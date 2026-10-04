"""Agrega noticias pontuadas -> sinal por papel -> probabilidades.

Peso de cada noticia (a releitura moderna do seu TCC):
    w = peso_do_veiculo x relevancia x novidade x materialidade x decaimento
        x PESO_DO_DRIVER        (so para noticia que chegou pelo roteamento)

    O peso do driver e o `share` da cadeia de afetacao, e o SINAL do beta
    inverte a direcao quando a exposicao e negativa: alta do petroleo e boa
    para PETR4 (share 0,49, beta +) e ruim para quem consome combustivel.
    Sem isso, noticia de petroleo pesaria igual para os dois.
      - veiculo   : ideia do SimilarWeb, mas com peso aprendivel
      - relevancia: a materia e DE MERCADO ou so cita a empresa?
      - novidade  : 1a reportagem > 20a repercussao (preco reage a surpresa)
      - decaimento: meia-vida configuravel; noticia de 20h atras nao vale como a de agora
"""
from __future__ import annotations
import math

from . import config, score as score_mod
from .calibrate import probabilities
from .volatility import vol_probability
from .db import connect
from .dedupe import cluster_size
from .util import now_ts

HALF_LIFE_H = 8.0        # meia-vida do decaimento de recencia
# Peso de cada indicador macro. Pequeno de proposito, e ainda decai com a
# idade da divulgacao: a primeira versao usava 0,5 fixo por indicador, e com
# quatro indicadores isso somava peso 2,0 contra n_eff de 0,38 das noticias --
# a surpresa virava 96% do sinal. Indicador mensal divulgado ha tres semanas
# nao pode pesar como manchete de uma hora atras.
PESO_SURPRESA = 0.12
MEIA_VIDA_SURPRESA_D = 10.0     # dias
# TETO da fatia que a macro pode ocupar no sinal. Sem ele, num dia sem
# noticia a surpresa macro vira 100% do sinal e o painel passa a mostrar
# convicao sobre um papel do qual ninguem falou -- fabricando sinal onde nao
# ha evidencia. A macro MODULA a noticia; nao a substitui.
TETO_SURPRESA = 0.30
WINDOW_H = 36            # janela de noticias consideradas


def source_weight(domain: str, src_cfg: dict) -> float:
    return float(src_cfg.get("domains", {}).get(domain, src_cfg.get("default_weight", 0.35)))


def escolher_scorer(con=None, scorer: str | None = None, asof: int | None = None,
                    window_h: int = WINDOW_H) -> tuple[str, str]:
    """Quem le a noticia nesta rodada, resolvendo DUAS perguntas distintas.

    1. AUTORIZACAO: o leitor pedido esta disponivel? (obs/score.py:resolver)
    2. COBERTURA: ele tem nota gravada na janela? Trocar o leitor padrao de
       `lexicon` para `llm` em banco com 50 mil scores do lexico esvaziaria o
       painel inteiro -- `aggregate` filtra por `sc.scorer=?` e nao acharia
       linha nenhuma. O painel vazio se le como "nao houve noticia", que e o
       erro de leitura mais caro deste projeto (docs/como-usar.md, secao 6).

    Entao: se o leitor pedido nao tem nota na janela e o lexico tem, usa o
    lexico e DIZ que usou (o motivo volta junto, vai para /api/status e para a
    coluna signals.scorer). A escolha e UMA por rodada, nunca por papel:
    `z` e `dispersion` sao comparados entre papeis, e misturar leitores na
    mesma tela tornaria a comparacao sem sentido.
    """
    efetivo, motivo = score_mod.resolver(scorer, verbose=False)
    proprio = con is None
    con = con or connect()
    try:
        asof = asof or now_ts()
        desde = asof - window_h * 3600
        q = ("SELECT COUNT(*) FROM scores sc JOIN articles a ON a.id=sc.article_id"
             " WHERE sc.scorer=? AND a.published_ts <= ? AND a.published_ts > ?")
        n = con.execute(q, (efetivo, asof, desde)).fetchone()[0]
        if n == 0 and efetivo != "lexicon":
            n_lex = con.execute(q, ("lexicon", asof, desde)).fetchone()[0]
            if n_lex > 0:
                return "lexicon", (f"'{efetivo}' sem nota na janela de "
                                   f"{window_h}h; {n_lex} do lexico")
    except Exception:                                        # noqa: BLE001
        pass
    finally:
        if proprio:
            con.close()
    return efetivo, motivo


def compute(ticker: str, scorer: str | None = None, asof: int | None = None,
            window_h: int = WINDOW_H, ab: dict | None = None,
            drv_vol: dict | None = None, vol_cal: dict | None = None) -> dict:
    asof = asof or now_ts()
    scorer = scorer or score_mod.resolver(verbose=False)[0]
    src_cfg = config.sources()
    con = connect()

    rows = con.execute("""
        SELECT sc.s, sc.magnitude, sc.novelty, sc.event_type, sc.article_id,
               m.relevance, m.driver, m.peso_driver, m.sinal_driver,
               a.domain, a.title, a.published_ts, a.url
        FROM scores sc
        JOIN mentions m ON m.article_id=sc.article_id AND m.ticker=sc.ticker
        JOIN articles a ON a.id=sc.article_id
        WHERE sc.ticker=? AND sc.scorer=?
          AND a.published_ts <= ? AND a.published_ts > ?
        ORDER BY a.published_ts DESC""",
        (ticker, scorer, asof, asof - window_h * 3600)).fetchall()

    num = den = 0.0
    items = []
    for r in rows:
        age_h = max(0.0, (asof - r["published_ts"]) / 3600.0)
        decay = 0.5 ** (age_h / HALF_LIFE_H)
        w = (source_weight(r["domain"], src_cfg) * r["relevance"]
             * r["novelty"] * r["magnitude"] * decay)
        # Roteamento: pondera pelo share e inverte pelo sinal do beta
        s_eff = r["s"]
        if r["driver"]:
            w *= max(0.0, float(r["peso_driver"] or 0.0))
            if (r["sinal_driver"] or 1) < 0:
                s_eff = -s_eff
        if w <= 1e-6:
            continue
        num += s_eff * w
        den += w
        items.append({"title": r["title"], "url": r["url"], "domain": r["domain"],
                      "s": round(s_eff, 4), "s_bruto": r["s"], "driver": r["driver"],
                      "peso_driver": r["peso_driver"],
                      "w": round(w, 4), "event_type": r["event_type"],
                      "novelty": round(r["novelty"], 3), "age_h": round(age_h, 1),
                      "cluster_size": cluster_size(con, r["article_id"])})

    # SURPRESA MACRO entra no sinal quando a porta esta aberta.
    # A porta e config, nao padrao escondido: obs/surpresa.py:ATIVO.
    # MEDICAO POR TRAS: os quatro indicadores reprovaram no teste de
    # permutacao (p entre 0,45 e 0,79). Ligar e decisao do usuario, e o
    # painel mostra esse p ao lado do numero.
    surp_contrib, surp_peso = 0.0, 0.0
    try:
        from . import surpresa as _sup
        pode, _motivo = _sup.disponivel()
        if pode:
            import datetime as _dt
            from . import tempo as _tp
            hoje = _dt.date.fromisoformat(_tp.data_sp(asof))
            for sens in _sup.sensibilidade(ticker):
                imp = sens.get("implicado_pp")
                ult = sens.get("ultima") or {}
                if imp is None or not ult.get("referencia"):
                    continue
                try:
                    dv = _dt.date.fromisoformat(
                        _sup.data_divulgacao(sens["indicador"], ult["referencia"]))
                    idade = max(0.0, (hoje - dv).days)
                except Exception:                                # noqa: BLE001
                    idade = 30.0
                decai = 0.5 ** (idade / MEIA_VIDA_SURPRESA_D)
                peso = PESO_SURPRESA * decai
                surp_contrib += max(-1.0, min(1.0, imp)) * peso
                surp_peso += peso
    except Exception:                                            # noqa: BLE001
        pass
    # Aplica o teto: a macro nunca passa de TETO_SURPRESA do peso total.
    # A guarda NAO pode exigir den > 0 -- papel sem noticia e justamente onde
    # o teto mais importa: com den = 0 o teto vira 0 e a macro e zerada, que
    # e o comportamento certo. Ninguem falou do papel, logo nao ha sinal.
    if surp_peso > 0:
        teto = den * TETO_SURPRESA / (1.0 - TETO_SURPRESA)
        if surp_peso > teto:
            fator = teto / surp_peso
            surp_contrib *= fator
            surp_peso = teto
    num += surp_contrib
    den += surp_peso

    z = (num / den) if den > 0 else 0.0
    if den > 0:
        mean = z
        var = sum(((it["s"] - mean) ** 2) * it["w"] for it in items) / den
        dispersion = math.sqrt(var)
    else:
        dispersion = 0.0

    probs = probabilities(con, z, den, horizon="1d", ticker=ticker)
    # Terceira cabeca. Le as MESMAS features (volume e discordancia de noticia)
    # mais a vol realizada do papel; nao altera em nada o calculo da direcao.
    vol = vol_probability(con, ticker, asof, n_eff=den, dispersion=dispersion, ab=ab,
                          drv_vol=drv_vol, cal=vol_cal)
    con.close()

    items.sort(key=lambda d: -d["w"])
    return {"ticker": ticker, "asof_ts": asof, "z": round(z, 4), "scorer": scorer,
            "n_eff": round(den, 4), "dispersion": round(dispersion, 4),
            "n_articles": len(items), "items": items[:12],
            "n_roteadas": sum(1 for i in items if i.get("driver")),
            "surpresa_contrib": round(surp_contrib, 4),
            "surpresa_peso": round(surp_peso, 4), **probs, **vol}


def run(scorer: str | None = None, asof: int | None = None,
        verbose: bool = True) -> list[dict]:
    asof = asof or now_ts()
    out = []
    con = connect()
    scorer, motivo_scorer = escolher_scorer(con, scorer, asof)
    if verbose and motivo_scorer != "escolhido":
        print(f"  [sinal] lendo com '{scorer}': {motivo_scorer}")
    # retornos anormais calculados UMA vez por rodada (ver vol_probability)
    try:
        from .label import abnormal_returns
        ab = abnormal_returns(con)
    except Exception:                                    # noqa: BLE001
        ab = None
    from .volatility import faixas, load_calibrator, panel_vol
    drv_vol = panel_vol(con)
    vol_cal = load_calibrator(con)
    with con:
        for tkr in config.tickers():
            sig = compute(tkr, scorer=scorer, asof=asof, ab=ab, drv_vol=drv_vol, vol_cal=vol_cal)
            con.execute("""
                INSERT OR REPLACE INTO signals
                (ticker,asof_ts,z,n_eff,dispersion,p_up,p_flat,p_down,
                 base_up,base_flat,base_down,calibrated,n_articles,
                 p_vol,vol_base,vol_calib,scorer)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sig["ticker"], sig["asof_ts"], sig["z"], sig["n_eff"], sig["dispersion"],
                 sig["p_up"], sig["p_flat"], sig["p_down"], sig["base_up"],
                 sig["base_flat"], sig["base_down"], sig["calibrated"], sig["n_articles"],
                 sig.get("p_vol"), sig.get("vol_base"), sig.get("vol_calib", 0), scorer))
            out.append(sig)
    con.close()
    faixas(out)          # agitacao sem calibrador -> faixa ordinal, nunca %
    return out
