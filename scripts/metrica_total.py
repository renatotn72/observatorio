"""Quanto o sistema acerta em 100 -- feature a feature e em conjunto.

TRES PERGUNTAS, TRES RESPOSTAS DIFERENTES

1. UNITARIA   cada feature sozinha vale o que, fora da amostra?
2. INTEGRADA  somadas, quanto cada uma AINDA acrescenta? (deixa-uma-de-fora)
3. OPERACIONAL  no ponto em que o painel de fato aponta, quantos acertos em 100?

A terceira e a unica que responde "o sistema acerta quanto". AUC nao e taxa de
acerto: AUC 0.59 nao quer dizer 59 em 100. AUC e a chance de ordenar
corretamente um par (dia agitado, dia calmo) sorteado ao acaso. A taxa de
acerto depende do PONTO DE CORTE e da taxa-base -- e com taxa-base de 20%,
"acuracia" e uma metrica mentirosa: quem responde "nao vai agitar" todo dia
acerta 80 em 100 e nao serve para nada.

Por isso a secao operacional reporta PRECISAO NO TOPO: dos dias que o sistema
aponta como mais agitados, quantos de fato foram. E compara com a taxa-base,
que e o que voce teria acertando no chute.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bisect                                                 # noqa: E402
import math                                                   # noqa: E402

import numpy as np                                            # noqa: E402

from obs import volatility as vol                             # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.label import abnormal_returns                        # noqa: E402

DOBRAS = vol.CAL_DOBRAS


def walk_forward(X, y, datas, cols=None):
    """OOS por dobras temporais. `cols` = subconjunto de features."""
    Xs = X if cols is None else X[:, list(cols)]
    unicas = sorted(set(datas))
    cortes = [unicas[int(len(unicas) * k / DOBRAS)] for k in range(1, DOBRAS)]
    lim = [bisect.bisect_left(datas, c) for c in cortes] + [len(datas)]
    P, A, B = [], [], []
    for k in range(len(cortes)):
        tr, te = slice(0, lim[k]), slice(lim[k], lim[k + 1])
        if y[tr].sum() < 10 or len(y[te]) == 0:
            continue
        m = vol.logit_fit(Xs[tr], y[tr])
        P.append(vol.logit_predict(m, Xs[te]))
        A.append(y[te])
        B.append(np.full(len(y[te]), y[tr].mean()))
    if not P:
        return None
    P, A, B = np.concatenate(P), np.concatenate(A), np.concatenate(B)
    brier = float(((P - A) ** 2).mean())
    base = float(((B - A) ** 2).mean())
    return {"auc": vol._auc(P, A), "skill": 1 - brier / base if base > 0 else 0.0,
            "n": len(A), "P": P, "A": A, "taxa_base": float(A.mean())}


def ic_para_acertos(ic: float) -> float:
    """IC de postos -> acertos em 100, para sinal binario.

    Relacao de Grenander/para normal bivariada: P(sinal concordante) =
    0.5 + arcsin(rho)/pi. E a traducao honesta entre "correlacao fraca" e
    "quantas vezes em 100", e e por isso que IC 0.09 vira ~52.9, nao 59.
    """
    ic = max(-0.999, min(0.999, ic))
    return 100.0 * (0.5 + math.asin(ic) / math.pi)


def main():
    con = connect()
    ab = abnormal_returns(con)
    drv = vol.panel_vol(con)
    X, y, datas = vol._dataset(ab, drv)
    ordem = np.argsort(np.array(datas), kind="mergesort")
    X, y = X[ordem], y[ordem]
    datas = [datas[j] for j in ordem]
    print(f"amostra: {len(y)} pares (papel, dia)  taxa-base {y.mean():.1%}")
    print(f"periodo: {datas[0]} .. {datas[-1]}\n")

    nomes = vol.FEATURES
    print("=== 1. UNITARIA: cada feature sozinha (fora da amostra) ===")
    print(f"{'feature':<46}{'AUC':>8}{'skill':>9}")
    unit = []
    for i, nm in enumerate(nomes):
        r = walk_forward(X, y, datas, cols=[i])
        unit.append((nm, r["auc"], r["skill"]))
        print(f"  {nm:<44}{r['auc']:>8.4f}{r['skill']:>+9.4f}")

    print("\n=== 2. INTEGRADA ===")
    cheio = walk_forward(X, y, datas)
    print(f"  modelo completo ({len(nomes)} features){'':<13}"
          f"{cheio['auc']:>8.4f}{cheio['skill']:>+9.4f}")
    print("\n  deixa-uma-de-fora (quanto PERDE sem ela):")
    print(f"{'feature retirada':<46}{'AUC':>8}{'delta':>9}")
    for i, nm in enumerate(nomes):
        cols = [j for j in range(len(nomes)) if j != i]
        r = walk_forward(X, y, datas, cols=cols)
        print(f"  {nm:<44}{r['auc']:>8.4f}{r['auc'] - cheio['auc']:>+9.4f}")

    print("\n  acumulada (em ordem de valor unitario):")
    ordem_u = [nomes.index(n) for n, _a, _s in
               sorted(unit, key=lambda t: -t[1])]
    print(f"{'ate':<46}{'AUC':>8}{'ganho':>9}")
    ant = 0.5
    for k in range(1, len(ordem_u) + 1):
        r = walk_forward(X, y, datas, cols=ordem_u[:k])
        print(f"  +{nomes[ordem_u[k-1]]:<43}{r['auc']:>8.4f}{r['auc'] - ant:>+9.4f}")
        ant = r["auc"]

    print("\n=== 3. OPERACIONAL: acertos em 100 ===")
    P, A = cheio["P"], cheio["A"]
    base = cheio["taxa_base"]
    print(f"  taxa-base (chute): {100*base:.1f} em 100\n")
    print(f"{'quando o sistema aponta':<34}{'acertos/100':>13}{'vs base':>10}{'n':>8}")
    for topo in (0.05, 0.10, 0.20, 0.30):
        lim = np.quantile(P, 1 - topo)
        sel = P >= lim
        if sel.sum() < 30:
            continue
        prec = float(A[sel].mean())
        print(f"  os {int(topo*100):>2}% mais agitados{'':<14}{100*prec:>12.1f}"
              f"{prec/base:>9.2f}x{int(sel.sum()):>8}")
    lim = np.quantile(P, 0.20)
    sel = P <= lim
    print(f"  os 20% mais calmos{'':<14}{100*float(A[sel].mean()):>12.1f}"
          f"{float(A[sel].mean())/base:>9.2f}x{int(sel.sum()):>8}")

    print("\n=== 4. AS TRES CABECAS ===")
    con2 = connect()
    n_rot = con2.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    n_news = con2.execute(
        "SELECT COUNT(*) FROM (SELECT m.ticker, date(a.published_ts,'unixepoch') d "
        "FROM mentions m JOIN articles a ON a.id=m.article_id "
        "JOIN scores s ON s.article_id=a.id AND s.ticker=m.ticker "
        "WHERE m.ticker!='__none__' GROUP BY 1,2)").fetchone()[0]
    con2.close()
    print(f"  AGITACAO   MEDIDA   AUC {cheio['auc']:.4f}, n_oos {cheio['n']}")
    print(f"  DIRECAO    BLOQUEADA  {n_rot} rotulos (min 120)")
    print(f"             se o IC do canal de noticia for 0.09, dá "
          f"{ic_para_acertos(0.09):.1f} em 100")
    print(f"             IC necessario para 70 em 100: ", end="")
    alvo = math.sin((0.70 - 0.5) * math.pi)
    print(f"{alvo:.3f} ({alvo/0.09:.1f}x o medido)")
    print(f"  ATENCAO    BLOQUEADA  {n_news} dias-papel com noticia (min 120)")
    con.close()


if __name__ == "__main__":
    main()
