"""Reconstrucao de historico: backfill de noticia -> sinais passados -> rotulos.

POR QUE ISSO EXISTE
A direcao so calibra com sinal do PASSADO casado com o retorno que veio
DEPOIS. Rodando so o ciclo ao vivo, juntar os ~120 eventos minimos levaria
meses. O GDELT aceita janela fechada (startdatetime/enddatetime, cobertura de
2017 em diante), entao da para reconstruir esse historico hoje.

AS DUAS DEFESAS CONTRA VAZAMENTO DE FUTURO
Reconstruir sinal passado e exatamente onde se vaza futuro. Aqui:
  1. o asof de cada dia e o FECHAMENTO daquele dia, e aggregate.compute()
     filtra `published_ts <= asof` -- nenhuma noticia posterior entra no sinal;
  2. o rotulo sai de label.build(), que exige pregao ESTRITAMENTE POSTERIOR
     ao asof.

O VIES QUE *NAO* DA PARA DESFAZER -- leia antes de confiar no numero
O GDELT indexa pelo `seendate`: quando ELE viu a materia, nao quando o veiculo
publicou. Em geral seendate >= publicacao, logo o vies e conservador (a
noticia parece mais tarde do que foi). Mas duas coisas o backfill nao
reproduz: a cobertura retroativa do indice nao e a mesma que estava visivel em
tempo real, e o `novelty` e calculado agora, sobre um corpus que naquele dia
nao existia. Portanto: a calibracao que sai daqui e ESTIMATIVA, nao medicao
limpa. O ciclo ao vivo vai acumulando rotulos de verdade e deve substitui-la.
Por isso o resumo marca cada rotulo com a origem.
"""
from __future__ import annotations
import datetime as dt

from . import aggregate, config, dedupe, entity, ingest, label, tempo
from .db import connect

# Fechamento da B3 e 17h BRT; 21h UTC deixa margem para o leilao.
HORA_ASOF_UTC = 21
PASSO_DIAS = 7          # janela por requisicao; ver truncamento em fetch_gdelt_janela
MIN_ROTULOS = 120       # minimo para a porta da calibracao abrir


def janelas(dias: int, passo: int = PASSO_DIAS) -> list[tuple[dt.datetime, dt.datetime]]:
    fim = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    out = []
    for i in range(0, dias, passo):
        b = fim - dt.timedelta(days=i)
        a = fim - dt.timedelta(days=min(i + passo, dias))
        out.append((a, b))
    return out


# Teto do backfill: generoso, porque a espera do GDELT e legitima (1 req/5,5s)
# e 53 janelas x 10 papeis sao ~50 min so de pausa obrigatoria.
TETO_BACKFILL_S = 5400.0


def backfill(dias: int = 365, passo: int = PASSO_DIAS, verbose: bool = True,
             teto_s: float = TETO_BACKFILL_S) -> int:
    """Baixa noticia historica em janelas curtas. Demorado por desenho: o GDELT
    pede 1 requisicao a cada 5s, e sao len(tickers) requisicoes por janela.

    COM DISJUNTOR, e o motivo e experiencia direta: com o GDELT em throttle
    este backfill rodou 53 janelas e trouxe ZERO artigo, gastando a espera
    inteira para nada. Agora, depois de 3 consultas seguidas sem resposta, ele
    para e diz que o throttle esta ativo -- throttle do GDELT nao passa em
    segundos, entao insistir e so queimar tempo.
    """
    js = janelas(dias, passo)
    n_tk = len(config.tickers())
    orc = ingest.Orcamento(teto_s)
    if verbose:
        seg = len(js) * n_tk * ingest.GDELT_DELAY_S
        print(f"{len(js)} janelas x {n_tk} papeis = ~{seg / 60:.0f} min de espera "
              f"imposta pelo GDELT (1 req / {ingest.GDELT_DELAY_S}s)")
    total = 0
    for k, (a, b) in enumerate(js, 1):
        if not orc.ok():
            if verbose:
                print(f"  parando na janela {k}/{len(js)}: {orc.motivo()}. "
                      f"{total} artigos salvos. Rode de novo mais tarde -- "
                      f"repetir nao duplica (INSERT OR IGNORE por url).")
            break
        rows = ingest.fetch_gdelt_janela(a, b, orc=orc)
        novos = ingest.store(rows)
        total += novos
        if verbose:
            print(f"  [{k}/{len(js)}] {a.date()}..{b.date()}: "
                  f"{len(rows)} coletados, {novos} novos", flush=True)
    return total


def _dias_com_noticia(con, dias: int) -> list[str]:
    """Dias de PREGAO que tem ao menos uma noticia pontuada ate o fechamento.

    Reconstruir dia sem noticia nao acrescenta informacao -- gera sinal z=0 que
    so dilui a amostra e empurra a taxa-base para o meio."""
    corte = int((dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=dias)).timestamp())
    pregoes = {r[0] for r in con.execute(
        "SELECT DISTINCT date FROM prices WHERE date >= date(?, 'unixepoch')",
        (corte,)).fetchall()}
    # DATA DE PREGAO, nao data UTC. `date(ts,'unixepoch')` devolve o dia em
    # UTC: noticia das 23h UTC (20h BRT) cairia no dia seguinte do calendario
    # UTC, embora pertenca ao pregao de hoje em Sao Paulo. A conversao vai no
    # Python porque o SQLite nao conhece fuso nomeado.
    com_news = {tempo.data_sp(r[0]) for r in con.execute(
        "SELECT DISTINCT a.published_ts FROM articles a "
        "JOIN scores sc ON sc.article_id = a.id WHERE a.published_ts >= ?",
        (corte,)).fetchall()}
    return sorted(pregoes & com_news)


# O historico e o unico lugar do projeto onde o lexico segue sendo o PADRAO,
# e nao por economia. Um modelo com cutoff ja sabe o que aconteceu com o papel
# depois da manchete de 2019: lendo 10 anos de titulo ele pode estar lembrando
# do desfecho em vez de lendo o texto, e e justamente desse corpus que saem os
# rotulos que destravam a calibracao. Acuracia alta obtida assim nao prova
# previsao -- prova vazamento.
AVISO_LLM_HISTORICO = (
    "  [backfill] AVISO: pontuando HISTORICO com LLM. Um modelo com cutoff ja\n"
    "  conhece o desfecho das materias antigas, entao o resultado NAO vale\n"
    "  como evidencia de previsao -- so como amostra de auditoria de leitura.\n"
    "  A validacao do canal de texto exige janela POSTERIOR ao cutoff\n"
    "  (docs/validacao.md, docs/canal-noticias.md).")


def reconstruir(dias: int = 365, scorer: str | None = None,
                verbose: bool = True) -> int:
    """Grava um sinal por (papel, dia de pregao com noticia), com asof no
    fechamento daquele dia. Nao recalibra nada; so produz o insumo do rotulo."""
    con = connect()
    # UM leitor para a serie inteira. Reconstruir metade da historia com um
    # leitor e metade com outro produziria um `z` cuja escala muda no meio da
    # amostra -- e o calibrador trataria a mudanca de leitor como sinal.
    scorer, motivo = aggregate.escolher_scorer(con, scorer)
    if verbose and motivo != "escolhido":
        print(f"  [backfill] lendo com '{scorer}': {motivo}")
    try:
        from .label import abnormal_returns
        ab = abnormal_returns(con)
    except Exception:                                        # noqa: BLE001
        ab = None
    from .volatility import load_calibrator, panel_vol
    drv_vol = panel_vol(con)
    vol_cal = load_calibrator(con)

    dias_lista = _dias_com_noticia(con, dias)
    if verbose:
        print(f"{len(dias_lista)} dias de pregao com noticia pontuada")
    n = 0
    tickers = list(config.tickers())
    with con:
        for d in dias_lista:
            # Fechamento REAL daquela data em Sao Paulo. O `21h UTC` fixo que
            # havia aqui erra por uma hora em datas anteriores a 2019, quando o
            # Brasil tinha horario de verao e o offset era -02.
            asof = tempo.fechamento_utc(d)
            for tkr in tickers:
                sig = aggregate.compute(tkr, scorer=scorer, asof=asof, ab=ab,
                                        drv_vol=drv_vol, vol_cal=vol_cal)
                # Papel sem nenhuma noticia naquela janela nao vira sinal.
                if sig["n_articles"] == 0:
                    continue
                con.execute("""
                    INSERT OR REPLACE INTO signals
                    (ticker,asof_ts,z,n_eff,dispersion,p_up,p_flat,p_down,
                     base_up,base_flat,base_down,calibrated,n_articles,
                     p_vol,vol_base,vol_calib)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sig["ticker"], sig["asof_ts"], sig["z"], sig["n_eff"],
                     sig["dispersion"], sig["p_up"], sig["p_flat"], sig["p_down"],
                     sig["base_up"], sig["base_flat"], sig["base_down"],
                     sig["calibrated"], sig["n_articles"], sig.get("p_vol"),
                     sig.get("vol_base"), sig.get("vol_calib", 0)))
                n += 1
    con.close()
    return n


def preparar(dias: int = 365, baixar: bool = True, horizonte: int = 1,
             verbose: bool = True, scorer: str = "lexicon") -> dict:
    """Cadeia inteira: backfill -> mencoes -> cluster -> score -> sinais -> rotulos.

    Nao chama `calibrate`: a decisao de abrir a porta fica com o usuario, que
    deve ver antes quantos rotulos sairam e de que origem."""
    out: dict = {"dias": dias}
    if baixar:
        if verbose:
            print("== 1. Backfill de noticia (GDELT, janela historica) ==")
        out["artigos_novos"] = backfill(dias, verbose=verbose)
    if verbose:
        print("== 2. Mencoes, agrupamento e pontuacao ==")
    out["mencoes"] = entity.link_all()
    # HISTORICO, nao a janela de 48h: sem isso todo artigo do backfill ficaria
    # sem cluster_id e novelty() devolveria 1.0 para todos -- a 20a repeticao
    # entraria com o mesmo peso da primeira reportagem.
    out["clusters"] = dedupe.cluster_historico(verbose=verbose)
    from . import score
    if scorer in score.PRECISAM_LLM and verbose:
        print(AVISO_LLM_HISTORICO)
    out["pontuados"] = score.run(scorer=scorer)
    out["scorer"] = scorer
    if verbose:
        print(f"  mencoes={out['mencoes']} pontuados={out['pontuados']}")
        print("== 3. Reconstrucao dos sinais passados ==")
    out["sinais"] = reconstruir(dias, scorer=scorer, verbose=verbose)
    if verbose:
        print("== 4. Rotulagem ==")
    out["rotulos"] = label.build(horizon_days=horizonte)
    con = connect()
    out["taxa_base"] = label.base_rates(con, f"{horizonte}d")
    con.close()
    out["pronto_para_calibrar"] = out["rotulos"] >= MIN_ROTULOS
    out["aviso"] = (
        "Rotulos vindos de backfill sao ESTIMATIVA: o GDELT indexa pelo seendate "
        "e a cobertura retroativa nao e a que estava visivel em tempo real. "
        "Use para destravar a primeira calibracao e deixe o ciclo ao vivo "
        "substituir com rotulo limpo. Ver obs/historico.py.")
    return out
