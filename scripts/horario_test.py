"""O sinal existe no horizonte de HORAS, onde o diario ja perdeu?

MOTIVO: no teste diario o IC do modelo estrutural caiu de 0,157
(contemporaneo) para 0,021 (D+1). Informacao que some em um dia reagiu dentro
do dia. Aqui mede-se a MESMA carteira tematica, barra a barra de 1 hora:

    contemporaneo  driver na hora t  x  carteira na hora t
    defasado       driver na hora t  x  carteira na hora t+1

Se o defasado de 1 HORA tiver IC claramente acima do defasado de 1 DIA, o
sinal vive em horas e o diario estava medindo tarde demais. Se nao tiver, o
mercado fecha o arbitramento dentro da propria hora.

ALINHAMENTO: so barras dentro do pregao da B3, e retorno de barra para barra
descartando buraco maior que 4h -- senao o gap de abertura entra disfarcado
de movimento horario.
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import math                                                   # noqa: E402
import random                                                 # noqa: E402

from obs import config, drivers, intraday, temas              # noqa: E402
from obs.assimetria import _spearman                          # noqa: E402
from obs.db import connect                                    # noqa: E402

PROXY = {"cambio_exportador": ("USDBRL", +1),
         "custo_energia_insumo": ("BRENT", +1),
         "risco_politico": ("USDBRL", +1)}
N_PERM = 500


def acertos(ic):
    return 100 * (0.5 + math.asin(max(-0.999, min(0.999, ic))) / math.pi)


def main(intervalo="1h", rng="2y"):
    alvo = {t: f"{t}.SA" for t in config.tickers()}
    alvo.update({k: drivers.DRIVERS[k][0] for k in ("USDBRL", "BRENT")})
    print(f"Baixando barras de {intervalo} ({rng})...")
    intraday.sync(alvo, intervalo=intervalo, rng=rng)

    con = connect()
    ser = intraday.series(con, intervalo, so_pregao=True)
    con.close()
    rets = {s: intraday.retornos(v) for s, v in ser.items()}
    acoes = {s: r for s, r in rets.items() if s in config.tickers()}
    resid = intraday.residual_transversal(acoes)
    print(f"  {len(resid)} papeis, "
          f"{len({t for v in resid.values() for t in v})} barras alinhadas\n")

    print(f"{'tema':<24}{'defasagem':<12}{'n':>7}{'IC':>9}{'p':>8}{'acertos/100':>13}")
    rnd = random.Random(20261002)
    for nome, (drv, orient) in PROXY.items():
        sinais = dict(temas.alvos(nome))
        if drv not in rets or not sinais:
            print(f"  {nome:<22} proxy {drv} ausente")
            continue
        den = sum(abs(s) for s in sinais.values())
        carimbos = sorted(rets[drv])
        idx = {t: i for i, t in enumerate(carimbos)}
        cart = {}
        for t in {t for v in resid.values() for t in v}:
            num, viu = 0.0, 0
            for tk, s in sinais.items():
                r = resid.get(tk, {}).get(t)
                if r is not None:
                    num += s * r
                    viu += 1
            if viu >= max(2, len(sinais) // 2):
                cart[t] = num / den

        for rotulo, desloc in (("mesma barra", 0), ("proxima barra", 1), ("+2 barras", 2)):
            xs, ys = [], []
            for t in carimbos:
                i = idx[t] + desloc
                if i >= len(carimbos):
                    break
                alvo_t = cart.get(carimbos[i])
                if alvo_t is None:
                    continue
                xs.append(orient * rets[drv][t])
                ys.append(alvo_t)
            if len(xs) < 200:
                print(f"  {nome:<22}{rotulo:<12}{len(xs):>7}  amostra curta")
                continue
            ic = _spearman(xs, ys)
            nulos = []
            for _ in range(N_PERM):
                emb = ys[:]
                rnd.shuffle(emb)
                nulos.append(_spearman(xs, emb))
            p = sum(1 for z in nulos if abs(z) >= abs(ic)) / len(nulos)
            marca = "  SIG" if p < 0.05 else ""
            print(f"  {nome:<22}{rotulo:<12}{len(xs):>7}{ic:>+9.4f}{p:>8.3f}"
                  f"{acertos(ic):>12.1f}{marca}")

    print("\nComparar com o diario: contemporaneo +0,157 / D+1 +0,021.")


if __name__ == "__main__":
    import sys as _s
    main(_s.argv[1] if len(_s.argv) > 1 else "1h",
         _s.argv[2] if len(_s.argv) > 2 else "2y")
