"""CLI do observatorio.  python3 -m obs.cli <comando>"""
from __future__ import annotations
import argparse
import json
import sys

from . import (aggregate, alarms, calibrate, contabil, cvm_ipe, db, dedupe,
               drivers, entity, historico, ingest, label, notify, prices,
               surpresa, reports, earnings, universe, ri, ops)
from .config import tickers
from .db import connect
from .util import iso, now_ts

SCORERS_CLI = ["lexicon", "llm", "ensemble"]
AJUDA_SCORER = ("quem le a noticia; vazio = padrao do projeto (llm, ou "
                "OBS_SCORER). Sem proxy autorizado, cai para lexicon dizendo "
                "que caiu")
AJUDA_HISTORICO = ("ler 10 anos de manchete com um modelo que ja sabe o "
                   "desfecho contamina o backtest; use --scorer llm aqui "
                   "somente para amostra de auditoria")


def cmd_init(a):
    db.init(); print("banco inicializado")


def cmd_ingest(a):
    db.init()
    ingest.run(timespan=a.timespan, so_gdelt=getattr(a, "so_gdelt", False))


def _pontuar(scorer=None):
    """Liga mencoes, agrupa duplicatas e pontua. A ordem IMPORTA: `novelty` e
    lida no momento em que o score e gravado, entao agrupar depois de pontuar
    daria peso maximo a republicacao.

    Existe como funcao porque `ingest-rss` e `pontuar` precisam da MESMA
    sequencia, e porque o scorer tem de vir de um lugar so. Antes, cada ponto
    do pipeline tinha "lexicon" escrito no codigo: pedir --scorer llm no
    `cycle` nao mudava o que a rodada rapida de RSS gravava.
    """
    from . import score
    men = entity.link_all()
    dedupe.cluster()
    pts = score.run(scorer=scorer)
    return men, pts


def cmd_ingest_rss(a):
    """So os feeds. Rapido de proposito: ~10s para os 24, logo pode rodar a
    cada minuto. E a unica via com chance de capturar reacao de minutos --
    o GDELT exige 5,5s por consulta e nao cabe nessa cadencia.

    CUSTO DO LEITOR NOVO: com `--scorer llm`, cada materia INEDITA vale uma
    chamada. Repeticao nao paga (reuso por cluster) e repontuacao nao paga
    (cache), mas numa cadencia de 1 minuto quem decide o teto e
    OBS_LLM_MAX_CHAMADAS. Para fixar o lexico so aqui: --scorer lexicon.
    """
    db.init()
    rows = ingest.fetch_rss()
    novos = ingest.store(rows)
    men, pts = _pontuar(a.scorer)
    print(f"-> {len(rows)} coletados, {novos} novos, {men} mencoes, {pts} pontuados")


def cmd_pontuar(a):
    """Liga, agrupa e pontua o que ja esta no banco. Sem rede de noticia.

    POR QUE E COMANDO PROPRIO: `ingest` (GDELT) coleta e nao pontua. Quem
    pontuava o GDELT era, por acidente, a rodada de RSS -- ela chama
    `link_all`/`score.run` sobre TODO o pendente. Com o job `refresh_rss`
    desligado, a materia do GDELT entrava e nunca virava nota.
    """
    db.init()
    men, pts = _pontuar(a.scorer)
    print(f"-> {men} mencoes, {pts} pares pontuados")


def cmd_intraday(a):
    from . import intraday
    alvo = {t: f"{t}.SA" for t in tickers()}
    alvo.update({k: drivers.DRIVERS[k][0] for k in ("USDBRL", "BRENT", "DXY")})
    n = intraday.sync(alvo, intervalo=a.intervalo, rng=a.range)
    print(f"-> {n} barras de {a.intervalo} gravadas")


def cmd_link(a):
    print(f"-> {entity.link_all()} mencoes ligadas")


def cmd_cluster(a):
    print(f"-> {dedupe.cluster()} artigos agrupados na janela")


def cmd_score(a):
    print(f"-> {score_mod_run(a.scorer)} pares (artigo,ticker) pontuados")


def score_mod_run(scorer):
    from . import score
    return score.run(scorer=scorer)


def cmd_classificar(a):
    """Recomputa tipo de evento e orientacao temporal no acervo."""
    from . import evento
    evento.reclassificar(scorer=a.scorer, aplicar=a.aplicar)


def cmd_score_estado(a):
    """Quem le a noticia, com que autorizacao e com que cobertura."""
    from . import score
    e = score.estado()
    print(f"leitor padrao   : {e['padrao']}")
    print(f"leitor efetivo  : {e['efetivo']}  ({e['motivo']})")
    print(f"LLM autorizado  : {'SIM' if e['llm_autorizado'] else 'NAO'} "
          f"-- {e['llm_motivo']}")
    print(f"modelo          : {e['modelo'] or '(nao definido)'}")
    print(f"versao do prompt: {e['prompt_versao']}")
    print(f"cache de leitura: {e['cache']} resposta(s)")
    print("cobertura por leitor:")
    for k, v in (e.get("cobertura") or {}).items():
        print(f"  {k:<10} {v:>8} pares")
    print(f"pendentes para '{e['efetivo']}': {e.get('pendentes')}")
    if e.get("erro"):
        print(f"ERRO: {e['erro']}")


def cmd_prices(a):
    prices.sync(range_=a.range, fonte=a.fonte)


def cmd_signals(a):
    sigs = aggregate.run(scorer=a.scorer)
    print(f"{'PAPEL':<7} {'z':>7} {'n_eff':>7} {'P_alta':>8} {'P_queda':>8} {'base_alta':>10} {'art':>4}")
    for s in sorted(sigs, key=lambda d: -abs(d["z"])):
        pu = f"{s['p_up']:.1%}" if s["p_up"] is not None else "  n/c"
        pd_ = f"{s['p_down']:.1%}" if s["p_down"] is not None else "  n/c"
        # taxa-base sem calibrador e o 1/3 de fabrica, nao medicao: nao imprime
        bu = f"{s['base_up']:.1%}" if s.get("calibrated") and s["base_up"] is not None else "n/c"
        print(f"{s['ticker']:<7} {s['z']:>+7.3f} {s['n_eff']:>7.2f} {pu:>8} {pd_:>8} "
              f"{bu:>10} {s['n_articles']:>4}")
    if sigs and sigs[0]["p_up"] is None:
        print("\n  AVISO: modelo NAO CALIBRADO -- nenhuma probabilidade e exibida.")
        print("  Rode `prices`, `label` e `calibrate` com historico suficiente.")


def cmd_label(a):
    print(f"-> {label.build(horizon_days=a.horizon)} rotulos gravados")
    con = connect()
    print("taxa-base (pool):", {k: (round(v, 4) if isinstance(v, float) else v)
                                for k, v in label.base_rates(con, f"{a.horizon}d").items()})
    con.close()


def cmd_backfill(a):
    db.init()
    r = historico.preparar(dias=a.dias, baixar=not a.sem_baixar,
                           horizonte=a.horizon, scorer=a.scorer)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    if r["pronto_para_calibrar"]:
        print(f"\n{r['rotulos']} rotulos (minimo {historico.MIN_ROTULOS}). "
              "Agora: python3 -m obs.cli calibrate --method platt")
    else:
        print(f"\n{r['rotulos']} rotulos, abaixo do minimo de "
              f"{historico.MIN_ROTULOS}. Aumente --dias ou amplie a watchlist.")


def cmd_backfill_rss(a):
    """Historico pelos feeds que paginam. Nao depende do GDELT.

    MEDIDO: Brazil Journal alcanca 25/nov/2025 em 150 paginas; Suno vai a
    10/jun; Seu Dinheiro a 24/jul. Feed que ignora ?paged para sozinho na
    terceira pagina seca, entao `--paginas` alto nao custa nada nesses."""
    db.init()
    n = ingest.backfill_rss(max_paginas=a.paginas)
    print(f"-> {n} artigos historicos novos")
    if not a.sem_processar:
        from . import score
        print(f"-> {entity.link_all()} mencoes")
        dedupe.cluster_historico(verbose=False)
        if a.scorer in score.PRECISAM_LLM:
            print(historico.AVISO_LLM_HISTORICO)
        print(f"-> {score.run(scorer=a.scorer)} pontuados")
        print("Agora: python3 -m obs.cli backfill --sem-baixar  (reconstroi e rotula)")


def cmd_assimetria(a):
    from . import assimetria
    if a.testar:
        print(json.dumps(assimetria.teste_persistencia(janela_est=a.janela,
                                                       horizonte=a.horizonte),
                         indent=2, ensure_ascii=False))
        return
    print(f"{'PAPEL':<8}{'b_baixa':>9}{'b_alta':>9}{'assimetria':>12}")
    for r in assimetria.painel(janela=a.janela):
        f = lambda v: f"{v:+.3f}" if v is not None else "  n/d"   # noqa: E731
        print(f"{r['ticker']:<8}{f(r['beta_baixa']):>9}{f(r['beta_alta']):>9}"
              f"{f(r['assimetria']):>12}")
    print("\nAssimetria > 0 = acompanha a QUEDA do mercado mais do que a alta.")
    print("NAO prevê queda: e reacao CONDICIONAL a um mercado que ja caiu.")
    print("Persistencia REPROVADA (p=0.065 a 0.107 com cortes independentes);")
    print("use para descrever o papel, nao para ordenar aposta.")


def cmd_fuso(a):
    """Diagnostica o fuso de cada fonte MEDINDO, nao lendo o que ela declara."""
    from . import tempo
    con = connect()
    if a.aplicar:
        n = tempo.aplica_deteccao(con, dias=a.dias, incluir_suspeitas=a.suspeitas)
        print(f"-> {n} dominio(s) com correcao gravada")
    print(f"{'dominio':<28}{'n':>6}{'p10':>10}  veredito")
    for d in tempo.diagnostica_fontes(con, dias=a.dias):
        marca = {"ok": "", "suspeita": "  <- verificar",
                 "fuso errado": "  <- CORRIGIR"}[d["veredito"]]
        print(f"  {d['dominio']:<26}{d['n']:>6}{d['p10_min']:>9.1f}m  "
              f"{d['veredito']}{marca}")
    con.close()
    print("\np10 = 10o percentil do atraso (coleta - publicacao declarada).")
    print("Com polling de 1 min, materia fresca da p10 de minutos. Negativo em")
    print("hora inteira = fuso errado (publicacao no futuro e impossivel).")
    print("Positivo grande e AMBIGUO: pode ser fuso ou catalogo antigo do feed.")


def cmd_limpar(a):
    from . import limpeza
    if a.auditar:
        print(json.dumps(limpeza.auditar(), indent=2, ensure_ascii=False))
        return
    r = limpeza.limpar(aplicar=a.aplicar, dias_log=a.dias_log, scorer=a.scorer)
    modo = "APLICADO" if a.aplicar else "SIMULACAO (nada foi alterado)"
    print(f"== {modo} ==")
    for x in r["acoes"]:
        print(f"  {x['n']:>6}  {x['acao']}")
        if x["detalhe"]:
            print(f"          {x['detalhe']}")
    if not r["acoes"]:
        print("  nada a limpar")
    if not a.aplicar:
        print("\nPara executar de verdade: python3 -m obs.cli limpar --aplicar")
    else:
        print("\nRecalcule os sinais: python3 -m obs.cli signals")


def cmd_calibrate(a):
    print(json.dumps(calibrate.fit(horizon=a.horizon, method=a.method),
                     indent=2, ensure_ascii=False))


def cmd_calibrate_vol(a):
    from .volatility import fit_calibrator
    fit_calibrator(persist=not a.simular)


def cmd_alarms(a):
    sigs = aggregate.run(scorer=a.scorer)
    ev = alarms.evaluate(sigs, scorer=a.scorer)
    if not ev:
        print("nenhum alarme disparado (portas de evidencia/novidade/calibracao)")
    notify.deliver(ev)


def cmd_cycle(a):
    db.init()
    ingest.run(timespan=a.timespan)
    men, pts = _pontuar(a.scorer)
    print(f"-> {men} mencoes, {pts} scores")
    prices.sync(range_=a.range)
    sigs = aggregate.run(scorer=a.scorer)
    label.build(horizon_days=1)
    res = calibrate.fit(horizon="1d")
    print("calibracao:", res.get("reason") or f"ok (n={res['n']}, skill_up={res.get('skill_up')})")
    ev = alarms.evaluate(sigs, scorer=a.scorer)
    notify.deliver(ev)
    cmd_signals(a)


def cmd_surpresa(a):
    n = surpresa.sync(a.indicador, n_meses=a.meses)
    print(f"-> {n} surpresas de {a.indicador} no banco")
    pode, motivo = surpresa.disponivel(a.indicador)
    print(f"entra no sinal? {'SIM' if pode else 'NAO'} — {motivo}")


def cmd_drivers(a):
    if a.purgar:
        print(f"removidos do banco: {drivers.purge_unregistered()}")
    drivers.sync(a.range)


def cmd_report_add(a):
    rid = reports.add_local(a.ticker, a.file, kind=a.kind, period=a.period,
                            report_date=a.data, title=a.title)
    print(f"-> relatório {rid} cadastrado para {a.ticker.upper()}")


def cmd_report_url(a):
    rid = reports.add_url(a.ticker, a.url, kind=a.kind, period=a.period,
                          report_date=a.data, title=a.title)
    print(f"-> URL de relatório {rid} cadastrada para {a.ticker.upper()}")


def cmd_report_extract(a):
    print(json.dumps(reports.extract_text(a.id), ensure_ascii=False, indent=2))


def cmd_report_analyze(a):
    # --externo é deliberadamente explícito; sem ele nenhuma linha sai da máquina.
    print(json.dumps(reports.analyze(a.id, external=a.externo), ensure_ascii=False, indent=2))


def cmd_consensus_import(a):
    print(json.dumps(earnings.import_consensus_csv(a.file), ensure_ascii=False, indent=2))


def cmd_earnings_compute(a):
    print(json.dumps(earnings.compute_surprises(a.ticker), ensure_ascii=False, indent=2))


def cmd_cvm_sync(a):
    """Documentos oficiais pelo IPE da CVM -- a fonte canonica.

    Funciona onde o crawler de RI falha: site dinamico nao expoe PDF no HTML,
    e o IPE traz link direto para todo documento entregue.
    """
    import datetime as dt
    from .config import tickers as _tk

    # Ordem de preferencia para casar no IPE: --termos > cvm_nome do
    # empresas.yml > CNPJ > nome da watchlist. O nome da watchlist e o pior
    # dos quatro: "Petrobras" nao casa com "PETROLEO BRASILEIRO S.A." na CVM.
    import yaml as _yaml
    from .config import CONFIG_DIR as _CD

    meta = _tk().get(a.ticker.upper(), {}) or {}
    emp = {}
    try:
        emp = (_yaml.safe_load((_CD / "empresas.yml").read_text(encoding="utf-8"))
               or {}).get("empresas", {}).get(a.ticker.upper(), {}) or {}
    except Exception:                                            # noqa: BLE001
        pass
    cnpj = a.cnpj or emp.get("cnpj") or ""
    if a.termos:
        termos = a.termos.split("|")
    elif emp.get("cvm_nome"):
        termos = [emp["cvm_nome"]]
    else:
        termos = [meta.get("name", a.ticker)]
    ano = dt.date.today().year
    anos = list(range(ano - a.anos + 1, ano + 1))
    cats = set(a.categorias.split("|")) if a.categorias else None
    r = cvm_ipe.sync(a.ticker, termos, anos=anos, categorias=cats,
                     limite=a.limite, download=a.download, cnpj=cnpj or None)
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_ri_sync(a):
    print(json.dumps(ri.sync(a.ticker, a.download), ensure_ascii=False, indent=2))


def cmd_universe_cvm(a):
    print(json.dumps(universe.fetch_cvm(), ensure_ascii=False, indent=2))


def cmd_universe_import(a):
    print(json.dumps(universe.import_csv(a.file), ensure_ascii=False, indent=2))


def cmd_contabil_sync(a):
    print(json.dumps(contabil.sync_fundamentos(a.ano, a.tipo, a.empresas),
                     ensure_ascii=False, indent=2))


def cmd_horizons(a):
    # Só cria rótulos; não afirma que qualquer horizonte seja rentável.
    for h in (1, 5, 20):
        print(f"-> D+{h}: {label.build(horizon_days=h)} rótulos")
    print("rode `calibrate --horizon 5d` e `calibrate --horizon 20d` separadamente")


def cmd_worker(a):
    db.init()
    print(f"worker: ate {a.paralelo} jobs em paralelo (grupos distintos), "
          f"ciclo de {a.seconds}s")
    ops.worker_loop(a.seconds, paralelo=a.paralelo)


def cmd_status(a):
    con = connect()
    q = lambda s: con.execute(s).fetchone()[0]
    print(f"artigos        : {q('SELECT COUNT(*) FROM articles')}")
    q_men = "SELECT COUNT(*) FROM mentions WHERE ticker != '__none__'"
    print(f"mencoes        : {q(q_men)}")
    print(f"scores         : {q('SELECT COUNT(*) FROM scores')}")
    print(f"sinais         : {q('SELECT COUNT(*) FROM signals')}")
    print(f"rotulos        : {q('SELECT COUNT(*) FROM labels')}")
    print(f"cotacoes       : {q('SELECT COUNT(*) FROM prices')}")
    print(f"alarmes        : {q('SELECT COUNT(*) FROM alarm_events')}")
    try:
        print(f"surpresas      : {q('SELECT COUNT(*) FROM surpresas')}")
        pode, motivo = surpresa.disponivel()
        print(f"  entra no sinal? {'SIM' if pode else 'NAO'} — {motivo}")
    except Exception:                                            # noqa: BLE001
        print("surpresas      : tabela ausente (rode `surpresa`)")
    rows = con.execute("SELECT name,n,fitted_ts,metrics FROM calibrators").fetchall()
    if not rows:
        print("calibradores   : NENHUM -> visor em modo NAO CALIBRADO")
    for r in rows:
        m = json.loads(r["metrics"])
        if r["name"] == "vol:1d":
            print(f"calibrador vol:1d  n={r['n']} em {iso(r['fitted_ts'])} AUC_oos={m.get('auc_oos')} "
                  f"skill_oos={m.get('skill_brier_oos')} -> "
                  f"{'APROVADO' if m.get('calibrado') else 'REPROVADO: ' + str(m.get('motivo'))}")
            continue
        print(f"calibrador {r['name']:<10} n={r['n']} em {iso(r['fitted_ts'])} "
              f"skill_up={m.get('skill_up')} skill_down={m.get('skill_down')}")
    con.close()


def cmd_serve(a):
    from .api import serve
    serve(port=a.port, scorer=a.scorer)


def cmd_demo(a):
    from .demo import seed
    seed(n_days=a.days)


def main(argv=None):
    p = argparse.ArgumentParser(prog="obs", description="Observatorio de noticias de acoes")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        s = sub.add_parser(name, **kw); s.set_defaults(fn=fn); return s

    add("init", cmd_init, help="cria o banco")
    s = add("ingest", cmd_ingest, help="coleta GDELT + RSS")
    s.add_argument("--timespan", default="1d")
    s.add_argument("--so-gdelt", action="store_true",
                   help="pula os feeds; use quando o RSS tiver cadencia propria")
    s = add("ingest-rss", cmd_ingest_rss, help="so os feeds RSS (rapido, ~10s)")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI, help=AJUDA_SCORER)
    s = add("intraday", cmd_intraday, help="barras intradiarias (1m/5m/1h)")
    s.add_argument("--intervalo", default="1m")
    s.add_argument("--range", default="5d")
    add("link", cmd_link, help="liga noticia -> ticker")
    add("cluster", cmd_cluster, help="agrupa quase-duplicatas")
    s = add("score", cmd_score, help="pontua noticias")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI,
                   help=AJUDA_SCORER)
    add("score-estado", cmd_score_estado,
        help="quem le a noticia agora, autorizacao e cobertura")
    s = add("classificar", cmd_classificar,
            help="recomputa tipo de evento e orientacao temporal no acervo "
                 "(passado/presente/futuro); SIMULA sem --aplicar")
    s.add_argument("--aplicar", action="store_true", help="grava as mudancas")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI,
                   help="limita a um leitor; vazio = todos")
    s = add("pontuar", cmd_pontuar,
            help="liga, agrupa e pontua o que ja esta no banco (sem rede de noticia)")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI, help=AJUDA_SCORER)
    s = add("prices", cmd_prices, help="sincroniza cotacoes")
    s.add_argument("--range", default="1mo")
    s.add_argument("--fonte", default="auto", choices=["auto", "brapi", "yahoo"])
    s = add("signals", cmd_signals, help="calcula sinal e probabilidades")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI, help=AJUDA_SCORER)
    s = add("label", cmd_label, help="rotula com retorno anormal futuro")
    s.add_argument("--horizon", type=int, default=1)
    s = add("backfill-rss", cmd_backfill_rss,
            help="historico por paginacao de RSS (nao usa GDELT)")
    s.add_argument("--paginas", type=int, default=150,
                   help="profundidade: ~10 itens por pagina, por feed")
    s.add_argument("--sem-processar", action="store_true",
                   help="so baixa; nao liga mencoes nem pontua")
    s.add_argument("--scorer", default="lexicon", choices=SCORERS_CLI,
                   help="PADRAO lexicon mesmo com o LLM ligado: " + AJUDA_HISTORICO)
    s = add("backfill", cmd_backfill,
            help="reconstroi historico de noticia -> sinais passados -> rotulos "
                 "(destrava a calibracao da direcao sem esperar meses)")
    s.add_argument("--dias", type=int, default=365)
    s.add_argument("--horizon", type=int, default=1)
    s.add_argument("--sem-baixar", action="store_true",
                   help="pula o download e so reprocessa o que ja esta no banco")
    s.add_argument("--scorer", default="lexicon", choices=SCORERS_CLI,
                   help="PADRAO lexicon mesmo com o LLM ligado: " + AJUDA_HISTORICO)
    s = add("assimetria", cmd_assimetria,
            help="beta de baixa x beta de alta: quem cai mais do que sobe")
    s.add_argument("--janela", type=int, default=252)
    s.add_argument("--horizonte", type=int, default=126)
    s.add_argument("--testar", action="store_true",
                   help="roda o teste de persistencia em vez do painel")
    s = add("fuso", cmd_fuso, help="mede o fuso real de cada fonte de noticia")
    s.add_argument("--dias", type=int, default=30)
    s.add_argument("--aplicar", action="store_true", help="grava as correcoes")
    s.add_argument("--suspeitas", action="store_true",
                   help="tambem aplica os casos ambiguos (use com cuidado)")
    s = add("limpar", cmd_limpar,
            help="audita e remove dado calculado sob regra antiga")
    s.add_argument("--aplicar", action="store_true",
                   help="executa de verdade; sem isso so simula")
    s.add_argument("--auditar", action="store_true",
                   help="so o diagnostico, sem propor acao")
    s.add_argument("--dias-log", type=int, default=7)
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI,
                   help="qual leitor repontuar; vazio = o ativo")
    s = add("calibrate", cmd_calibrate, help="ajusta calibrador sinal->prob")
    s.add_argument("--horizon", default="1d")
    s.add_argument("--method", default="platt", choices=["platt", "isotonic"])
    s = add("calibrate-vol", cmd_calibrate_vol,
            help="ajusta a cabeca de agitacao (logit walk-forward) e grava se passar na porta")
    s.add_argument("--simular", action="store_true", help="so mede, nao grava o calibrador")
    s = add("alarms", cmd_alarms, help="avalia e entrega alarmes")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI, help=AJUDA_SCORER)
    s = add("cycle", cmd_cycle, help="pipeline completo (use no cron)")
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI, help=AJUDA_SCORER)
    s.add_argument("--timespan", default="1d")
    s.add_argument("--range", default="1mo")
    s = add("surpresa", cmd_surpresa, help="consenso Focus vs realizado BCB")
    s.add_argument("--indicador", default="IPCA")
    s.add_argument("--meses", type=int, default=132)
    s = add("drivers", cmd_drivers, help="sincroniza cambio, commodities e indices")
    s.add_argument("--range", default="2y")
    s.add_argument("--purgar", action="store_true")
    s = add("report-add", cmd_report_add, help="cadastra PDF local de RI/ITR/DFP")
    s.add_argument("--ticker", required=True); s.add_argument("--file", required=True)
    s.add_argument("--kind", default="RI"); s.add_argument("--period", default="")
    s.add_argument("--data", default=""); s.add_argument("--title", default="")
    s = add("report-url", cmd_report_url, help="cadastra URL de relatório sem baixá-lo")
    s.add_argument("--ticker", required=True); s.add_argument("--url", required=True)
    s.add_argument("--kind", default="CVM"); s.add_argument("--period", default="")
    s.add_argument("--data", default=""); s.add_argument("--title", default="")
    s = add("report-extract", cmd_report_extract, help="extrai texto local de PDF")
    s.add_argument("--id", type=int, required=True)
    s = add("report-analyze", cmd_report_analyze, help="analisa relatório; --externo envia texto ao LLM")
    s.add_argument("--id", type=int, required=True); s.add_argument("--externo", action="store_true")
    s = add("consensus-import", cmd_consensus_import, help="importa CSV de consenso prévio")
    s.add_argument("--file", required=True)
    s = add("earnings-compute", cmd_earnings_compute, help="calcula surpresa realizada vs consenso")
    s.add_argument("--ticker")
    add("universe-cvm", cmd_universe_cvm, help="baixa cadastro de companhias abertas da CVM")
    s = add("universe-import", cmd_universe_import, help="importa CSV ticker,nome,cnpj,... de candidatas")
    s.add_argument("--file", required=True)
    s = add("cvm-sync", cmd_cvm_sync,
            help="documentos oficiais pelo IPE da CVM (fonte canônica; funciona em site dinâmico)")
    s.add_argument("--ticker", required=True)
    s.add_argument("--termos", default="", help="trechos do nome na CVM, separados por |")
    s.add_argument("--cnpj", default="", help="casa por CNPJ em vez de nome")
    s.add_argument("--anos", type=int, default=1)
    s.add_argument("--categorias", default="", help="categorias do IPE separadas por |")
    s.add_argument("--limite", type=int, default=20)
    s.add_argument("--download", action="store_true", default=True)
    s.add_argument("--sem-download", dest="download", action="store_false")
    s = add("ri-sync", cmd_ri_sync, help="descobre e baixa PDFs no domínio oficial de RI validado")
    s.add_argument("--ticker", required=True)
    s.add_argument("--no-download", dest="download", action="store_false")
    s.set_defaults(download=True)
    s = add("contabil-sync", cmd_contabil_sync, help="baixa e estrutura DRE ITR/DFP da CVM")
    s.add_argument("--ano", type=int, required=True); s.add_argument("--tipo", default="ITR")
    s.add_argument("--empresas", default=None, help="config/empresas.yml com CNPJs validados")
    add("horizons", cmd_horizons, help="gera rótulos D+1, D+5 e D+20")
    s = add("worker", cmd_worker, help="executa fila e agenda de operações")
    s.add_argument("--seconds", type=int, default=20)
    s.add_argument("--paralelo", type=int, default=ops.MAX_PARALELO,
                   help="jobs simultaneos de grupos distintos")
    add("status", cmd_status, help="diagnostico do banco")
    s = add("serve", cmd_serve, help="sobe o painel web")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--scorer", default=None, choices=SCORERS_CLI, help=AJUDA_SCORER)
    s = add("demo", cmd_demo, help="popula dados SINTETICOS para validar o encanamento")
    s.add_argument("--days", type=int, default=400)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
