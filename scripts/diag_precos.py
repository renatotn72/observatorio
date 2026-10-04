#!/usr/bin/env python3
"""Ponto 3.3 — estado do banco de precos por ticker x granularidade.

Antes de coletar qualquer coisa: o que ja temos, de quando ate quando, quantas
barras, e onde estao os buracos.

NAO COLETA NADA. So le o banco.

LACUNA, aqui, e dia de pregao em que OUTROS papeis tem barra e este nao tem.
E a definicao util: nao existe calendario da B3 no banco, mas se oito papeis
negociaram num dia e o nono nao, ou ele nao negociou mesmo (iliquidez) ou
faltou coleta. As duas coisas importam, e as duas aparecem aqui.

USO
    python3 scripts/diag_precos.py
    python3 scripts/diag_precos.py --gran diario
    python3 scripts/diag_precos.py --csv        # grava data/diag_precos.csv
"""
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs.db import connect                                   # noqa: E402

GRANS_INTRA = ("1m", "5m", "15m", "1h")


def _fmt(d):
    return d if d else "—"


def diario(con):
    rows = con.execute(
        "SELECT ticker, date, close FROM prices ORDER BY ticker, date").fetchall()
    por = {}
    for r in rows:
        por.setdefault(r["ticker"], []).append(r["date"])
    # pregoes = uniao das datas de TODOS os papeis
    todos = sorted({d for v in por.values() for d in v})
    idx = {d: i for i, d in enumerate(todos)}
    out = []
    for tkr, datas in sorted(por.items()):
        datas = sorted(set(datas))
        i0, i1 = idx[datas[0]], idx[datas[-1]]
        esperadas = i1 - i0 + 1          # pregoes no intervalo de vida do papel
        lacunas = esperadas - len(datas)
        # maior buraco seguido
        maior, atual = 0, 0
        presentes = set(datas)
        for i in range(i0, i1 + 1):
            if todos[i] in presentes:
                atual = 0
            else:
                atual += 1
                maior = max(maior, atual)
        atraso = len(todos) - 1 - i1     # quantos pregoes atras parou
        out.append({"ticker": tkr, "gran": "diario", "primeira": datas[0],
                    "ultima": datas[-1], "barras": len(datas),
                    "esperadas": esperadas, "lacunas": lacunas,
                    "maior_buraco": maior, "atraso_pregoes": atraso})
    return out, todos


def intra(con, gran):
    rows = con.execute(
        "SELECT simbolo, MIN(ts) a, MAX(ts) b, COUNT(*) n FROM intraday "
        "WHERE intervalo=? GROUP BY simbolo ORDER BY simbolo", (gran,)).fetchall()
    f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")  # noqa: E731
    return [{"ticker": r["simbolo"].replace(".SA", ""), "gran": gran,
             "primeira": f(r["a"]), "ultima": f(r["b"]), "barras": r["n"],
             "esperadas": None, "lacunas": None, "maior_buraco": None,
             "atraso_pregoes": None} for r in rows]


def main(so_gran=None, como_csv=False):
    con = connect()
    linhas, pregoes = diario(con)
    if so_gran in (None, "diario"):
        print(f"\n{'=' * 100}")
        print("DIARIO  (tabela `prices`)")
        print(f"{'=' * 100}")
        print(f"calendario observado: {len(pregoes)} pregoes, "
              f"{pregoes[0]} a {pregoes[-1]}")
        print(f"\n{'papel':<9}{'primeira':<12}{'ultima':<12}{'barras':>8}"
              f"{'esperadas':>11}{'lacunas':>9}{'maior buraco':>14}"
              f"{'parou ha':>10}")
        for x in linhas:
            marca = ""
            if x["atraso_pregoes"] > 5:
                marca = "  <- DESATUALIZADO"
            elif x["lacunas"] > 0.05 * x["esperadas"]:
                marca = "  <- muitas lacunas"
            print(f"{x['ticker']:<9}{x['primeira']:<12}{x['ultima']:<12}"
                  f"{x['barras']:>8}{x['esperadas']:>11}{x['lacunas']:>9}"
                  f"{x['maior_buraco']:>14}{x['atraso_pregoes']:>10}{marca}")
        tot = sum(x["barras"] for x in linhas)
        lac = sum(x["lacunas"] for x in linhas)
        print(f"\n{'TOTAL':<9}{'':<12}{'':<12}{tot:>8}"
              f"{sum(x['esperadas'] for x in linhas):>11}{lac:>9}")
        print("\n'esperadas' = pregoes entre a primeira e a ultima barra DESTE papel,")
        print("contados pelo calendario observado (uniao das datas de todos).")
        print("'lacunas' = esperadas - barras. Pode ser iliquidez ou falha de coleta.")
        print("'parou ha' = pregoes desde a ultima barra ate o fim do calendario.")

    for g in GRANS_INTRA:
        if so_gran not in (None, g):
            continue
        li = intra(con, g)
        print(f"\n{'=' * 100}")
        print(f"INTRADIARIO {g}  (tabela `intraday`)")
        print(f"{'=' * 100}")
        if not li:
            print("  sem barras nesta granularidade")
            continue
        print(f"{'papel':<9}{'primeira':<12}{'ultima':<12}{'barras':>8}")
        for x in li:
            print(f"{x['ticker']:<9}{x['primeira']:<12}{x['ultima']:<12}{x['barras']:>8}")
        print(f"\n{'TOTAL':<9}{'':<12}{'':<12}{sum(x['barras'] for x in li):>8}"
              f"   em {len(li)} simbolos")
        linhas += li

    # papeis da watchlist que NAO tem preco nenhum
    from obs import config
    tem = {x["ticker"] for x in linhas}
    faltam = [t for t in config.tickers() if t not in tem]
    print(f"\n{'=' * 100}")
    print("PAPEIS DA WATCHLIST SEM PRECO NENHUM")
    print(f"{'=' * 100}")
    print("  " + (", ".join(faltam) if faltam else "nenhum"))

    con.close()
    if como_csv:
        p = "data/diag_precos.csv"
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(linhas[0]))
            w.writeheader()
            w.writerows(linhas)
        print(f"\n-> {p}")
    return linhas


if __name__ == "__main__":
    a = sys.argv[1:]
    g = next((a[i + 1] for i, x in enumerate(a) if x == "--gran" and i + 1 < len(a)), None)
    main(g, "--csv" in a)
