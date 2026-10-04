"""Painel web em stdlib (http.server) -- sem FastAPI, sem uvicorn.

Endpoints:
  GET /                  painel
  GET /api/signals       sinal + probabilidades de todos os papeis
  GET /api/ticker/<T>    detalhe com as manchetes que formaram o sinal
  GET /api/alarms        ultimos alarmes
  GET /api/status        estado de calibracao e contagens
  GET /acao.html?t=<T>   pagina do papel: preco com as noticias por cima
  GET /api/chart/<T>     cotacoes diarias + noticias pontuadas (?dias=365; 0 = tudo)

  /api/signals e /api/ticker/<T> aceitam ?horizonte=abertura|d1|d5 (padrao d1).
  Num horizonte sem medicao a cabeca sai zerada: a tela mostra o selo, nunca
  um numero (ver obs/medidas.py).
"""
from __future__ import annotations
import datetime as dt
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import (aggregate, alarms as alarm_mod, config, contabil, drivers,
               externo, medidas, notify, pergunta, reports, surpresa, ops,
               score as score_mod)
from .config import ROOT
from .db import connect
from .dedupe import cluster_size
from .util import iso

# Resolvido em serve(); None = decide na hora pelo padrao do projeto
# (obs/score.py:resolver) e pela cobertura (aggregate.escolher_scorer).
SCORER = None

# O painel atualiza a cada 2 min e pode estar aberto em varias abas. Com uma
# watchlist grande (centenas de papeis) recalcular tudo a cada GET e caro, e
# cada rodada ainda grava uma linha em `signals`. Cache curto resolve os dois.
SIGNALS_TTL_S = 60
_SIG_LOCK = threading.Lock()
_SIG_CACHE: dict = {"ts": 0.0, "data": None}


def _signals():
    with _SIG_LOCK:
        if _SIG_CACHE["data"] is not None and time.time() - _SIG_CACHE["ts"] < SIGNALS_TTL_S:
            return _SIG_CACHE["data"]
        sigs = aggregate.run(scorer=SCORER, verbose=False)
        ev = alarm_mod.evaluate(sigs, scorer=_scorer_ativo())
        if ev:
            notify.deliver(ev)
        meta = config.tickers()
        cad = _cadeias()
        out = []
        for s in sigs:
            m = meta.get(s["ticker"], {}) or {}
            # as manchetes ficam de fora: o painel as busca em /api/ticker/<T>
            # so para o papel aberto, e com 400 papeis elas pesariam megabytes
            row = {k: v for k, v in s.items() if k != "items"}
            row["name"] = m.get("name", s["ticker"])
            row["sector"] = m.get("sector")
            c = cad["papeis"].get(s["ticker"])
            row["cadeia_top"] = c["top"][0]["driver"] if c else None   # p/ busca/filtro
            out.append(row)
        _SIG_CACHE.update(ts=time.time(), data=out)
        return out


def _signals_h(hid: str | None) -> list[dict]:
    """Sinais com so o que tem lastro no horizonte pedido."""
    return [medidas.aplicar(s, hid) for s in _signals()]


# ---------------------------------------------------- cadeia de afetacao ---
# Reestimada uma vez por dia de dado novo (ultima cotacao + ultimo driver).
_CAD_LOCK = threading.Lock()
_CAD_CACHE: dict = {"chave": None, "data": None}
CADEIA_TOP = 4
CADEIA_NOTA = ("Descritiva: regressão múltipla (ridge) dos retornos diários do papel nos "
               "drivers, janela de 250 pregões. O teste de permutação desta cadeia NÃO foi "
               "feito; ela não entra em nenhuma probabilidade.")


def _cadeias() -> dict:
    con = connect()
    try:
        drivers.init()
        chave = (con.execute("SELECT MAX(date) FROM prices").fetchone()[0],
                 con.execute("SELECT MAX(date) FROM driver_prices").fetchone()[0])
    finally:
        con.close()
    with _CAD_LOCK:
        if _CAD_CACHE["chave"] == chave and _CAD_CACHE["data"] is not None:
            return _CAD_CACHE["data"]
        from .prices import returns_by_date
        con = connect()
        rets = returns_by_date(con)
        con.close()
        tk = config.tickers()
        asof = (dt.date.today() + dt.timedelta(days=1)).isoformat()   # usa tudo ate hoje
        try:
            exps = drivers.fit_exposures({k: v for k, v in rets.items() if k in tk},
                                         asof, persist=False)
        except Exception:                                # noqa: BLE001 (sem drivers)
            exps = {}
        papeis = {}
        for tkr, e in exps.items():
            top = drivers.affect_index(e, top=CADEIA_TOP)
            papeis[tkr] = {
                "r2": round(e["r2"], 3), "n": e["n"],
                "top": [{"driver": k, "categoria": drivers.DRIVERS.get(k, ("", "?"))[1],
                         "share": round(sh, 4), "beta": round(b, 6),
                         "sinal": 1 if b > 0 else -1} for k, sh, b in top]}
        r2s = [p["r2"] for p in papeis.values()]
        data = {"papeis": papeis, "asof": {"precos": chave[0], "drivers": chave[1]}, "janela": 250, "n_drivers": len(drivers.DRIVERS),
                "r2_min": min(r2s) if r2s else None, "r2_max": max(r2s) if r2s else None,
                "permutacao_feita": False, "nota": CADEIA_NOTA}
        _CAD_CACHE.update(chave=chave, data=data)
        return data


def _cadeia(tkr: str) -> dict | None:
    cad = _cadeias()
    c = cad["papeis"].get(tkr)
    if not c:
        return None
    return {**c, "asof": cad["asof"], "permutacao_feita": False, "nota": cad["nota"]}


def _ticker(tkr: str, hid: str | None) -> dict:
    d = aggregate.compute(tkr, scorer=_scorer_ativo())
    # faixa ordinal da agitacao e relativa a watchlist: vem do lote completo
    lote = {s["ticker"]: s for s in _signals()}
    if tkr in lote:
        for k in ("vol_faixa", "vol_ordem"):
            d[k] = lote[tkr].get(k)
    m = config.tickers().get(tkr, {}) or {}
    d["name"], d["sector"] = m.get("name", tkr), m.get("sector")
    d = medidas.aplicar(d, hid)
    d["cadeia"] = _cadeia(tkr)
    # Sensibilidade deste papel a surpresa macro. Vem sempre marcada como nao
    # validada: a dispersao transversal dos betas reprovou no teste de
    # permutacao, entao isto e leitura descritiva e nao entra em probabilidade.
    try:
        sens = surpresa.sensibilidade(tkr)
        pode, motivo = surpresa.disponivel()
        d["surpresa"] = {"validado": bool(pode), "motivo": motivo,
                         "indicadores": sens} if sens else None
    except Exception:                                            # noqa: BLE001
        d["surpresa"] = None
    # Agenda conhecida ANTES do evento. Entra como contexto candidato da
    # cabeca de volatilidade; nunca altera z, alta ou queda sem validação.
    try:
        inicio = dt.date.fromtimestamp(d["asof_ts"])
        d["eventos_externos"] = externo.contexto_pre_evento(d.get("cadeia"), inicio=inicio)
    except Exception:                                            # noqa: BLE001
        d["eventos_externos"] = None
    return d


# 1sem NAO vem de coleta: e agregado do proprio diario. Buscar semanal numa
# fonte externa duplicaria dado que ja temos e abriria divergencia entre as
# duas series. 15m e 1m/5m/1h vem da tabela `intraday`.
GRANS_VALIDAS = ("1sem", "1d", "1h", "15m", "5m", "1m")
GRANS_INTRADAY = ("1h", "15m", "5m", "1m")


def _semanal(prices: list) -> list:
    """Agrega o diario por semana ISO, usando o ULTIMO fechamento da semana."""
    porsem: dict = {}
    for d, c in prices:
        ano, sem, _ = dt.date.fromisoformat(d).isocalendar()
        porsem[(ano, sem)] = (d, c)          # sobrescreve: fica o ultimo
    return [v for _k, v in sorted(porsem.items())]


def _granularidades_disponiveis(con, tkr: str) -> dict:
    """Quais granularidades tem dado para ESTE papel, e quanto.

    A UI usa para DESABILITAR o que nao tem dado, em vez de mostrar grafico
    vazio -- que o usuario le como defeito e nao como ausencia.
    """
    out = {}
    n_d = con.execute("SELECT COUNT(*) FROM prices WHERE ticker=?", (tkr,)).fetchone()[0]
    out["1d"] = {"barras": n_d, "tem": n_d > 1}
    out["1sem"] = {"barras": n_d // 5, "tem": n_d > 10}
    for g in GRANS_INTRADAY:
        r = con.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM intraday WHERE simbolo=? AND intervalo=?",
            (tkr, g)).fetchone()
        out[g] = {"barras": r[0], "tem": (r[0] or 0) > 1,
                  "de": iso(r[1]) if r[1] else None,
                  "ate": iso(r[2]) if r[2] else None}
    return out


def _chart(tkr: str, dias: int, gran: str = "1d") -> dict:
    """`gran` escolhe a granularidade da serie de preco: 1d, 1h, 5m ou 1m.

    O dado intradiario vem da tabela `intraday`, nao de `prices` -- sao
    coletas diferentes, com retencao diferente (o Yahoo guarda 5 dias de 1m e
    2 anos de 1h). Quando nao ha barra na granularidade pedida a resposta diz
    isso em `aviso`, em vez de cair silenciosamente para o diario e o usuario
    achar que esta vendo minuto.
    """
    if gran == "1sem":
        out = _chart_diario(tkr, dias)
        out["prices"] = _semanal(out["prices"])
        out["granularidade"] = "1sem"
        out["intradia"] = False
        con = connect()
        out["granularidades"] = _granularidades_disponiveis(con, tkr)
        con.close()
        return out
    if gran != "1d":
        from . import intraday as _intra
        con = connect()
        _intra.init(con)
        since = int(time.time()) - max(1, dias) * 86400
        linhas = [[r["ts"], r["close"]] for r in con.execute(
            "SELECT ts, close FROM intraday WHERE simbolo=? AND intervalo=? "
            "AND ts>=? ORDER BY ts", (tkr, gran, since)).fetchall()]
        con.close()
        base = _chart_diario(tkr, dias)
        base["prices"] = [[iso(t), c] for t, c in linhas]
        base["granularidade"] = gran
        base["intradia"] = True
        # RECORTA A NOTICIA AO PERIODO QUE TEM BARRA. O intradiario so retem
        # alguns dias (1m = 5), entao pedir 90 dias traz 3 meses de noticia e
        # 5 dias de preco. Marcador sem preco nao e so feio: `priceAt`
        # extrapola para o PRIMEIRO fechamento da serie, logo uma noticia de
        # agosto era desenhada na altura do preco de setembro -- posicao
        # errada apresentada como se fosse certa.
        if linhas:
            t0, t1 = linhas[0][0], linhas[-1][0]
            antes = len(base.get("news") or [])
            base["news"] = [n for n in base["news"] if t0 <= n["ts"] <= t1]
            ocultas = antes - len(base["news"])
            if ocultas:
                base["noticias_ocultas"] = ocultas
                base["aviso"] = (
                    f"{ocultas} notícia(s) fora do período com barras de {gran}. "
                    f"A fonte só retém alguns dias nessa granularidade; use Dia "
                    f"para ver o histórico completo.")
        con2 = connect()
        base["granularidades"] = _granularidades_disponiveis(con2, tkr)
        con2.close()
        if not linhas:
            base["aviso"] = (f"sem barras de {gran} para {tkr}. Colete com "
                             f"`obs intraday --intervalo {gran}` ou pelo job "
                             "'Coletar barras' na Central.")
        return base
    out = _chart_diario(tkr, dias)
    out["granularidade"] = "1d"
    out["intradia"] = False
    con = connect()
    out["granularidades"] = _granularidades_disponiveis(con, tkr)
    con.close()
    return out


def _chart_diario(tkr: str, dias: int) -> dict:
    """Cotacoes diarias + todas as noticias pontuadas do papel no periodo.

    `w` aqui e o peso da noticia SEM o decaimento de recencia (que so faz
    sentido "agora"): veiculo x relevancia x novidade x materialidade."""
    src_cfg = config.sources()
    con = connect()
    if dias > 0:
        cut_date = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
        since_ts = int(time.time()) - dias * 86400
    else:
        cut_date, since_ts = "0000-00-00", 0
    prices = [[r["date"], r["close"]] for r in con.execute(
        "SELECT date, close FROM prices WHERE ticker=? AND date>=? ORDER BY date",
        (tkr, cut_date)).fetchall()]
    rows = con.execute("""
        SELECT a.id, a.published_ts, a.title, a.url, a.domain,
               sc.s, sc.magnitude, sc.novelty, sc.event_type, m.relevance
        FROM scores sc
        JOIN mentions m ON m.article_id=sc.article_id AND m.ticker=sc.ticker
        JOIN articles a ON a.id=sc.article_id
        WHERE sc.ticker=? AND sc.scorer=? AND a.published_ts>=?
        ORDER BY a.published_ts""", (tkr, _scorer_ativo(), since_ts)).fetchall()
    news = []
    for r in rows:
        w = (aggregate.source_weight(r["domain"], src_cfg) * r["relevance"]
             * r["novelty"] * r["magnitude"])
        news.append({"ts": r["published_ts"], "when": iso(r["published_ts"]),
                     "title": r["title"], "url": r["url"], "domain": r["domain"],
                     "s": r["s"], "magnitude": r["magnitude"], "novelty": round(r["novelty"], 3),
                     "relevance": round(r["relevance"], 3), "event_type": r["event_type"],
                     "w": round(w, 4), "cluster_size": cluster_size(con, r["id"])})
    con.close()
    m = config.tickers().get(tkr, {}) or {}
    return {"ticker": tkr, "name": m.get("name", tkr), "sector": m.get("sector"),
            "dias": dias, "scorer": _scorer_ativo(), "prices": prices, "news": news,
            # datas REAIS de divulgacao de resultado (protocolo na CVM), para
            # o grafico marcar. Diferente da data do IPCA, que e aproximada.
            "divulgacoes": contabil.calendario(tkr)}


def _alarm_list(limit=40):
    con = connect()
    rows = con.execute(
        "SELECT ts,ticker,direction,p,base,edge,n_eff,message FROM alarm_events"
        " ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [{**dict(r), "when": iso(r["ts"])} for r in rows]


def _scorer_ativo() -> str:
    """O leitor que de fato responde a esta requisicao.

    Nao e constante: o proxy pode ter caido depois do `serve`, e a cobertura
    muda conforme a pontuacao avanca. Resolver por requisicao custa duas
    contagens no SQLite e evita a tela vazia que se le como "nao ha noticia".
    """
    return aggregate.escolher_scorer(scorer=SCORER)[0]


def _status():
    con = connect()
    one = lambda s: con.execute(s).fetchone()[0]
    q_men = "SELECT COUNT(*) FROM mentions WHERE ticker != '__none__'"
    st = {
        "articles": one("SELECT COUNT(*) FROM articles"),
        "mentions": one(q_men),
        "scores": one("SELECT COUNT(*) FROM scores"),
        "labels": one("SELECT COUNT(*) FROM labels"),
        "prices": one("SELECT COUNT(*) FROM prices"),
        "alarms": one("SELECT COUNT(*) FROM alarm_events"),
        "calibrators": [],
    }
    for r in con.execute("SELECT name,n,fitted_ts,metrics FROM calibrators").fetchall():
        st["calibrators"].append({"name": r["name"], "n": r["n"],
                                  "fitted": iso(r["fitted_ts"]),
                                  "metrics": json.loads(r["metrics"])})
    # DIAS, nao rotulos. Um dia de operacao gera dezenas de sinais por papel
    # (um por rodada de `signals`), e todos apontam para o MESMO retorno de
    # D+1. Contar rotulos superestima a amostra por um fator enorme: MEDIDO,
    # 85 sinais da PETR4, 85 asof distintos, UM unico dia. Amanha isso viraria
    # 850 "rotulos" que sao 10 observacoes independentes, e MIN_N=120 abriria
    # a porta com dado replicado. O que conta e DIA DE PREGAO distinto.
    st["dias_sinal"] = one(
        "SELECT COUNT(DISTINCT date(asof_ts,'unixepoch')) FROM signals")
    st["sinais_por_dia"] = round(
        one("SELECT COUNT(*) FROM signals") / max(1, st["dias_sinal"]), 1)
    con.close()
    nomes = {c["name"] for c in st["calibrators"]}
    st["calibrated"] = {"up:1d", "down:1d"} <= nomes
    vol = next((c for c in st["calibrators"] if c["name"] == "vol:1d"), None)
    st["agitacao"] = {"calibrado": bool(vol and vol["metrics"].get("calibrado")),
                      "calibrador": vol,
                      "como_calibrar": "python3 -m obs.cli calibrate-vol"}
    st["surpresa"] = surpresa.estado()
    # QUEM LE A NOTICIA. Vai para a tela porque a troca de leitor muda o que
    # `z` significa: a mesma manchete pontuada pelo lexico e pelo LLM nao da o
    # mesmo numero, e o painel nao pode esconder qual dos dois produziu a
    # coluna. `validado: False` e deliberado -- o ganho incremental do leitor
    # novo ainda nao foi medido (scripts/ouro_llm.py).
    st["scorer"] = {**score_mod.estado(), "validado": False,
                    "nota": ("troca de leitor mede-se por ganho incremental "
                             "fora da amostra; rode scripts/ouro_llm.py e "
                             "scripts/evento_noticia.py antes de tratar o "
                             "LLM como melhoria comprovada")}
    st["medidas"] = medidas.MEDIDAS
    st["horizontes"] = medidas.HORIZONTES
    # PORTAS POR CABECA. Sem isto o front escrevia o criterio a mao e errava:
    # anunciava a porta da agitacao (500 / 0,55 / 0,01) como se fosse a da
    # direcao. Numero de qualidade nao pode morar no HTML.
    st["portas"] = medidas.portas()
    # A ULTIMA TENTATIVA de calibrar a direcao, aprovada ou nao. Distingue
    # "ainda nao houve tentativa" de "houve e reprovou" -- o painel dizia a
    # primeira coisa nos dois casos.
    _t = next((c for c in st["calibrators"]
               if c["name"] == "tentativa:direcao:1d"), None)
    st["direcao_tentativa"] = _t["metrics"] if _t else None
    st["horizonte_padrao"] = medidas.HORIZONTE_PADRAO
    try:
        cad = _cadeias()
        st["cadeia"] = {k: cad[k] for k in ("asof", "janela", "n_drivers", "r2_min", "r2_max",
                                            "permutacao_feita", "nota")}
        st["cadeia"]["papeis"] = len(cad["papeis"])
    except Exception as exc:                             # noqa: BLE001
        st["cadeia"] = {"erro": str(exc)}
    return st


class _Prov:
    """Fonte de fatos para obs.pergunta, sem import circular.

    Passa pelos MESMOS caminhos que servem a tela (cache de sinais incluso), de
    modo que a IA nunca ve um numero diferente do que o usuario esta olhando.
    """

    def __init__(self, hid: str | None):
        self.hid = hid

    def signals(self):
        return _signals_h(self.hid)

    def ticker(self, tkr: str):
        return _ticker(tkr, self.hid)

    def status(self):
        return _status()

    def ops_state(self):
        return ops.state()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):            # silencia o log por requisicao
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)
        try:
            if path in ("/", "/index.html"):
                html = (ROOT / "web" / "index.html").read_bytes()
                return self._send(html, "text/html; charset=utf-8")
            if path in ("/admin", "/admin.html"):
                html = (ROOT / "web" / "admin.html").read_bytes()
                return self._send(html, "text/html; charset=utf-8")
            if path in ("/acao", "/acao.html") or path.startswith("/acao/"):
                html = (ROOT / "web" / "acao.html").read_bytes()
                return self._send(html, "text/html; charset=utf-8")
            if path.startswith("/files/report/"):
                try:
                    rid = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    return self._json({"error": "id inválido"}, 400)
                f = reports.file_for_report(rid)
                if not f:
                    return self._json({"error": "PDF local não disponível"}, 404)
                return self._send(f.read_bytes(), "application/pdf")
            if path.startswith("/api/report/"):
                try:
                    rid = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    return self._json({"error": "id inválido"}, 400)
                r = reports.get_report(rid)
                return self._json(r or {"error": "relatório não encontrado"}, 200 if r else 404)
            if path.startswith("/api/chart/"):
                tkr = path.rsplit("/", 1)[-1].upper()
                if tkr not in config.tickers():
                    return self._json({"error": "ticker fora da watchlist"}, 404)
                gran = (qs.get("gran") or ["1d"])[0]
                if gran not in GRANS_VALIDAS:
                    return self._json(
                        {"error": "gran deve ser " + ", ".join(GRANS_VALIDAS)}, 400)
                try:
                    dias = int((qs.get("dias") or ["365"])[0])
                except ValueError:
                    dias = 365
                return self._json(_chart(tkr, max(0, min(dias, 36500)), gran))
            hid = (qs.get("horizonte") or [None])[0]
            if path == "/api/signals":
                h = medidas.horizonte(hid)
                return self._json({"signals": _signals_h(h["id"]), "horizonte": h})
            if path.startswith("/api/ticker/"):
                tkr = path.rsplit("/", 1)[-1].upper()
                if tkr not in config.tickers():
                    return self._json({"error": "ticker fora da watchlist"}, 404)
                return self._json(_ticker(tkr, hid))
            if path.startswith("/api/calendario/"):
                tkr = path.rsplit("/", 1)[-1].upper()
                return self._json({"ticker": tkr,
                                   "divulgacoes": contabil.calendario(tkr)})
            if path == "/api/externos":
                pode, motivo = externo.disponivel()
                return self._json({
                    "ativo": externo.ATIVO, "pode": pode, "motivo": motivo,
                    "eventos": [{"nome": k, "instrumento": v["instr"], "nota": v["nota"],
                                 **externo.RESULTADOS.get(k, {})}
                                for k, v in externo.EVENTOS.items()],
                    "agenda": externo.agenda()})
            if path == "/api/surpresas":
                ind = (qs.get("indicador", ["IPCA"])[0] or "IPCA")
                return self._json(surpresa.impacto_por_papel(ind))
            if path == "/api/alarms":
                return self._json({"alarms": _alarm_list()})
            if path == "/api/admin/state":
                return self._json(ops.state())
            if path == "/api/ia/estado":
                return self._json(pergunta.estado())
            if path == "/api/status":
                return self._json(_status())
            return self._json({"error": "not found"}, 404)
        except Exception as exc:                                  # noqa: BLE001
            return self._json({"error": str(exc)}, 500)


    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(n).decode("utf-8") if n else "{}")
            path = urlparse(self.path).path
            if path == "/api/admin/run":
                return self._json(ops.enqueue(str(data.get("job") or ""), "manual"))
            if path == "/api/perguntar":
                # A IA so le. Propor tarefa e permitido; executar nao -- quem
                # enfileira continua sendo /api/admin/run, por clique humano.
                tkr = str(data.get("ticker") or "").upper() or None
                if tkr and tkr not in config.tickers():
                    return self._json({"error": "ticker fora da watchlist"}, 404)
                hid = medidas.horizonte(data.get("horizonte"))["id"]
                return self._json(pergunta.responder(
                    str(data.get("pergunta") or ""), _Prov(hid),
                    escopo=str(data.get("escopo") or "painel"), ticker=tkr))
            if path == "/api/admin/schedule":
                ops.set_schedule(
                    str(data.get("job") or ""), bool(data.get("enabled")),
                    data.get("interval_minutes", 15), data.get("window_start", "00:00"),
                    data.get("window_end", "23:59"), bool(data.get("weekdays_only")),
                    data.get("max_retries", 2), data.get("retry_delay_minutes", 5))
                return self._json({"ok": True})
            return self._json({"error": "rota não encontrada"}, 404)
        except Exception as exc:                                  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)


def serve(port: int = 8000, scorer: str | None = None):
    global SCORER
    SCORER = scorer
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Observatorio em http://127.0.0.1:{port}  (Ctrl+C para parar)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando")
    finally:
        srv.server_close()
