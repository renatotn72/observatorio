"""O numero que o painel mostra e confiavel? Tabela de decis + ganho total.

"Acertar em 100" so significa alguma coisa se a probabilidade exibida for
HONESTA: quando o painel diz 35%, aconteceu em ~35 de 100? Isso e
confiabilidade (reliability), e e diferente de discriminacao (AUC). Um modelo
pode ordenar bem e mentir no nivel -- dizer 60% onde e 30%.

Mede tres coisas:
  1. decil a decil: previsto x realizado, com intervalo de Wilson
  2. ganho sobre o chute, em pontos percentuais e em multiplo
  3. o ganho AGREGADO, que e a resposta a "quanto o sistema ajuda no total"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math                                                   # noqa: E402

import numpy as np                                            # noqa: E402

from obs import volatility as vol                             # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.label import abnormal_returns                        # noqa: E402
from metrica_total import walk_forward                        # noqa: E402


def wilson(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * (c - m), 100 * (c + m)


def main():
    con = connect()
    ab = abnormal_returns(con)
    drv = vol.panel_vol(con)
    X, y, datas = vol._dataset(ab, drv)
    con.close()
    ordem = np.argsort(np.array(datas), kind="mergesort")
    X, y = X[ordem], y[ordem]
    datas = [datas[j] for j in ordem]

    r = walk_forward(X, y, datas)
    P, A = r["P"], r["A"]
    base = float(A.mean())
    print(f"n fora da amostra: {len(A)}   taxa-base: {100*base:.1f} em 100\n")

    print("=== confiabilidade por decil ===")
    print(f"{'decil':<7}{'previsto':>10}{'realizado':>11}{'IC95':>16}{'n':>7}"
          f"{'erro':>8}")
    bordas = np.quantile(P, np.linspace(0, 1, 11))
    erros, pesos = [], []
    for k in range(10):
        a, b = bordas[k], bordas[k + 1]
        sel = (P >= a) & (P <= b) if k == 9 else (P >= a) & (P < b)
        n = int(sel.sum())
        if n < 20:
            continue
        prev, real = float(P[sel].mean()), float(A[sel].mean())
        lo, hi = wilson(real, n)
        dentro = lo <= 100 * prev <= hi
        erros.append(abs(prev - real))
        pesos.append(n)
        print(f"  {k+1:<5}{100*prev:>10.1f}{100*real:>11.1f}"
              f"   [{lo:.1f}, {hi:.1f}]{n:>7}{100*(real-prev):>+8.1f}"
              f"{'' if dentro else '   FORA'}")

    ece = sum(e * w for e, w in zip(erros, pesos)) / sum(pesos)
    print(f"\n  erro de calibracao medio (ECE): {100*ece:.2f} pontos")

    print("\n=== ganho sobre o chute ===")
    print(f"{'faixa apontada':<26}{'acertos/100':>13}{'ganho pp':>10}{'x base':>9}")
    for topo, rot in ((0.05, "5% mais agitados"), (0.10, "10% mais agitados"),
                      (0.20, "20% mais agitados"), (0.50, "metade mais agitada")):
        lim = np.quantile(P, 1 - topo)
        sel = P >= lim
        prec = float(A[sel].mean())
        print(f"  {rot:<24}{100*prec:>12.1f}{100*(prec-base):>+10.1f}"
              f"{prec/base:>8.2f}x")

    print("\n=== ganho AGREGADO ===")
    # Quanto o sistema melhora, em media, a chance de quem o segue?
    # Compara: seguir o ranking do sistema x sortear ao acaso, para varios
    # tamanhos de "quantos papeis-dia eu acompanho".
    print(f"{'se voce acompanha':<26}{'com o sistema':>15}{'no acaso':>10}"
          f"{'ganho':>9}")
    for frac, rot in ((0.02, "os 2% do topo"), (0.05, "os 5% do topo"),
                      (0.10, "os 10% do topo"), (0.25, "os 25% do topo")):
        lim = np.quantile(P, 1 - frac)
        sel = P >= lim
        prec = float(A[sel].mean())
        print(f"  {rot:<24}{100*prec:>14.1f}{100*base:>10.1f}"
              f"{100*(prec-base):>+9.1f}")


if __name__ == "__main__":
    main()
