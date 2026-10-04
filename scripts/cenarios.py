#!/usr/bin/env python3
"""Se implementarmos TUDO: quantas vezes em 100 a previsao acerta?

Nao ha numero unico honesto -- o canal de noticias nunca foi medido. Entao:
cenarios com probabilidade atribuida, e a media ponderada no fim.

Como os canais se somam: dois sinais aproximadamente independentes combinam
por raiz da soma dos quadrados.  IC_total ~ sqrt(IC_preco^2 + IC_noticia^2)
"""
from __future__ import annotations
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.signal_value import p_up_given_z, mean_z_of_top, BASE_UP   # noqa: E402

IC_PRECO = 0.0253          # medido: HSI -> residuo transversal do gap


def hit(ic: float) -> float:
    return 0.5 + math.asin(min(0.999, ic)) / math.pi


# (nome, P(cenario), IC do canal de NOTICIAS apos implementar tudo)
CEN = [
    ("Falha: noticia nao agrega", 0.35, 0.000),
    ("Modesto",                   0.40, 0.045),
    ("Bom",                       0.20, 0.070),
    ("Excelente",                 0.05, 0.110),
]

z10 = mean_z_of_top(0.10)
z01 = mean_z_of_top(0.01)

print("PREMISSA: implementado corpo da noticia + extrator LLM + pesos de fonte")
print("aprendidos + universo de 150-300 papeis.\n")
print(f"IC do canal de PRECO ja medido: {IC_PRECO:.4f}\n")
print("=" * 78)
print(f"{'cenario':<28} {'P':>5} {'IC_not':>7} {'IC_tot':>8} {'acerto':>8} {'P(alta|top10%)':>15}")
print("-" * 78)

esp_hit = esp_ic = esp_p10 = 0.0
for nome, p, ic_n in CEN:
    ic_t = math.sqrt(IC_PRECO ** 2 + ic_n ** 2)
    h = hit(ic_t)
    p10 = p_up_given_z(z10, ic_t)
    esp_hit += p * h; esp_ic += p * ic_t; esp_p10 += p * p10
    print(f"{nome:<28} {p:>5.0%} {ic_n:>7.3f} {ic_t:>8.4f} {h:>7.1%} {p10:>15.1%}")

print("-" * 78)
print(f"{'MEDIA PONDERADA':<28} {'':<5} {'':>7} {esp_ic:>8.4f} {esp_hit:>7.1%} {esp_p10:>15.1%}")

print("\n\nEM 100 PREVISOES DE DIRECAO (alta vs queda, ignorando neutro)")
print("=" * 78)
for nome, p, ic_n in CEN:
    ic_t = math.sqrt(IC_PRECO ** 2 + ic_n ** 2)
    h = hit(ic_t)
    print(f"  {nome:<28} {100*h:>5.1f} acertos  (vantagem de {100*h-50:>+4.1f} sobre a moeda)")
print(f"  {'--> esperado':<28} {100*esp_hit:>5.1f} acertos  (vantagem de {100*esp_hit-50:>+4.1f})")

print("\n\nSINAL FORTE (top 1% do dia) NO CENARIO 'BOM'")
print("=" * 78)
ic_bom = math.sqrt(IC_PRECO ** 2 + 0.070 ** 2)
print(f"  P(alta | top 1%)  = {p_up_given_z(z01, ic_bom):.1%}   contra taxa-base de {BASE_UP:.0%}")
print(f"  acerto direcional = {hit(ic_bom):.1%}   -> {100*hit(ic_bom):.0f} em 100")
