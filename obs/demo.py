"""Popula dados SINTETICOS para provar o encanamento ponta a ponta.

Existe porque calibrar de verdade exige meses de historico. O demo gera
sinais e retornos anormais com uma relacao CONHECIDA (ruidosa, fraca, do
tamanho que se ve na vida real), roda a calibracao e acende o painel.

NADA aqui e dado de mercado. `python3 -m obs.cli demo` escreve na tabela
`signals`/`labels` com asof no passado e ticker real -- limpe com
`rm data/observatorio.db` antes de usar dados reais a serio.
"""
from __future__ import annotations
import random

from . import db
from .config import tickers
from .db import connect
from .util import now_ts

TRUE_EDGE = 0.22       # forca da relacao sinal->retorno (fraca, de proposito)


def seed(n_days: int = 400, seed_val: int = 11) -> None:
    rng = random.Random(seed_val)
    db.init()
    con = connect()
    tkrs = list(tickers())
    base_ts = now_ts() - n_days * 86400
    n = 0
    with con:
        con.execute("DELETE FROM signals")
        con.execute("DELETE FROM labels")
        for d in range(n_days):
            for tkr in tkrs:
                if rng.random() < 0.45:          # nem todo papel tem noticia todo dia
                    continue
                ts = base_ts + d * 86400 + 43200
                z = max(-1.0, min(1.0, rng.gauss(0, 0.45)))
                n_eff = round(abs(rng.gauss(2.5, 1.6)) + 0.2, 3)
                disp = round(abs(rng.gauss(0.3, 0.15)), 3)

                # retorno anormal = componente ligado ao sinal + muito ruido
                sigma = 0.018
                car = TRUE_EDGE * z * sigma * (n_eff / (n_eff + 2.0)) + rng.gauss(0, sigma)
                cls = 1 if car > 0.5 * sigma else (-1 if car < -0.5 * sigma else 0)

                con.execute("""INSERT OR REPLACE INTO signals
                    (ticker,asof_ts,z,n_eff,dispersion,p_up,p_flat,p_down,
                     base_up,base_flat,base_down,calibrated,n_articles)
                    VALUES (?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,0,?)""",
                    (tkr, ts, round(z, 4), n_eff, disp, rng.randint(1, 9)))
                con.execute("""INSERT OR REPLACE INTO labels
                    (ticker,asof_ts,horizon,car,sigma,cls) VALUES (?,?,?,?,?,?)""",
                    (tkr, ts, "1d", round(car, 6), sigma, cls))
                n += 1
    con.close()
    print(f"demo: {n} pares (sinal, rotulo) sinteticos gerados em {n_days} dias")
    print(f"      relacao verdadeira embutida: TRUE_EDGE={TRUE_EDGE} (fraca, realista)")
