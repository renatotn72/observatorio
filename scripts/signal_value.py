#!/usr/bin/env python3
"""IC -> P(alta | sinal). Quanto vale, em probabilidade, o sinal que temos?

Modelo: sinal z e retorno latente r sao normais padrao com correlacao rho.
A classe ALTA e r > k, com k escolhido para bater a taxa-base observada.
Entao, dado um sinal z:
    P(alta | z) = 1 - Phi( (k - rho*z) / sqrt(1 - rho^2) )

rho vem do IC medido (Spearman -> Pearson: rho ~ 2*sin(pi*IC/6)).
"""
from __future__ import annotations
import math

BASE_UP = 0.33          # taxa-base de alta anormal observada no projeto
IC_MEDIDO = 0.0253      # HSI -> residuo transversal do gap (unico limpo)
N = 7506


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def inv_phi(p: float) -> float:
    """Aproximacao de Acklam, precisao ~1e-9."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def spearman_to_pearson(ic: float) -> float:
    return 2 * math.sin(math.pi * ic / 6)


def p_up_given_z(z: float, ic: float, base: float = BASE_UP) -> float:
    rho = spearman_to_pearson(ic)
    k = inv_phi(1 - base)
    return 1 - phi((k - rho * z) / math.sqrt(max(1e-12, 1 - rho * rho)))


def mean_z_of_top(frac: float) -> float:
    """E[z | z no topo de `frac`] = phi_densidade(q)/frac."""
    q = inv_phi(1 - frac)
    return math.exp(-q * q / 2) / math.sqrt(2 * math.pi) / frac


def main():
    se = 1 / math.sqrt(N)
    lo, hi = IC_MEDIDO - 1.96 * se, IC_MEDIDO + 1.96 * se
    print(f"IC medido      : {IC_MEDIDO:+.4f}   (n={N:,})")
    print(f"IC 95% IC      : [{lo:+.4f}, {hi:+.4f}]   <- repare que quase toca zero")
    print(f"Taxa-base alta : {BASE_UP:.1%}\n")

    print("P(ALTA | sinal), por forca do sinal, com o IC que medimos")
    print("=" * 66)
    print(f"{'sinal':<22} {'P(alta)':>9} {'ganho':>8} {'[IC baixo':>11} {'IC alto]':>10}")
    print("-" * 66)
    for label, frac in [("top 50% (acima da media)", 0.50), ("top 20%", 0.20),
                        ("top 10%", 0.10), ("top 5%", 0.05), ("top 1% (extremo)", 0.01)]:
        z = mean_z_of_top(frac)
        p = p_up_given_z(z, IC_MEDIDO)
        p_lo = p_up_given_z(z, lo)
        p_hi = p_up_given_z(z, hi)
        print(f"{label:<22} {p:>8.1%} {p-BASE_UP:>+8.1%} {p_lo:>11.1%} {p_hi:>10.1%}")

    print("\n\nE SE o pipeline de NOTICIAS entregasse ICs maiores?")
    print("=" * 66)
    print(f"{'IC':>8} {'P(alta|top 10%)':>17} {'ganho':>9} {'P(alta|top 1%)':>16}")
    print("-" * 66)
    z10, z01 = mean_z_of_top(0.10), mean_z_of_top(0.01)
    for ic in (0.025, 0.05, 0.10, 0.20, 0.40):
        p10 = p_up_given_z(z10, ic)
        p01 = p_up_given_z(z01, ic)
        print(f"{ic:>8.3f} {p10:>17.1%} {p10-BASE_UP:>+9.1%} {p01:>16.1%}")

    print("\n[IC de 0.20+ em retorno de acao nao existe fora de fraude ou vazamento.")
    print(" A faixa realista para sinal de noticia e 0.02 a 0.06.]")


if __name__ == "__main__":
    main()
