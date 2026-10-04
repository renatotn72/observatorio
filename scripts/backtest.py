#!/usr/bin/env python3
"""Backtest walk-forward com embargo.

Por que nao k-fold aleatorio: noticias vizinhas no tempo compartilham o mesmo
retorno de mercado. Embaralhar vaza informacao do futuro para o treino e te
entrega um resultado otimo que nao existe. Aqui o calibrador e reajustado em
cada dobra usando SO o passado, com um embargo entre treino e teste.

Metricas que importam (acuracia NAO esta entre elas):
  IC       correlacao de Spearman entre sinal e retorno anormal realizado
  skill    1 - Brier_modelo/Brier_taxa_base  (>0 = agrega informacao)
  decis    retorno anormal medio por decil de sinal: tem de ser monotono
  hit      acerto direcional condicionado a |sinal| alto

Uso:  python3 scripts/backtest.py [--folds 6] [--embargo-days 3] [--horizon 1d]
"""
from __future__ import annotations
import argparse
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs.calibrate import (brier, pava, platt, platt_predict,  # noqa: E402
                           predict)
from obs.db import connect                              # noqa: E402
from obs.util import date_str                           # noqa: E402


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def load(horizon: str):
    con = connect()
    rows = con.execute("""
        SELECT s.ticker, s.asof_ts, s.z, s.n_eff, l.car, l.sigma, l.cls
        FROM signals s JOIN labels l
          ON l.ticker=s.ticker AND l.asof_ts=s.asof_ts AND l.horizon=?
        ORDER BY s.asof_ts ASC""", (horizon,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def decile_table(zs, cars, sigmas, k=10):
    idx = sorted(range(len(zs)), key=lambda i: zs[i])
    out = []
    size = max(1, len(idx) // k)
    for b in range(k):
        chunk = idx[b * size:(b + 1) * size] if b < k - 1 else idx[(k - 1) * size:]
        if not chunk:
            continue
        out.append({
            "decil": b + 1, "n": len(chunk),
            "z_medio": st.fmean(zs[i] for i in chunk),
            # retorno anormal em unidades de sigma: comparavel entre papeis
            "car_sigma": st.fmean(cars[i] / sigmas[i] for i in chunk if sigmas[i]),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--embargo-days", type=int, default=3)
    ap.add_argument("--horizon", default="1d")
    ap.add_argument("--min-train", type=int, default=120)
    ap.add_argument("--method", default="both", choices=["both", "platt", "isotonic"])
    a = ap.parse_args()

    data = load(a.horizon)
    if len(data) < a.min_train * 2:
        print(f"Dados insuficientes: {len(data)} eventos rotulados.")
        print(f"Precisa de ~{a.min_train*2}. Acumule historico ou rode `obs demo`.")
        return 1

    n = len(data)
    fold_size = n // (a.folds + 1)
    embargo = a.embargo_days * 86400

    methods = ["platt", "isotonic"] if a.method == "both" else [a.method]
    oos = {m: {"z": [], "car": [], "sigma": [], "cls": [],
               "p_up": [], "p_dn": [], "base_up": [], "base_dn": []} for m in methods}

    print(f"{n} eventos  |  {date_str(data[0]['asof_ts'])} -> {date_str(data[-1]['asof_ts'])}")
    print(f"walk-forward: {a.folds} dobras, embargo de {a.embargo_days} dias\n")
    hdr = f"{'dobra':>5} {'treino':>7} {'teste':>6} {'IC':>8}"
    for m in methods:
        hdr += f" {'sk_up/'+m[:4]:>12} {'sk_dn/'+m[:4]:>12}"
    print(hdr)

    for f in range(a.folds):
        split = (f + 1) * fold_size
        test = data[split:split + fold_size]
        if not test:
            continue
        cutoff = test[0]["asof_ts"] - embargo
        train = [d for d in data[:split] if d["asof_ts"] < cutoff]
        if len(train) < a.min_train:
            print(f"{f+1:>5} {len(train):>7} {len(test):>6}   (treino curto, pulada)")
            continue

        zs = [d["z"] for d in train]
        tr_up = [1.0 if d["cls"] == 1 else 0.0 for d in train]
        tr_dn = [1.0 if d["cls"] == -1 else 0.0 for d in train]
        b_up, b_dn = st.fmean(tr_up), st.fmean(tr_dn)

        tz = [d["z"] for d in test]
        y_up = [1.0 if d["cls"] == 1 else 0.0 for d in test]
        y_dn = [1.0 if d["cls"] == -1 else 0.0 for d in test]
        ic = spearman(tz, [d["car"] / d["sigma"] for d in test])
        line = f"{f+1:>5} {len(train):>7} {len(test):>6} {ic:>8.4f}"

        for m in methods:
            if m == "isotonic":
                k_up, k_dn = pava(zs, tr_up), pava([-z for z in zs], tr_dn)
                p_up = [predict(k_up, z) for z in tz]
                p_dn = [predict(k_dn, -z) for z in tz]
            else:
                k_up, k_dn = platt(zs, tr_up), platt([-z for z in zs], tr_dn)
                p_up = [platt_predict(k_up, z) for z in tz]
                p_dn = [platt_predict(k_dn, -z) for z in tz]

            s_up = 1 - brier(p_up, y_up) / max(1e-9, brier([b_up] * len(y_up), y_up))
            s_dn = 1 - brier(p_dn, y_dn) / max(1e-9, brier([b_dn] * len(y_dn), y_dn))
            line += f" {s_up:>12.4f} {s_dn:>12.4f}"

            o = oos[m]
            for d, pu, pd_ in zip(test, p_up, p_dn):
                o["z"].append(d["z"]); o["car"].append(d["car"])
                o["sigma"].append(d["sigma"]); o["cls"].append(d["cls"])
                o["p_up"].append(pu); o["p_dn"].append(pd_)
                o["base_up"].append(b_up); o["base_dn"].append(b_dn)
        print(line)

    ref = oos[methods[0]]
    if not ref["z"]:
        print("\nNenhuma dobra avaliavel.")
        return 1

    print("\n=== AGREGADO FORA DA AMOSTRA ===")
    ic = spearman(ref["z"], [c / s for c, s in zip(ref["car"], ref["sigma"])])
    print(f"n fora da amostra : {len(ref['z'])}")
    print(f"IC (Spearman)     : {ic:+.4f}   [0.02-0.05 ja e util em producao]")

    for m in methods:
        o = oos[m]
        y_up = [1.0 if c == 1 else 0.0 for c in o["cls"]]
        y_dn = [1.0 if c == -1 else 0.0 for c in o["cls"]]
        sk_up = 1 - brier(o["p_up"], y_up) / max(1e-9, brier(o["base_up"], y_up))
        sk_dn = 1 - brier(o["p_dn"], y_dn) / max(1e-9, brier(o["base_dn"], y_dn))
        print(f"skill Brier [{m:>8}] : alta {sk_up:+.4f}  queda {sk_dn:+.4f}   [>0 = bate a base]")

    strong = [i for i in range(len(ref["z"])) if abs(ref["z"][i]) > 0.4]
    if strong:
        hit = st.fmean(1.0 if (ref["z"][i] > 0) == (ref["car"][i] > 0) else 0.0 for i in strong)
        print(f"acerto |z|>0.4    : {hit:.3f} em {len(strong)} casos  [50% = nada]")

    print("\ndecis de sinal (CAR medio em unidades de sigma; procure MONOTONIA):")
    print(f"  {'decil':>5} {'n':>5} {'z_medio':>9} {'car/sigma':>11}")
    for r in decile_table(ref["z"], ref["car"], ref["sigma"]):
        print(f"  {r['decil']:>5} {r['n']:>5} {r['z_medio']:>+9.3f} {r['car_sigma']:>+11.4f}")

    print("\nLembretes: resultado bruto, SEM custo de transacao. Spread + slippage na B3")
    print("come boa parte disso. IC positivo nao e estrategia -- e so informacao.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
