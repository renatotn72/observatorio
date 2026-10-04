"""Beta de baixa x beta de alta: que papel e mais suscetivel a CAIR.

A PERGUNTA QUE ISTO RESPONDE
"Da para detectar os papeis mais suscetiveis a variacao positiva ou negativa?"
A cabeca de agitacao ja diz quem vai se mexer MUITO, mas nao diz para que lado
a sensibilidade pende. Beta de baixa diz:

    beta_menos = cov(r_i, r_m | r_m < 0) / var(r_m | r_m < 0)
    beta_mais  = cov(r_i, r_m | r_m > 0) / var(r_m | r_m > 0)
    assimetria = beta_menos - beta_mais

Assimetria > 0 e o papel que acompanha a queda do mercado mais do que
acompanha a alta -- o que o investidor sente como "esse cai junto e sobe
sozinho". Ang, Chen e Xing (2006) documentaram premio para essa exposicao.

O QUE *NAO* SE PODE CONCLUIR DISSO
Beta de baixa alto NAO prevê queda. Ele diz como o papel reage DADO que o
mercado caiu -- e condicional, nao preditivo. Quem confunde as duas coisas
acaba comprando defensiva achando que previu o mercado.

O TESTE QUE IMPORTA E O DE PERSISTENCIA
Medir assimetria na amostra e trivial e nao prova nada: qualquer ruido produz
algum numero. A pergunta util e se a assimetria estimada no passado ANTECIPA a
assimetria realizada depois. Se nao persistir, e ruido com nome bonito e nao
serve para ordenar papel nenhum. Por isso `teste_persistencia` faz
walk-forward com IC de Spearman e nulo de permutacao, igual ao resto do
projeto.

O mercado aqui e a MEDIA TRANSVERSAL dos papeis da watchlist, nao o retorno
residual: residualizar remove justamente o fator comum que o beta mede.
"""
from __future__ import annotations
import math
import random
import statistics as st

from .db import connect
from .prices import returns_by_date

MIN_OBS_LADO = 30        # minimo de pregoes de cada lado para estimar o beta
JANELA_PADRAO = 252      # ~1 ano de pregoes


def mercado(rets: dict[str, dict[str, float]],
            universo: list[str] | None = None) -> dict[str, float]:
    """Retorno de mercado = media transversal do dia (>= 3 papeis)."""
    universo = universo or sorted(rets)
    datas = sorted({d for t in universo for d in rets.get(t, {})})
    out = {}
    for d in datas:
        dia = [rets[t][d] for t in universo if d in rets.get(t, {})]
        if len(dia) >= 3:
            out[d] = sum(dia) / len(dia)
    return out


def _beta(pares: list[tuple[float, float]]) -> float | None:
    """Beta de r_i contra r_m por minimos quadrados, sem intercepto imposto."""
    if len(pares) < MIN_OBS_LADO:
        return None
    xm = sum(p[1] for p in pares) / len(pares)
    ym = sum(p[0] for p in pares) / len(pares)
    num = sum((y - ym) * (x - xm) for y, x in pares)
    den = sum((x - xm) ** 2 for _, x in pares)
    return num / den if den > 0 else None


def betas(rets_tk: dict[str, float], mkt: dict[str, float],
          datas: list[str] | None = None) -> dict:
    """beta de baixa, beta de alta e assimetria para um papel."""
    datas = datas if datas is not None else sorted(set(rets_tk) & set(mkt))
    baixo = [(rets_tk[d], mkt[d]) for d in datas
             if d in rets_tk and d in mkt and mkt[d] < 0]
    alto = [(rets_tk[d], mkt[d]) for d in datas
            if d in rets_tk and d in mkt and mkt[d] > 0]
    bm, bp = _beta(baixo), _beta(alto)
    return {"beta_baixa": bm, "beta_alta": bp,
            "assimetria": (bm - bp) if (bm is not None and bp is not None) else None,
            "n_baixa": len(baixo), "n_alta": len(alto)}


def painel(ticker: str | None = None, janela: int | None = None) -> list[dict]:
    """Assimetria corrente de cada papel, da janela mais recente."""
    con = connect()
    rets = returns_by_date(con)
    con.close()
    mkt = mercado(rets)
    todas = sorted(mkt)
    if janela:
        todas = todas[-janela:]
    out = []
    for tkr in (sorted(rets) if ticker is None else [ticker.upper()]):
        if tkr not in rets:
            continue
        b = betas(rets[tkr], mkt, todas)
        b["ticker"] = tkr
        out.append(b)
    out.sort(key=lambda d: -(d["assimetria"] if d["assimetria"] is not None else -9))
    return out


def _spearman(a: list[float], b: list[float]) -> float:
    def postos(v):
        ordem = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(ordem):
            j = i
            while j + 1 < len(ordem) and v[ordem[j + 1]] == v[ordem[i]]:
                j += 1
            media = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[ordem[k]] = media
            i = j + 1
        return r
    ra, rb = postos(a), postos(b)
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((x - mb) ** 2 for x in rb))
    return num / (da * db) if da > 0 and db > 0 else 0.0


def teste_persistencia(janela_est: int = JANELA_PADRAO, horizonte: int = 63,
                       passo: int | None = None, n_perm: int = 500,
                       semente: int = 20261002) -> dict:
    """A assimetria estimada no passado antecipa a realizada depois?

    Walk-forward: estima em [t-janela_est, t], realiza em (t, t+horizonte].
    IC de Spearman transversal por data de corte, media das datas. Nulo por
    permutacao dos papeis DENTRO de cada corte -- preserva o numero de papeis
    e a distribuicao, destroi so o pareamento.

    `passo` DEFAULTA A `horizonte`, isto e, cortes SEM SOBREPOSICAO -- e essa
    escolha nao e detalhe. MEDIDO: com passo=21 e horizonte=126, cada janela
    futura divide dados com ~6 vizinhas; os 101 "cortes" valem ~17 observacoes
    independentes, e o t sai inflado por ~sqrt(6).

        passo=21  (sobreposto):  IC +0.119  t 3.16  p 0.000  "PASSOU"
        passo=126 (independente): IC +0.136  t 1.18  p 0.085  REPROVADO

    O IC quase nao muda; o que muda e a barra de erro. Mesma armadilha que
    fez o driver de energia parecer significativo antes do Fama-MacBeth.
    Passar `passo` menor que `horizonte` e legitimo para ver a curva, mas o
    veredito so vale com cortes independentes.
    """
    if passo is None:
        passo = horizonte
    con = connect()
    rets = returns_by_date(con)
    con.close()
    mkt = mercado(rets)
    datas = sorted(mkt)
    universo = sorted(rets)
    ics, cortes = [], []
    i = janela_est
    while i + horizonte < len(datas):
        jan_est = datas[i - janela_est:i]
        jan_fut = datas[i:i + horizonte]
        est, fut = [], []
        for tkr in universo:
            a = betas(rets[tkr], mkt, jan_est)["assimetria"]
            b = betas(rets[tkr], mkt, jan_fut)["assimetria"]
            if a is not None and b is not None:
                est.append(a)
                fut.append(b)
        if len(est) >= 5:
            ics.append(_spearman(est, fut))
            cortes.append((datas[i], est, fut))
        i += passo
    if not ics:
        return {"erro": "historico insuficiente", "n_cortes": 0}

    ic = sum(ics) / len(ics)
    dp = st.pstdev(ics) if len(ics) > 1 else 0.0
    t = ic / (dp / math.sqrt(len(ics))) if dp > 0 else float("nan")

    rnd = random.Random(semente)
    nulos = []
    for _ in range(n_perm):
        vals = []
        for _dt, est, fut in cortes:
            emb = fut[:]
            rnd.shuffle(emb)
            vals.append(_spearman(est, emb))
        nulos.append(sum(vals) / len(vals))
    p = sum(1 for x in nulos if abs(x) >= abs(ic)) / len(nulos)

    return {"ic_spearman": round(ic, 4), "t": round(t, 2) if t == t else None,
            "p_permutacao": round(p, 4), "n_cortes": len(ics),
            "janela_est": janela_est, "horizonte": horizonte,
            "n_permutacoes": n_perm,
            "veredito": "PASSOU" if (p < 0.05 and abs(ic) > 0.1) else "REPROVADO"}
