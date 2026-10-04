#!/usr/bin/env python3
"""Analise de poder: quantos eventos para DETECTAR um sinal desse tamanho?

Responde a pergunta que vem antes de "o modelo funciona?": se o sinal
existir, voce consegue prova-lo com a quantidade de dados que tem?

Simula n pares (sinal, retorno anormal) com um IC verdadeiro conhecido,
mede o IC amostral e testa contra zero. Repete e conta a fracao de vezes em
que o teste rejeita -- isso e o poder.
"""
from __future__ import annotations
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest import spearman                      # noqa: E402

TRIALS = 400
ALPHA = 0.05


def simulate(n: int, true_ic: float, rng: random.Random) -> float:
    """Gera n pares com correlacao ~true_ic e devolve o IC de Spearman medido."""
    zs, cars = [], []
    rho = true_ic
    for _ in range(n):
        z = rng.gauss(0, 1)
        e = rng.gauss(0, 1)
        car = rho * z + math.sqrt(max(0.0, 1 - rho * rho)) * e
        zs.append(z); cars.append(car)
    return spearman(zs, cars)


def power(n: int, true_ic: float, rng: random.Random) -> float:
    """Fracao de simulacoes em que o IC medido e significativo e do sinal certo."""
    crit = 1.959964 / math.sqrt(n - 1)        # ~SE do Spearman sob H0
    hits = 0
    for _ in range(TRIALS):
        ic = simulate(n, true_ic, rng)
        if ic > crit:
            hits += 1
    return hits / TRIALS


def n_for_power(true_ic: float, target: float = 0.80) -> int:
    """Formula de Fisher: n ~ ((z_alpha + z_beta)/atanh(r))^2 + 3."""
    za, zb = 1.644854, 0.841621               # unicaudal 5%, poder 80%
    r = atanh(true_ic)
    return int(math.ceil(((za + zb) / r) ** 2 + 3))


def atanh(r: float) -> float:
    return 0.5 * math.log((1 + r) / (1 - r))


def main():
    rng = random.Random(42)
    print("QUANTOS EVENTOS PARA PROVAR QUE O SINAL EXISTE")
    print("(teste unicaudal, alpha 5%, poder 80%)\n")
    print(f"{'IC verdadeiro':>14} {'n necessario':>13} {'papeis x dias':>26}")
    for ic in (0.02, 0.03, 0.05, 0.08, 0.12):
        n = n_for_power(ic)
        # ~0.6 noticia pontuada por papel por pregao, estimativa otimista
        dias_10 = n / (10 * 0.6)
        dias_100 = n / (100 * 0.6)
        print(f"{ic:>14.2f} {n:>13,} {f'10 papeis: {dias_10:,.0f} pregoes':>26}")
        print(f"{'':>14} {'':>13} {f'100 papeis: {dias_100:,.0f} pregoes':>26}")

    print("\n\nPODER REAL COM O QUE VOCE TERIA EM 1 ANO")
    print("(10 papeis x ~250 pregoes x 0.6 = ~1.500 eventos)\n")
    print(f"{'IC verdadeiro':>14} {'n=1.500':>10} {'n=5.000':>10} {'n=15.000':>10}")
    for ic in (0.02, 0.03, 0.05, 0.08):
        row = f"{ic:>14.2f}"
        for n in (1500, 5000, 15000):
            row += f"{power(n, ic, rng):>10.0%}"
        print(row)

    print("\n\nLEI FUNDAMENTAL DA GESTAO ATIVA:  IR ~ IC x raiz(amplitude)")
    print("\nAMPLITUDE NAO E NUMERO DE EVENTOS. Contar 1.500 noticias em 10 blue")
    print("chips como 1.500 apostas independentes e o erro classico no uso desta")
    print("lei -- essas acoes andam juntas. Correcao por correlacao media rho:")
    print("    N_efetivo = N / (1 + (N-1) * rho)")
    print("Blue chips da B3 tem rho tipico ~0.55 entre si.\n")

    RHO = 0.55
    EV_DIA = 0.6
    print(f"{'papeis':>7} {'N_efetivo':>11} {'amplitude/ano':>15}")
    for n_papeis in (10, 50, 200):
        n_eff = n_papeis / (1 + (n_papeis - 1) * RHO)
        # noticias repetidas sobre o mesmo papel em dias proximos tambem nao sao
        # independentes; 1 aposta efetiva por papel-dia e o teto realista
        breadth = n_eff * 250 * min(1.0, EV_DIA)
        print(f"{n_papeis:>7} {n_eff:>11.2f} {breadth:>15,.0f}")

    print(f"\n{'IC':>6} {'10 papeis':>12} {'50 papeis':>12} {'200 papeis':>12}   [IR anual]")
    for ic in (0.02, 0.03, 0.05, 0.08):
        row = f"{ic:>6.2f}"
        for n_papeis in (10, 50, 200):
            n_eff = n_papeis / (1 + (n_papeis - 1) * RHO)
            breadth = n_eff * 250 * min(1.0, EV_DIA)
            row += f"{ic * math.sqrt(breadth):>12.2f}"
        print(row)
    print("\n[IR abaixo de ~0.5 e indistinguivel de sorte na pratica;")
    print(" acima de 1.0 e bom; e isso TUDO e BRUTO, antes de custo de transacao.]")
    print("\nRepare que aumentar de 10 para 200 papeis multiplica a amplitude por")
    print("~4, nao por 20: a correlacao come quase todo o ganho de diversificacao.")


if __name__ == "__main__":
    main()
