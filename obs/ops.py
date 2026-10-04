"""Fila, agenda e worker seguro para operações administrativas."""
from __future__ import annotations
import concurrent.futures as cf
import os
import json, subprocess, sys, time, traceback, datetime as dt
from pathlib import Path
from . import config
from .db import connect

SCHEMA="""
CREATE TABLE IF NOT EXISTS ops_schedules(
 job TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, interval_minutes INTEGER,
 window_start TEXT DEFAULT '00:00', window_end TEXT DEFAULT '23:59',
 weekdays_only INTEGER NOT NULL DEFAULT 0, max_retries INTEGER NOT NULL DEFAULT 2,
 retry_delay_minutes INTEGER NOT NULL DEFAULT 5, next_run_ts INTEGER,
 last_run_ts INTEGER, last_status TEXT, last_message TEXT, updated_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ops_runs(
 id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, trigger TEXT NOT NULL,
 status TEXT NOT NULL, queued_ts INTEGER NOT NULL, started_ts INTEGER, finished_ts INTEGER,
 details TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_runs ON ops_runs(status, queued_ts);
-- Ajustes que o usuario controla pelo painel, sem editar codigo.
CREATE TABLE IF NOT EXISTS ops_config(
 chave TEXT PRIMARY KEY, valor TEXT NOT NULL, updated_ts INTEGER NOT NULL
);
"""

# Padroes dos ajustes operaveis pela Central. Quem decide quanto historico
# buscar e o usuario, nao o codigo: 150 paginas alcancaram 25/nov/2025 no
# Brazil Journal, mas isso varia por veiculo e por quanto ele ja baixou antes.
CONFIG_PADRAO = {
    "backfill_paginas": 150,      # profundidade do historico por RSS
    "intraday_intervalo": "1m",   # granularidade das barras coletadas
    "intraday_range": "5d",       # o Yahoo so retem 5 dias de 1m
    "ohlcv_range": "10y",         # cobre toda a serie diaria que o banco tem
    # do mais grosso ao mais fino: 1h cobre 720 dias por requisicao e 1m so 8,
    # entao se a coleta for interrompida o que ficou e a parte mais barata.
    "yf_intervalos": "1h,15m,5m,1m",
}


def get_config(chave, padrao=None):
    con = connect(); init(con)
    r = con.execute("SELECT valor FROM ops_config WHERE chave=?", (chave,)).fetchone()
    con.close()
    if r is None:
        return CONFIG_PADRAO.get(chave, padrao)
    v = r["valor"]
    pad = CONFIG_PADRAO.get(chave, padrao)
    if isinstance(pad, int):
        try:
            return int(v)
        except ValueError:
            return pad
    return v


def set_config(chave, valor):
    con = connect(); init(con)
    with con:
        con.execute("INSERT OR REPLACE INTO ops_config VALUES (?,?,?)",
                    (chave, str(valor), int(time.time())))
    con.close()
    return get_config(chave)


def config_atual():
    return {k: get_config(k) for k in CONFIG_PADRAO}


def _migra(con):
    """Acrescenta `worker_pid` sem destruir nada (ALTER TABLE e idempotente aqui).

    E fecha os runs que ficaram 'running' SEM pid. Eles sao, por construcao,
    anteriores a esta coluna -- ou seja, foram tomados por um worker de outra
    geracao do codigo, que ja nao existe. Deixa-los travaria o grupo deles ate
    a regra de idade (50 min) agir, e foi exatamente o que prendeu quatro jobs
    de documento aqui.
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(ops_runs)")}
    if "worker_pid" not in cols:
        with con:
            con.execute("ALTER TABLE ops_runs ADD COLUMN worker_pid INTEGER")
    with con:
        con.execute(
            "UPDATE ops_runs SET status='error', finished_ts=?, "
            "error='orfao: run anterior ao rastreio de pid' "
            "WHERE status='running' AND worker_pid IS NULL",
            (int(time.time()),))


def _vivo(pid) -> bool:
    """O processo que tomou este run ainda existe?"""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True            # existe, mas e de outro usuario
JOBS={
 "refresh_news":{"label":"Atualizar notícias (RSS + GDELT)","schedule":True},
 # SEPARADOS porque tem cadencia natural MUITO diferente. Os 24 feeds somam
 # ~10s e podem rodar a cada minuto; o GDELT exige 5,5s por consulta e nao
 # suporta isso. Juntos, o lento ditava o ritmo do rapido -- MEDIDO: a latencia
 # mediana entre publicacao e ingestao era de 62 minutos, o que torna qualquer
 # previsao de minutos impossivel antes mesmo do modelo.
 "refresh_rss":{"label":"Atualizar RSS (rápido, 1 min)","schedule":True},
 "refresh_gdelt":{"label":"Atualizar GDELT (lento)","schedule":True},
 # PONTUAR e passo proprio desde que o LLM virou o leitor padrao. Antes,
 # quem pontuava era, por acidente, o job de RSS -- ele chama link_all e
 # score.run sobre TODO o pendente, inclusive o que veio do GDELT. Com
 # `refresh_rss` desligado, materia do GDELT entrava e nunca virava nota.
 # Fica no grupo "noticia" de proposito: pontuar antes de coletar le fila
 # velha, e o grupo e o que garante a ordem (ver GRUPOS).
 "score_news":{"label":"Pontuar notícias (leitor ativo)","schedule":True},
 "collect_intraday":{"label":"Coletar barras de 1 minuto","schedule":True},
 # Profundidade controlavel pelo painel: ops_config.backfill_paginas.
 "backfill_rss":{"label":"Carregar histórico de notícias (RSS)","schedule":False},
 "refresh_prices":{"label":"Atualizar preços","schedule":True},
 # COMPLEMENTO, nao recoleta: preenche open/high/low/volume das barras que ja
 # existem SEM trocar nenhum fechamento. Precisa ser job separado de
 # `refresh_prices` justamente porque aquele SUBSTITUI a barra -- se o
 # fechamento muda, toda medicao ja aprovada passa a ser sobre outra serie.
 # Medido em 4/10/2026: 24.920 barras diarias com open e volume NULOS, porque
 # foram coletadas antes de o codigo ler esses campos. Nao e falta da fonte.
 "fill_ohlcv":{"label":"Completar OHLCV (sem trocar fechamento)","schedule":False},
 # UOL: DESCOBERTA (~1.800 tickers com id) e BID/ASK. Nao OHLCV -- o Yahoo ja
 # da, e dizer o contrario foi erro meu, corrigido em docs/precos-fontes.md.
 # Os tres passos sao jobs separados de proposito: descobrir e sondar sao caros
 # e raros (catalogo nao muda todo dia), coletar e a rotina. Juntar os tres
 # faria a rotina pagar o scraping do catalogo.
 # Yahoo chart v8 (period1=0): a serie INTEIRA numa requisicao por papel,
 # com adjclose e proventos. Nao e `refresh_prices` com outro nome -- aquele
 # pede 2 anos pelo endpoint curto e SUBSTITUI a barra; este traz o historico
 # todo e COMPLEMENTA. `yf_intraday` fica fora do agendamento porque desliza
 # janela de 8 dias para 1m: sao centenas de requisicoes por papel e isso e
 # backfill, nao rotina.
 "yf_diario":{"label":"Yahoo: histórico diário completo (+adjclose, proventos)","schedule":False},
 "yf_intraday":{"label":"Yahoo: intradiário deslizando a janela","schedule":False},
 "uol_descobrir":{"label":"UOL: descobrir papéis (catálogo)","schedule":False},
 "uol_sondar":{"label":"UOL: sondar papéis (data-id + validação)","schedule":False},
 "uol_coletar":{"label":"UOL: coletar cotações","schedule":True},
 "refresh_drivers":{"label":"Atualizar drivers","schedule":True},
 "refresh_cvm_registry":{"label":"Atualizar cadastro CVM","schedule":True},
 "refresh_ri":{"label":"Descobrir documentos de RI","schedule":True},
 "sync_itr":{"label":"Baixar ITR","schedule":True},
 "sync_dfp":{"label":"Baixar DFP","schedule":True},
 "extract_reports":{"label":"Processar PDFs pendentes","schedule":True},
 "analyze_reports_local":{"label":"Analisar PDFs localmente","schedule":True},
 "build_labels":{"label":"Atualizar rótulos D+1/D+5/D+20","schedule":False},
 "recalibrate_direction":{"label":"Recalibrar direção","schedule":False},
 "recalibrate_volatility":{"label":"Recalibrar agitação","schedule":False},
 "run_pead_backtest":{"label":"Experimento PEAD","schedule":False},
 "refresh_universe":{"label":"Revisar universo","schedule":True},
}
def init(con=None):
    own=con is None; con=con or connect()
    with con:
        con.executescript(SCHEMA)
    _migra(con)
    with con:
        for job in JOBS:
            con.execute("""INSERT OR IGNORE INTO ops_schedules(job,updated_ts) VALUES (?,?)""",(job,int(time.time())))
    if own: con.close()

# Piso de 1 minuto, nao 5. O piso de 5 existia quando todo job era lento; com
# `refresh_rss` custando ~10s ele passou a ser o que IMPEDE previsao de
# minutos -- MEDIDO: a latencia mediana publicacao->ingestao era de 62 min, e
# a diferenca entre isso e o p10 de 1,3 min e so cadencia de polling.
INTERVALO_MIN = 1


def _next(now, minutes):
    return int(now + max(INTERVALO_MIN,int(minutes or 15))*60)
def set_schedule(job, enabled, interval_minutes=15, window_start="00:00", window_end="23:59",
                 weekdays_only=False, max_retries=2, retry_delay_minutes=5):
    if job not in JOBS or not JOBS[job]["schedule"]: raise ValueError("job não agendável")
    now=int(time.time()); con=connect(); init(con)
    with con: con.execute("""UPDATE ops_schedules SET enabled=?,interval_minutes=?,window_start=?,window_end=?,
       weekdays_only=?,max_retries=?,retry_delay_minutes=?,next_run_ts=?,updated_ts=? WHERE job=?""",
       (int(bool(enabled)),max(INTERVALO_MIN,int(interval_minutes)),window_start,window_end,int(bool(weekdays_only)),
        max(0,int(max_retries)),max(1,int(retry_delay_minutes)),_next(now,interval_minutes) if enabled else None,now,job))
    con.close()
def enqueue(job, trigger="manual"):
    if job not in JOBS: raise ValueError("job inválido")
    con=connect(); init(con)
    with con:
        # evita duplicata pendente/executando
        row=con.execute("SELECT id FROM ops_runs WHERE job=? AND status IN ('queued','running')",(job,)).fetchone()
        if row: return {"queued":False,"id":row["id"],"reason":"já pendente ou executando"}
        cur=con.execute("INSERT INTO ops_runs(job,trigger,status,queued_ts) VALUES (?,?,?,?)",
                        (job,trigger,"queued",int(time.time())))
    con.close(); return {"queued":True,"id":cur.lastrowid}
def _within(row, now):
    d=dt.datetime.fromtimestamp(now)
    if row["weekdays_only"] and d.weekday()>=5: return False
    hm=d.strftime("%H:%M"); return row["window_start"]<=hm<=row["window_end"]
def materialize_due():
    now=int(time.time()); con=connect(); init(con); n=0
    rows=con.execute("SELECT * FROM ops_schedules WHERE enabled=1 AND next_run_ts<=?",(now,)).fetchall()
    for r in rows:
        if _within(r,now): enqueue(r["job"],"schedule"); n+=1
        with con: con.execute("UPDATE ops_schedules SET next_run_ts=? WHERE job=?",
                              (_next(now,r["interval_minutes"]),r["job"]))
    con.close(); return n
# O teto do subprocesso e a ULTIMA defesa, nao a primeira. A ingestao agora se
# autolimita em 900s (obs.ingest.TETO_RODADA_S) e salva o que coletou; este
# numero so existe para o caso de um comando travar de vez. Ele e maior que o
# teto interno de proposito: se os dois forem iguais, quem mata e o subprocesso
# -- e matar perde tudo, porque o `store` so roda no fim da coleta.
TIMEOUT_CLI = 2400


def _run_cli(args):
    return subprocess.run([sys.executable,"-m","obs.cli",*args],cwd=str(config.ROOT),
                          capture_output=True,text=True,timeout=TIMEOUT_CLI)
def execute(job):
    from . import reports, ri
    if job=="refresh_news":
        return _run_cli(["ingest","--timespan","1h"])
    if job=="refresh_rss":
        return _run_cli(["ingest-rss"])
    if job=="refresh_gdelt":
        return _run_cli(["ingest","--timespan","1h","--so-gdelt"])
    if job=="score_news":
        return _run_cli(["pontuar"])
    if job=="collect_intraday":
        return _run_cli(["intraday","--intervalo",get_config("intraday_intervalo"),
                         "--range",get_config("intraday_range")])
    if job=="backfill_rss":
        return _run_cli(["backfill-rss","--paginas",str(get_config("backfill_paginas", 150))])
    if job=="refresh_prices": return _run_cli(["prices","--range","2y"])
    if job=="fill_ohlcv":
        return _run_cli(["prices","--fonte","yahoo","--range",
                         get_config("ohlcv_range", "10y"), "--complementar"])
    if job=="yf_diario": return _run_cli(["yf-diario"])
    if job=="yf_intraday":
        return _run_cli(["yf-intraday", "--intervalos",
                         get_config("yf_intervalos", "1h,15m,5m,1m")])
    if job=="uol_descobrir": return _run_cli(["uol-descobrir"])
    if job=="uol_sondar": return _run_cli(["uol-sondar","--categorias","acao"])
    if job=="uol_coletar": return _run_cli(["uol-coletar","--periodo","months"])
    if job=="refresh_drivers": return _run_cli(["drivers","--range","2y"])
    if job in ("refresh_cvm_registry","refresh_universe"): return _run_cli(["universe-cvm"])
    if job=="refresh_ri":
        out=[]
        for t in (ri._empresas()).keys(): out.append(ri.sync(t, download=True))
        return {"ri":out}
    if job in ("sync_itr","sync_dfp"):
        return _run_cli(["contabil-sync","--ano",str(dt.date.today().year),"--tipo",job[-3:].upper()])
    if job=="extract_reports":
        con=connect(); reports.init(con); rows=con.execute("SELECT id FROM report_documents WHERE status IN ('registered','remote') AND local_path IS NOT NULL").fetchall(); con.close()
        return {"processed":[reports.extract_text(r["id"]) for r in rows]}
    if job=="analyze_reports_local":
        con=connect(); reports.init(con); rows=con.execute("SELECT id FROM report_documents WHERE status='extracted'").fetchall(); con.close()
        return {"processed":[reports.analyze(r["id"],external=False) for r in rows]}
    if job=="build_labels": return _run_cli(["horizons"])
    if job=="recalibrate_direction": return _run_cli(["calibrate","--horizon","1d"])
    if job=="recalibrate_volatility": return _run_cli(["calibrate-vol"])
    if job=="run_pead_backtest": return {"status":"blocked","reason":"consenso ou expectativa interna ainda não disponível"}
    raise ValueError("job sem executor")
# GRUPO de exclusao. Jobs do MESMO grupo nunca rodam ao mesmo tempo; grupos
# diferentes rodam em paralelo.
#
# POR QUE AGRUPAR EM VEZ DE SOLTAR TUDO: nao e medo de concorrencia no SQLite
# (esta em WAL, escrita serializa com espera de 30s). E ordem logica dentro do
# grupo -- `build_labels` depois de `refresh_prices` da rotulo com o preco
# novo; ao contrario, da rotulo velho e ninguem percebe. Entre grupos nao ha
# dependencia nenhuma: baixar PDF de RI nao tem relacao com buscar noticia,
# e fazer um esperar o outro so desperdica a janela.
GRUPOS = {
    "refresh_news": "noticia",
    "refresh_rss": "rss",          # grupo proprio: rapido, nao espera o GDELT
    "refresh_gdelt": "noticia",    # mesmo grupo do ingest completo: ambos usam a cota
    "score_news": "noticia",       # depende do que a coleta acabou de gravar
    "collect_intraday": "mercado",
    "backfill_rss": "rss",
    "refresh_prices": "mercado", "refresh_drivers": "mercado",
    "fill_ohlcv": "mercado", "yf_diario": "mercado",
    "yf_intraday": "mercado",
    # mesmo grupo: sondar depende do catalogo, coletar depende da sondagem.
    # O grupo e o que garante a ordem (ver o comentario de GRUPOS).
    "uol_descobrir": "uol", "uol_sondar": "uol", "uol_coletar": "uol",
    "refresh_cvm_registry": "cadastro", "refresh_universe": "cadastro",
    "refresh_ri": "documento", "sync_itr": "documento", "sync_dfp": "documento",
    "extract_reports": "documento", "analyze_reports_local": "documento",
    "build_labels": "modelo", "recalibrate_direction": "modelo",
    "recalibrate_volatility": "modelo", "run_pead_backtest": "modelo",
}
MAX_PARALELO = 4


def _finaliza(run_id, job, status, details, err):
    con = connect(); init(con); now = int(time.time())
    with con:
        con.execute("UPDATE ops_runs SET status=?,finished_ts=?,details=?,error=? WHERE id=?",
                    (status, now, json.dumps(details, ensure_ascii=False), err, run_id))
        con.execute("UPDATE ops_schedules SET last_run_ts=?,last_status=?,last_message=? WHERE job=?",
                    (now, status, (err or "ok")[:1000], job))
    con.close()


def _executa_run(run_id, job):
    try:
        res = execute(job)
        if isinstance(res, subprocess.CompletedProcess):
            ok = res.returncode == 0
            details = {"stdout": res.stdout[-8000:], "stderr": res.stderr[-4000:],
                       "returncode": res.returncode}
        else:
            ok = True; details = res
        status = "done" if ok else "error"
        err = None if ok else details.get("stderr", "erro")
    except Exception:                                        # noqa: BLE001
        status = "error"; details = {}; err = traceback.format_exc()
    _finaliza(run_id, job, status, details, err)
    return status


# Run que fica 'running' alem disto e orfao: o worker que o tomou morreu.
IDADE_ORFAO_S = TIMEOUT_CLI + 600


def recupera_orfaos(con) -> int:
    """Fecha runs presos em 'running' por worker que morreu.

    SEM ISTO O SISTEMA TRAVA, e em silencio: `_reivindica` trata grupo com job
    'running' como ocupado, entao um worker morto no meio de `refresh_ri`
    bloqueia TODO o grupo 'documento' -- nenhum PDF volta a ser baixado e nada
    no painel diz por que. MEDIDO: aconteceu aqui, com `analyze_reports_local`,
    `extract_reports`, `sync_dfp` e `sync_itr` parados em 'queued' atras de um
    `refresh_ri` cujo processo nao existia mais.

    DUAS REGRAS, e a primeira e a que importa:
      1. PID MORTO -> orfao na hora. Checar o processo e exato; esperar pelo
         relogio e chute. Vale sobretudo para `refresh_ri` e os outros jobs
         que rodam em processo (nao via `_run_cli`) e portanto nao tem timeout
         nenhum para socorre-los.
      2. IDADE, so para runs sem `worker_pid` -- linhas antigas, gravadas antes
         desta coluna existir.
    """
    agora = int(time.time())
    corte = agora - IDADE_ORFAO_S
    n = 0
    with con:
        for r in con.execute(
                "SELECT id, job, worker_pid, started_ts FROM ops_runs "
                "WHERE status='running'").fetchall():
            pid = r["worker_pid"]
            if pid is None:
                orfao = (r["started_ts"] or 0) < corte
                motivo = "sem pid registrado e parado ha muito tempo"
            else:
                orfao = not _vivo(pid)
                motivo = f"processo {pid} nao existe mais"
            if not orfao:
                continue
            con.execute(
                "UPDATE ops_runs SET status='error',finished_ts=?,error=? WHERE id=?",
                (agora, f"orfao: {motivo}", r["id"]))
            n += 1
    return n


def _reivindica(maximo=MAX_PARALELO):
    """Marca como 'running' ate `maximo` jobs de grupos DISTINTOS e livres."""
    materialize_due()
    con = connect(); init(con)
    n_orf = recupera_orfaos(con)
    if n_orf:
        print(f"[worker] {n_orf} run(s) orfao(s) liberado(s)", flush=True)
    ocupados = {GRUPOS.get(r["job"], r["job"]) for r in con.execute(
        "SELECT job FROM ops_runs WHERE status='running'").fetchall()}
    fila = con.execute(
        "SELECT * FROM ops_runs WHERE status='queued' ORDER BY queued_ts").fetchall()
    pegos = []
    with con:
        for r in fila:
            if len(pegos) >= maximo:
                break
            g = GRUPOS.get(r["job"], r["job"])
            if g in ocupados:
                continue                     # grupo ja tem job rodando
            ocupados.add(g)
            con.execute("UPDATE ops_runs SET status='running',started_ts=?,"
                        "worker_pid=? WHERE id=?",
                        (int(time.time()), os.getpid(), r["id"]))
            pegos.append((r["id"], r["job"]))
    con.close()
    return pegos


def work_once():
    """Um job, em primeiro plano. Mantido para uso manual e para teste."""
    pegos = _reivindica(maximo=1)
    if not pegos:
        return False
    _executa_run(*pegos[0])
    return True


def work_batch(maximo=MAX_PARALELO):
    """Ate `maximo` jobs de grupos distintos, em paralelo. Devolve quantos."""
    pegos = _reivindica(maximo)
    if not pegos:
        return 0
    if len(pegos) == 1:
        _executa_run(*pegos[0])
        return 1
    with cf.ThreadPoolExecutor(max_workers=len(pegos)) as pool:
        list(pool.map(lambda t: _executa_run(*t), pegos))
    return len(pegos)


def worker_loop(seconds=20, paralelo=MAX_PARALELO):
    while True:
        n = work_batch(paralelo)
        if n:
            print(f"[worker] {n} job(s) concluido(s)", flush=True)
        time.sleep(max(5, int(seconds)))
def state():
    con=connect(); init(con)
    sch=[dict(r) for r in con.execute("SELECT * FROM ops_schedules ORDER BY job").fetchall()]
    runs=[dict(r) for r in con.execute("SELECT * FROM ops_runs ORDER BY id DESC LIMIT 80").fetchall()]
    con.close()
    return {"jobs":JOBS,"schedules":sch,"runs":runs,"config":config_atual(),"worker_note":"execute `python -m obs.cli worker` em processo separado"}
