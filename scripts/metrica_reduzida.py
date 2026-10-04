"""O modelo de 5 features e melhor que um menor? E a precisao tem que margem?

A leitura unitaria sugeriu duas coisas:
  - Payroll sozinho da AUC 0.4614, ABAIXO de 0.50
  - tirar vol-5 nao muda nada (delta 0.0000): e redundante com vol-20
Aqui testa-se cada subconjunto e poe-se intervalo de confianca na precisao
operacional, que e o numero que o usuario le como "acertos em 100".
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import numpy as np                                            # noqa: E402

from obs import volatility as vol                             # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.label import abnormal_returns                        # noqa: E402
from metrica_total import walk_forward                        # noqa: E402

SUBCONJUNTOS = {
    "todas as 5": [0, 1, 2, 3, 4],
    "sem Payroll (4)": [0, 1, 2, 3],
    "sem Payroll nem vol-5 (3)": [0, 2, 3],
    "so vol-20 + |ret| hoje (2)": [0, 2],
    "so vol-20 (1)": [2],
}


def main():
    con = connect()
    ab = abnormal_returns(con)
    drv = vol.panel_vol(con)
    X, y, datas = vol._dataset(ab, drv)
    ordem = np.argsort(np.array(datas), kind="mergesort")
    X, y = X[ordem], y[ordem]
    datas = [datas[j] for j in ordem]
    con.close()

    print(f"{'modelo':<30}{'AUC':>8}{'skill':>9}{'prec@5%':>10}")
    guarda = {}
    for nome, cols in SUBCONJUNTOS.items():
        r = walk_forward(X, y, datas, cols=cols)
        lim = np.quantile(r["P"], 0.95)
        sel = r["P"] >= lim
        prec = float(r["A"][sel].mean())
        guarda[nome] = (r, prec, int(sel.sum()))
        print(f"  {nome:<28}{r['auc']:>8.4f}{r['skill']:>+9.4f}{100*prec:>9.1f}")

    print("\n=== margem de erro da precisao no topo 5% ===")
    print("(Wilson 95%; e a faixa honesta do 'acerta X em 100')")
    for nome, (r, prec, n) in guarda.items():
        z = 1.96
        den = 1 + z * z / n
        centro = (prec + z * z / (2 * n)) / den
        meio = z * ((prec * (1 - prec) / n + z * z / (4 * n * n)) ** 0.5) / den
        print(f"  {nome:<28}{100*prec:>6.1f}  "
              f"[{100*(centro-meio):.1f}, {100*(centro+meio):.1f}]  n={n}")

    base = float(y.mean())
    print(f"\n  taxa-base: {100*base:.1f} em 100")
    print("  Se o intervalo nao exclui a taxa-base, o modelo nao provou nada.")


if __name__ == "__main__":
    main()
