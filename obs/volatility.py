"""Cabeca de VOLATILIDADE -- a terceira saida, ao lado de alta e queda.

POR QUE ELA EXISTE
    Direcao de acao em D+1 tem teto de ~53% de acerto; e a forma do problema,
    nao falta de engenharia. Volatilidade e outra coisa: ela e PERSISTENTE --
    dia agitado tende a ser seguido de dia agitado. Isso torna 70-80% de
    acerto alcancavel no mesmo pipeline, com os mesmos dados.

O QUE NAO MUDA
    Nenhuma peca do sistema sai. Ingestao, relevancia, cluster, novidade,
    score e agregacao continuam iguais; a volatilidade e mais uma cabeca
    lendo as MESMAS features, nao um sistema paralelo.

ALVO
    dia agitado = |retorno anormal| acima da mediana historica DAQUELE papel
    (mediana por papel, nao global: 1% na WEGE3 e na MGLU3 nao sao o mesmo
    evento -- mesma razao pela qual a direcao usa multiplos de sigma).

FEATURES QUE O CALIBRADOR APROVADO USA DE FATO -- cinco, todas ex-ante:
    |retorno anormal| de hoje
    vol realizada do papel em 5 e em 20 pregoes
    vol realizada dos drivers (o painel macro agitado antecede papel agitado)
    calendario conhecido: Payroll EUA no dia-alvo

NENHUMA FEATURE DE NOTICIA ENTRA AQUI. Este cabecalho afirmava que n_eff e a
discordancia entre fontes eram features; nao sao. `build_features` tem o ramo
que as aceita, mas NENHUM chamador passa `noticia=` -- nem o treino
(fit_calibrator), nem a predicao (vol_probability), nem os scripts de teste.
O ramo e codigo morto a espera de medicao.

A consequencia importa para a leitura do resultado: o AUC 0.590 fora da
amostra e de um modelo de PRECO E CALENDARIO. Ele nao e evidencia de que
noticia preveja agitacao -- essa hipotese, que e a da psicologia do TCC
(atencao + propagacao + emocao elevam a chance de movimento grande),
permanece NAO TESTADA. Ver docs/psicologia.md.
"""
from __future__ import annotations
import math
import statistics as st
import datetime as dt

import numpy as np

RIDGE = 1e-3
MAX_IT = 80


def logit_fit(X: np.ndarray, y: np.ndarray, lam: float = RIDGE):
    """Regressao logistica multivariada por IRLS/Newton, em espaco padronizado.

    Multivariada e nao uma Platt por feature: vol de 1, 5 e 20 dias sao
    fortemente correlacionadas, e betas univariados somados contariam a mesma
    informacao tres vezes -- o mesmo erro que a cadeia de afetacao evita.
    """
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Xs = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    b = np.zeros(Xs.shape[1])
    b[0] = math.log(max(1e-6, y.mean()) / max(1e-6, 1 - y.mean()))
    for _ in range(MAX_IT):
        z = np.clip(Xs @ b, -35, 35)
        p = 1 / (1 + np.exp(-z))
        w = np.clip(p * (1 - p), 1e-9, None)
        g = Xs.T @ (p - y) + lam * b
        H = Xs.T @ (Xs * w[:, None]) + lam * np.eye(Xs.shape[1])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        b -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return {"b": b, "mu": mu, "sd": sd}


def logit_predict(m: dict, X: np.ndarray) -> np.ndarray:
    Xs = np.hstack([np.ones((len(X), 1)), (X - m["mu"]) / m["sd"]])
    return 1 / (1 + np.exp(-np.clip(Xs @ m["b"], -35, 35)))


def realized_vol(vals: list[float]) -> float:
    return st.pstdev(vals) if len(vals) > 1 else 0.0


def build_features(abn: dict[str, float], dates: list[str], i: int,
                   drv_vol: dict[str, float],
                   noticia: dict | None = None,
                   target_date: str | None = None) -> list[float] | None:
    """Features conhecidas no FECHAMENTO de `dates[i]`, para prever `dates[i+1]`.

    A janela e INCLUSIVA em i. A primeira versao usava `dates[i-20:i]`, que
    exclui o proprio dia i -- ou seja, previa T+1 com dados ate T-1, jogando
    fora o pregao mais informativo de todos. Com volatilidade isso e fatal:
    o |retorno| de ontem e, de longe, o melhor preditor do de hoje, e sem ele
    o AUC fica em 0.51 e parece que volatilidade nao e previsivel.
    """
    if i < 21:
        return None
    hist = [abn[d] for d in dates[max(0, i - 19):i + 1] if d in abn]
    if len(hist) < 15:
        return None
    base = [
        abs(abn.get(dates[i], 0.0)),         # |retorno| de HOJE (fecha antes do alvo)
        realized_vol(hist[-5:]),             # vol 5 pregoes
        realized_vol(hist),                  # vol 20 pregoes
        drv_vol.get(dates[i], 0.0),          # vol do painel macro hoje
    ]
    # Dado EX-ANTE: o calendario diz se ha Payroll no DIA-ALVO. Nao usa DXY,
    # valor realizado ou proxy contemporanea. A feature so ganha peso se o
    # walk-forward do calibrador aprovar a nova especificacao.
    if target_date:
        from .externo import risco_calendario
        base.append(risco_calendario(target_date))
    else:
        base.append(0.0)
    if noticia is None:
        return base
    # Features de NOTICIA e de ATENCAO. E aqui -- nao na direcao -- que a
    # psicologia do TCC tem chance: atencao, propagacao e emocao mudam a
    # INTENSIDADE da reacao sem dizer o lado. Ver obs/atencao.py.
    #
    # As tres de atencao respondem a objecao de que novidade sozinha joga fora
    # informacao: a 20a copia e informacao velha (novidade ~0.22) mas e prova
    # de que 20 redacoes acharam o assunto publicavel. Novidade continua na
    # DIRECAO; espalhamento entra aqui, na MAGNITUDE.
    #
    # NAO MEDIDO AINDA: exige historico de noticia casado com retorno, que e o
    # que `obs backfill` produz. Enquanto nao medir, nenhum chamador passa
    # `noticia=` e o calibrador segue com as 5 de preco e calendario.
    return base + [
        min(noticia.get("n_eff", 0.0), 8.0),              # volume efetivo
        noticia.get("dispersion", 0.0),                   # discordancia
        abs(noticia.get("desacordo", 0.0)),               # lexico vs LLM
        min(noticia.get("fontes_efetivas", 0.0), 12.0),   # espalhamento real
        min(noticia.get("velocidade_cascata", 0.0), 8.0),  # nas 1as 2 horas
        noticia.get("razao_repeticao", 0.0),              # quanto e so copia
        noticia.get("medo", 0.0),                         # excitacao, nao tom
        min(noticia.get("surto", 0.0), 10.0),             # vs baseline do papel
    ]


FEATURES_NOTICIA = ["n_eff", "dispersao", "desacordo", "fontes_efetivas",
                    "velocidade_cascata", "razao_repeticao", "medo", "surto"]


# ---------------------------------------------------------------- servico ---
VOL_QUANTIL = 0.80       # "dia agitado" = top 20%; medido AUC 0.683
MIN_HIST = 40

# Calibrador da cabeca de agitacao (logit_fit walk-forward). So vira
# probabilidade exibida se passar na porta abaixo, medida FORA da amostra.
CAL_NAME = "vol:1d"
CAL_DOBRAS = 6
CAL_MIN_OOS = 500        # pares (papel, dia) fora da amostra, no minimo
# Porta pratica, nao so estatistica: com centenas de milhares de pares ate
# AUC 0,51 vira "significativo". Exigimos ganho que valha exibir um numero.
CAL_MIN_AUC = 0.55       # e o limite inferior do IC 95% acima de 0,5
CAL_MIN_SKILL = 0.01     # skill de Brier >= 1% sobre a taxa-base do treino
FEATURE_VERSION = 2
FEATURES = ["|ret| hoje", "vol 5 pregoes", "vol 20 pregoes", "vol do painel macro",
            "Payroll EUA no dia-alvo (calendário aproximado)"]


def panel_vol(con) -> dict[str, float]:
    """Vol do painel macro no dia = media dos |retornos| dos drivers.

    Mesma definicao de scripts/vol_test.py e vol_test2.py, onde o AUC foi
    medido -- trocar a feature aqui invalidaria a medicao."""
    from . import drivers
    try:
        dret = drivers.driver_returns(con)
    except Exception:                                    # noqa: BLE001 (tabela ausente)
        return {}
    by: dict[str, list[float]] = {}
    for ser in dret.values():
        for d, r in ser.items():
            by.setdefault(d, []).append(abs(r))
    return {d: st.fmean(v) for d, v in by.items()}


def _limiar(mags_ordenados: list[float]) -> float:
    return mags_ordenados[int(VOL_QUANTIL * (len(mags_ordenados) - 1))]


def _dataset(ab: dict[str, dict[str, float]], drv_vol: dict[str, float]):
    """Pares (features no fechamento de T, rotulo de T+1) para todos os papeis.

    O limiar do top 20% e EXPANSIVO: em cada T usa so |retornos| ate T.
    Com painel macro disponivel, so entram dias que o tenham -- senao a 4a
    feature valeria 0 em anos inteiros e o ajuste aprenderia isso."""
    import bisect
    X, y, datas = [], [], []
    for tkr, serie in ab.items():
        dates = sorted(serie)
        vistos: list[float] = []
        for i in range(len(dates) - 1):
            bisect.insort(vistos, abs(serie[dates[i]]))
            if len(vistos) < MIN_HIST:
                continue
            if drv_vol and dates[i] not in drv_vol:
                continue
            f = build_features(serie, dates, i, drv_vol, target_date=dates[i + 1])
            if f is None:
                continue
            X.append(f)
            y.append(1.0 if abs(serie[dates[i + 1]]) > _limiar(vistos) else 0.0)
            datas.append(dates[i + 1])
    return np.array(X, dtype=float), np.array(y, dtype=float), datas


def _auc(p: np.ndarray, y: np.ndarray) -> float:
    """AUC por postos (Mann-Whitney), O(n log n)."""
    pos = int((y > 0.5).sum()); neg = len(y) - pos
    if not pos or not neg:
        return float("nan")
    ordem = p.argsort(kind="mergesort")
    postos = np.empty(len(p)); postos[ordem] = np.arange(1, len(p) + 1)
    # empates recebem posto medio
    _, inv, cont = np.unique(p, return_inverse=True, return_counts=True)
    soma = np.bincount(inv, weights=postos); postos = (soma / cont)[inv]
    return float((postos[y > 0.5].sum() - pos * (pos + 1) / 2) / (pos * neg))


def fit_calibrator(persist: bool = True, verbose: bool = True) -> dict:
    """Ajusta o logit_fit da agitacao com o historico do banco, walk-forward.

    Mede FORA da amostra (AUC, skill de Brier contra a taxa-base do treino,
    confiabilidade por decil) e grava o calibrador com essas metricas. A
    probabilidade so e exibida se `calibrado` for verdadeiro."""
    from .db import connect
    from .label import abnormal_returns
    from .util import now_ts
    import json

    con = connect()
    ab = abnormal_returns(con)
    drv_vol = panel_vol(con)
    X, y, datas = _dataset(ab, drv_vol)
    out: dict = {"n": int(len(y)), "calibrado": False, "alvo": "top 20% de |retorno anormal| em D+1",
                 "features": FEATURES, "feature_version": FEATURE_VERSION,
                 "painel_macro": bool(drv_vol)}
    if len(y) < 2 * CAL_MIN_OOS:
        out["motivo"] = f"amostra insuficiente: {len(y)} pares (papel, dia)"
        con.close()
        return out

    ordem = np.argsort(np.array(datas), kind="mergesort")
    X, y = X[ordem], y[ordem]
    datas = [datas[j] for j in ordem]
    unicas = sorted(set(datas))
    cortes = [unicas[int(len(unicas) * k / CAL_DOBRAS)] for k in range(1, CAL_DOBRAS)]
    P, A, B = [], [], []
    import bisect
    lim_idx = [bisect.bisect_left(datas, c) for c in cortes] + [len(datas)]
    for k in range(len(cortes)):
        tr, te = slice(0, lim_idx[k]), slice(lim_idx[k], lim_idx[k + 1])
        if y[tr].sum() < 10 or len(y[te]) == 0:
            continue
        m = logit_fit(X[tr], y[tr])
        P.append(logit_predict(m, X[te])); A.append(y[te])
        B.append(np.full(len(y[te]), y[tr].mean()))
    P, A, B = np.concatenate(P), np.concatenate(A), np.concatenate(B)

    brier = float(((P - A) ** 2).mean())
    brier_base = float(((B - A) ** 2).mean())
    skill = 1 - brier / brier_base if brier_base > 0 else 0.0
    dec = np.quantile(P, np.linspace(0, 1, 11))
    gaps = []
    for a, b in zip(dec[:-1], dec[1:]):
        sel = (P >= a) & (P <= b)
        if sel.sum() >= 20:
            gaps.append(abs(float(P[sel].mean() - A[sel].mean())))
    auc = _auc(P, A)
    # IC 95% do AUC (Hanley & McNeil)
    n1, n0 = float((A > 0.5).sum()), float((A < 0.5).sum())
    q1, q2 = auc / (2 - auc), 2 * auc ** 2 / (1 + auc)
    se = ((auc * (1 - auc) + (n1 - 1) * (q1 - auc ** 2) + (n0 - 1) * (q2 - auc ** 2)) / (n1 * n0)) ** 0.5
    out.update({
        "n_oos": int(len(A)), "taxa_base_oos": round(float(A.mean()), 4),
        "auc_oos": round(auc, 4), "auc_ic95": [round(auc - 1.96 * se, 4), round(auc + 1.96 * se, 4)], "brier_oos": round(brier, 5),
        "brier_base_oos": round(brier_base, 5), "skill_brier_oos": round(skill, 4),
        "confiabilidade_max_gap": round(max(gaps), 4) if gaps else None,
        "periodo": [datas[lim_idx[0]], datas[-1]],
    })
    # A PORTA: so vira probabilidade exibida se bater a taxa-base fora da amostra
    out["porta"] = {"min_oos": CAL_MIN_OOS, "min_auc": CAL_MIN_AUC, "min_skill": CAL_MIN_SKILL}
    falhas = []
    if out["n_oos"] < CAL_MIN_OOS:
        falhas.append(f"so {out['n_oos']} pares fora da amostra (minimo {CAL_MIN_OOS})")
    if auc < CAL_MIN_AUC or out["auc_ic95"][0] <= 0.5:
        falhas.append(f"AUC {auc:.3f} (IC95 {out['auc_ic95'][0]:.3f}-{out['auc_ic95'][1]:.3f}); minimo {CAL_MIN_AUC}")
    if skill < CAL_MIN_SKILL:
        falhas.append(f"skill de Brier {skill:+.4f}; minimo {CAL_MIN_SKILL:+.2f}")
    out["calibrado"] = not falhas
    if falhas:
        out["motivo"] = "; ".join(falhas)

    final = logit_fit(X, y)
    payload = {"b": final["b"].tolist(), "mu": final["mu"].tolist(), "sd": final["sd"].tolist(),
               "quantil": VOL_QUANTIL, "feature_version": FEATURE_VERSION}
    if persist:
        with con:
            con.execute("INSERT OR REPLACE INTO calibrators(name,payload,n,fitted_ts,metrics)"
                        " VALUES (?,?,?,?,?)",
                        (CAL_NAME, json.dumps(payload), int(len(y)), now_ts(), json.dumps(out)))
    con.close()
    if verbose:
        print(f"agitacao: n={out['n']}  fora da amostra n={out['n_oos']}  "
              f"AUC={out['auc_oos']:.3f}  skill Brier={out['skill_brier_oos']:+.4f}  "
              f"-> {'CALIBRADO' if out['calibrado'] else 'NAO calibrado: ' + out.get('motivo', '')}")
    return out


def load_calibrator(con) -> dict | None:
    import json
    try:
        row = con.execute("SELECT payload, metrics FROM calibrators WHERE name=?",
                          (CAL_NAME,)).fetchone()
    except Exception:                                    # noqa: BLE001
        return None
    if not row:
        return None
    pl, met = json.loads(row["payload"]), json.loads(row["metrics"] or "{}")
    # Impede usar calibrador antigo com vetor de features de outro tamanho.
    if pl.get("feature_version") != FEATURE_VERSION:
        return None
    m = {"b": np.array(pl["b"]), "mu": np.array(pl["mu"]), "sd": np.array(pl["sd"])}
    return {"model": m, "metrics": met}


def vol_probability(con, ticker: str, asof: int, n_eff: float = 0.0,
                    dispersion: float = 0.0, ab: dict | None = None,
                    drv_vol: dict | None = None, cal: dict | None = None) -> dict:
    """Cabeca de agitacao: P(amanha ficar no top 20% de agitacao deste papel).

    REGRA: `p_vol` so sai preenchido com `vol_calib = 1`, isto e, quando o
    calibrador gravado por `fit_calibrator` passou na porta fora da amostra.
    Sem isso devolve `vol_score`, um escore PROVISORIO que so serve para
    ORDENAR os papeis (vira faixa baixa/media/alta em aggregate.run) e nunca
    deve ser exibido como numero.

    Por que top 20% e nao "acima da mediana": medimos as duas. Na mediana o
    AUC e 0.637; no top 20%, 0.683; no top 10%, 0.743.
    """
    from .label import abnormal_returns

    vazio = {"p_vol": None, "vol_base": None, "vol_calib": 0, "vol_score": None}
    # `ab` pode vir pronto de aggregate.run: abnormal_returns le a tabela de
    # precos INTEIRA, e recalcular por papel fica quadratico na watchlist
    # (400 papeis x 400 leituras de ~1M linhas = minutos por requisicao).
    if ab is None:
        try:
            ab = abnormal_returns(con)
        except Exception:                                # noqa: BLE001
            return vazio

    serie = ab.get(ticker) or {}
    dates = sorted(serie)
    if len(dates) < MIN_HIST:
        return vazio

    # 1) calibrador aprovado -> probabilidade com lastro
    if cal is None:
        cal = load_calibrator(con)
    if cal and cal["metrics"].get("calibrado"):
        if drv_vol is None:
            drv_vol = panel_vol(con)
        # O proximo pregao e o dia-alvo: Payroll agendado nele e conhecido
        # antes da abertura. Feriados locais nao sao inferidos aqui; a feature
        # e validada apenas nas datas observadas do historico.
        alvo = dt.date.fromisoformat(dates[-1]) + dt.timedelta(days=1)
        while alvo.weekday() >= 5:
            alvo += dt.timedelta(days=1)
        f = build_features(serie, dates, len(dates) - 1, drv_vol,
                           target_date=alvo.isoformat())
        if f is not None:
            p = float(logit_predict(cal["model"], np.array([f]))[0])
            return {"p_vol": round(p, 4), "vol_base": cal["metrics"].get("taxa_base_oos"),
                    "vol_calib": 1, "vol_score": p}

    # 2) sem calibrador: escore provisorio, so ORDINAL
    mags = sorted(abs(serie[d]) for d in dates)
    limiar = _limiar(mags)
    if limiar <= 0:
        return vazio
    hist = [serie[d] for d in dates[-20:]]
    hoje = abs(serie[dates[-1]])
    v5, v20 = realized_vol(hist[-5:]), realized_vol(hist)
    razao = (0.5 * hoje + 0.3 * v5 + 0.2 * v20) / limiar
    score = razao * (1.0 + 0.05 * min(n_eff, 4.0) + 0.05 * min(dispersion, 1.0))
    return {"p_vol": None, "vol_base": None, "vol_calib": 0, "vol_score": round(score, 6)}


def faixas(sigs: list[dict]) -> None:
    """Escore provisorio -> faixa ORDINAL relativa a watchlist (tercis).

    Preenche `vol_faixa` (baixa/media/alta) e `vol_ordem` (1 = mais agitado)
    nos papeis SEM calibrador aprovado. Nada aqui e probabilidade."""
    cand = [s for s in sigs if not s.get("vol_calib") and s.get("vol_score") is not None]
    cand.sort(key=lambda s: -s["vol_score"])
    n = len(cand)
    for i, s in enumerate(cand):
        s["vol_ordem"] = i + 1
        s["vol_faixa"] = "alta" if i < n / 3 else ("media" if i < 2 * n / 3 else "baixa")
    calib = sorted((s for s in sigs if s.get("vol_calib")), key=lambda s: -(s.get("p_vol") or 0))
    for i, s in enumerate(calib):
        s["vol_ordem"] = i + 1
        s["vol_faixa"] = None
