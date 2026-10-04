"""Calibracao VERDADEIRA da direcao -- sem esperar historico de noticia.

O IMPASSE E O CONTORNO
A direcao nunca foi calibrada porque o rotulo exige sinal do PASSADO casado
com retorno futuro, e so ha tres dias de noticia. Mas o sistema tem DEZ ANOS
de drivers e a cadeia de afetacao ja monta um sinal transversal a partir
deles. Entao da para calibrar e testar a direcao de verdade agora -- no canal
de DRIVERS, nao no de noticia.

O QUE ISTO MEDE E O QUE NAO MEDE
    MEDE  : a direcao e previsivel a partir da cadeia de afetacao?
            o maquinario de calibracao produz probabilidade com lastro?
    NAO MEDE: o canal de NOTICIA. Esse continua esperando o backfill.

AS TRES DEFESAS CONTRA VAZAMENTO DE FUTURO
1. betas reestimados a cada 21 pregoes, e `fit_exposures(asof=T)` so usa
   `d < T` -- nenhuma observacao do dia-alvo entra na estimacao;
2. o sinal do dia T usa retorno de DRIVER de T; o alvo e o pregao T+1 da B3.
   Driver como SPX e DXY fecha depois da B3, mas antes da ABERTURA de T+1,
   entao a informacao existe quando a aposta seria feita;
3. a calibracao e walk-forward: o modelo de cada dobra so ve dobras anteriores.

O ALVO e o mesmo do resto do projeto: retorno ANORMAL (residuo transversal),
classificado em alta/neutro/queda por K_SIGMA desvios do proprio papel.
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import bisect                                                 # noqa: E402
import math                                                   # noqa: E402
import random                                                 # noqa: E402
import statistics as st                                       # noqa: E402

import numpy as np                                            # noqa: E402

from obs import drivers, volatility as vol                     # noqa: E402
from obs.db import connect                                     # noqa: E402
from obs.label import K_SIGMA, MIN_SIGMA_OBS, abnormal_returns  # noqa: E402
from obs.prices import returns_by_date                         # noqa: E402

REESTIMA = 21        # pregoes entre reestimacoes dos betas
DOBRAS = 5
MIN_OOS = 500


def constroi(verbose=True):
    """(z do sinal de drivers, classe em D+1) ao longo de todo o historico."""
    con = connect()
    rets = returns_by_date(con)
    ab = abnormal_returns(con)
    dret = drivers.driver_returns(con)
    con.close()
    if not dret:
        return None

    datas_drv = sorted(set.intersection(*[set(v) for v in dret.values()]))
    # desvio expansivo por papel, para classificar em multiplos de sigma
    sig: dict[str, dict[str, float]] = {}
    for tkr, serie in ab.items():
        ds, vals, acc = sorted(serie), [], {}
        for d in ds:
            if len(vals) >= MIN_SIGMA_OBS:
                s = st.pstdev(vals)
                if s > 0:
                    acc[d] = s
            vals.append(serie[d])
        sig[tkr] = acc

    Z, Y, D = [], [], []
    exposures = None
    for i, dia in enumerate(datas_drv):
        if i % REESTIMA == 0:
            # betas SO com dados anteriores a `dia`
            exposures = drivers.fit_exposures(rets, dia, persist=False)
            if verbose and i % (REESTIMA * 20) == 0:
                print(f"  ... {dia} ({len(exposures)} papeis)", flush=True)
        if not exposures:
            continue
        sinal = drivers.driver_signal(exposures, dret, dia)
        for tkr, z in sinal.items():
            serie = ab.get(tkr) or {}
            ds = sorted(d for d in serie if d > dia)
            if not ds:
                continue
            alvo = ds[0]
            s = sig.get(tkr, {}).get(alvo)
            if not s:
                continue
            r = serie[alvo]
            Z.append(z)
            Y.append(1 if r > K_SIGMA * s else (-1 if r < -K_SIGMA * s else 0))
            D.append(alvo)
    return np.array(Z), np.array(Y), D


def _wilson(p, n, z=1.96):
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return 100 * (c - m), 100 * (c + m)


def avalia(Z, alvo_bin, D, nome):
    """Calibra z -> P(classe) walk-forward e mede fora da amostra."""
    ordem = np.argsort(np.array(D), kind="mergesort")
    Zs, ys = Z[ordem], alvo_bin[ordem]
    Ds = [D[j] for j in ordem]
    unicas = sorted(set(Ds))
    cortes = [unicas[int(len(unicas) * k / DOBRAS)] for k in range(1, DOBRAS)]
    lim = [bisect.bisect_left(Ds, c) for c in cortes] + [len(Ds)]
    P, A, B = [], [], []
    for k in range(len(cortes)):
        tr, te = slice(0, lim[k]), slice(lim[k], lim[k + 1])
        if ys[tr].sum() < 20 or len(ys[te]) == 0:
            continue
        m = vol.logit_fit(Zs[tr].reshape(-1, 1), ys[tr])
        P.append(vol.logit_predict(m, Zs[te].reshape(-1, 1)))
        A.append(ys[te])
        B.append(np.full(len(ys[te]), ys[tr].mean()))
    if not P:
        return None
    P, A, B = np.concatenate(P), np.concatenate(A), np.concatenate(B)
    brier = float(((P - A) ** 2).mean())
    base = float(((B - A) ** 2).mean())
    skill = 1 - brier / base if base > 0 else 0.0
    auc = vol._auc(P, A)
    topo = np.quantile(P, 0.9)
    sel = P >= topo
    prec = float(A[sel].mean())
    lo, hi = _wilson(prec, int(sel.sum()))
    return {"nome": nome, "n_oos": len(A), "taxa_base": float(A.mean()),
            "auc": auc, "skill": skill, "prec_topo10": prec,
            "ic95": (lo, hi), "n_topo": int(sel.sum())}


def main():
    print("Construindo sinal historico da cadeia de afetacao (walk-forward)...")
    dado = constroi()
    if dado is None:
        print("sem drivers no banco"); return
    Z, Y, D = dado
    print(f"\npares (papel, dia): {len(Z)}   periodo {D[0]} .. {D[-1]}")
    print(f"classes -> alta {100*(Y==1).mean():.1f}  neutro "
          f"{100*(Y==0).mean():.1f}  queda {100*(Y==-1).mean():.1f}")
    if len(Z) < MIN_OOS:
        print("amostra insuficiente"); return

    print(f"\n{'cabeca':<10}{'n_oos':>8}{'base':>8}{'AUC':>8}{'skill':>9}"
          f"{'prec@10%':>10}{'IC95':>16}")
    res = []
    for nome, alvo in (("ALTA", (Y == 1).astype(float)),
                       ("QUEDA", (Y == -1).astype(float))):
        r = avalia(Z, alvo, D, nome)
        if r is None:
            print(f"  {nome}: sem dobras validas"); continue
        res.append(r)
        print(f"  {r['nome']:<8}{r['n_oos']:>8}{100*r['taxa_base']:>7.1f}"
              f"{r['auc']:>8.4f}{r['skill']:>+9.4f}{100*r['prec_topo10']:>9.1f}"
              f"   [{r['ic95'][0]:.1f}, {r['ic95'][1]:.1f}]")

    print("\n=== veredito ===")
    for r in res:
        passa = (r["auc"] > 0.52 and r["skill"] > 0
                 and r["ic95"][0] > 100 * r["taxa_base"])
        print(f"  {r['nome']:<8} {'PASSOU' if passa else 'REPROVADO'}", end="")
        if not passa:
            motivos = []
            if r["auc"] <= 0.52:
                motivos.append(f"AUC {r['auc']:.3f}")
            if r["skill"] <= 0:
                motivos.append(f"skill {r['skill']:+.4f}")
            if r["ic95"][0] <= 100 * r["taxa_base"]:
                motivos.append(f"IC95 inclui a taxa-base {100*r['taxa_base']:.1f}")
            print("  (" + "; ".join(motivos) + ")", end="")
        print()
    print("\nIsto mede o canal de DRIVERS. O canal de NOTICIA segue nao medido.")


if __name__ == "__main__":
    main()
