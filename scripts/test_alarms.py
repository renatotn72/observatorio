#!/usr/bin/env python3
"""Exercita o motor de alarmes com sinais forjados, porta por porta.

Nao e teste de mercado: e teste do CAMINHO. Cada caso prova que uma porta
especifica barra ou deixa passar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import alarms, notify                     # noqa: E402
from obs.db import connect                         # noqa: E402


def sig(ticker, p_up, base_up, n_eff, calibrated=1, p_down=0.30, base_down=0.30):
    return {"ticker": ticker, "p_up": p_up, "base_up": base_up, "p_down": p_down,
            "base_down": base_down, "n_eff": n_eff, "z": 0.75, "dispersion": 0.2,
            "calibrated": calibrated, "n_articles": 4,
            "items": [{"title": f"Manchete forjada sobre {ticker}"}]}


CASES = [
    ("vantagem grande, evidencia boa  -> DEVE disparar",
     sig("PETR4", 0.58, 0.33, 6.0), True),
    ("vantagem pequena (4 p.p.)       -> barrado por min_edge",
     sig("VALE3", 0.37, 0.33, 6.0), False),
    ("vantagem boa, evidencia fraca   -> barrado por min_n_eff",
     sig("ITUB4", 0.58, 0.33, 0.4), False),
    ("vantagem boa, NAO calibrado     -> barrado por require_calibrated",
     sig("BBAS3", 0.58, 0.33, 6.0, calibrated=0), False),
    ("MGLU3 regra so 'down', sinal up -> barrado por direction",
     sig("MGLU3", 0.60, 0.33, 6.0), False),
]


def main():
    con = connect()
    with con:
        con.execute("DELETE FROM alarm_events")     # cooldown limpo
    # desliga a porta de novidade: aqui nao ha artigo real por tras
    con.close()
    orig = alarms._has_novelty
    alarms._has_novelty = lambda *a, **k: True

    ok = True
    for desc, s, expected in CASES:
        fired = alarms.evaluate([s])
        got = any(e["direction"] == "up" for e in fired)
        mark = "OK " if got == expected else "FALHOU"
        if got != expected:
            ok = False
        print(f"  [{mark}] {desc}")
        for e in fired:
            notify.deliver([{**e, "channels": ["file"]}])

    # cooldown: repetir o caso 1 nao pode disparar de novo
    again = alarms.evaluate([sig("PETR4", 0.58, 0.33, 6.0)])
    mark = "OK " if not again else "FALHOU"
    if again:
        ok = False
    print(f"  [{mark}] repeticao imediata do mesmo papel -> barrado por cooldown")

    alarms._has_novelty = orig
    # Porta de novidade, agora de verdade. Tem de ser um papel SEM noticia
    # pontuada no banco -- usar PETR4 aqui era erro do teste, nao do motor:
    # PETR4 tem primeira-reportagem real, entao a porta deixa passar e esta certa.
    con = connect()
    with con:
        con.execute("DELETE FROM alarm_events")
    scored = {r[0] for r in con.execute("SELECT DISTINCT ticker FROM scores")}
    con.close()
    from obs.config import tickers as _tk
    quiet = sorted(set(_tk()) - scored)
    if not quiet:
        print("  [PULA] todo papel da watchlist tem noticia; sem caso para a porta de novidade")
    else:
        nov = alarms.evaluate([sig(quiet[0], 0.58, 0.33, 6.0)])
        mark = "OK " if not nov else "FALHOU"
        if nov:
            ok = False
        print(f"  [{mark}] {quiet[0]} sem primeira-reportagem -> barrado por require_novelty")

        # e o contrapositivo: um papel QUE TEM noticia real passa pela porta
        noisy = sorted(scored)
        if noisy:
            con = connect()
            with con:
                con.execute("DELETE FROM alarm_events")
            con.close()
            yes = alarms.evaluate([sig(noisy[0], 0.58, 0.33, 6.0)])
            mark = "OK " if yes else "FALHOU"
            if not yes:
                ok = False
            print(f"  [{mark}] {noisy[0]} COM primeira-reportagem real -> passa pela porta")

    print("\nTODOS OS CASOS PASSARAM" if ok else "\nHA CASOS FALHANDO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
