#!/usr/bin/env python3
"""70% de acerto direcional: o que exigiria, e onde isso existe.

Duas contas:
  A) Que IC um acerto de 70% implica, contra o que medimos.
  B) Se, com o IC que temos, da para chegar a 70% SELECIONANDO so os sinais
     mais extremos -- e com que frequencia isso aconteceria.

(B) e a pergunta honesta: acerto condicional sobe com a forca do sinal, e
sempre se pode trocar frequencia por acerto. O que decide se isso e um
sistema ou uma curiosidade e quantas vezes por ano acontece.
"""
from __future__ import annotations
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.signal_value import inv_phi, phi, spearman_to_pearson   # noqa: E402

IC_HOJE = 0.0808          # medido, Fama-MacBeth t = -3.81
IC_TUDO = 0.0914          # projetado com tudo implementado
EVENTOS_ANO = 300 * 250   # 300 papeis x 250 pregoes, universo ja ampliado


def ic_para_acerto(hit: float) -> float:
    return math.sin(math.pi * (hit - 0.5))


def acerto_dado_z(ic: float, z: float) -> float:
    """P(acertar o sinal | sinal padronizado z), normal bivariada."""
    rho = spearman_to_pearson(ic)
    return phi(rho * abs(z) / math.sqrt(max(1e-12, 1 - rho * rho)))


def z_para_acerto(ic: float, alvo: float) -> float:
    """Qual |z| entrega esse acerto condicional."""
    rho = spearman_to_pearson(ic)
    return inv_phi(alvo) * math.sqrt(1 - rho * rho) / rho


print("A) O QUE 70% EXIGE")
print("=" * 66)
for h in (0.55, 0.60, 0.65, 0.70, 0.80):
    ic = ic_para_acerto(h)
    print(f"  acerto {h:.0%}  ->  IC = {ic:.3f}   "
          f"({ic / IC_HOJE:>5.1f}x o que medimos)")
print(f"\n  medido hoje: IC = {IC_HOJE:.4f}  ->  acerto {50 + 100*(acerto_dado_z(IC_HOJE, 0.7979)-0.5):.1f}%"
      .replace("acerto", "acerto medio"))

print("\n\nB) DA PARA CHEGAR A 70% SELECIONANDO SO OS EXTREMOS?")
print("=" * 66)
print(f"{'acerto alvo':>12} {'|z| exigido':>12} {'freq. do sinal':>16} {'eventos/ano':>13}")
print("-" * 66)
for alvo in (0.55, 0.60, 0.65, 0.70):
    z = z_para_acerto(IC_TUDO, alvo)
    freq = 2 * (1 - phi(z))            # duas caudas
    n = freq * EVENTOS_ANO
    freq_txt = f"{freq:.2e}" if freq < 1e-4 else f"{100*freq:.3f}%"
    n_txt = f"{n:.1f}" if n >= 0.1 else f"{n:.2e}"
    print(f"{alvo:>11.0%} {z:>12.2f} {freq_txt:>16} {n_txt:>13}")

print(f"\n  (universo de 300 papeis x 250 pregoes = {EVENTOS_ANO:,} eventos/ano)")
print("  |z| e o sinal padronizado: |z|>3 ja e 1 em 370; |z|>6, 1 em 500 milhoes.")

print("\n\nC) ONDE 70%+ EXISTE DE VERDADE (outros alvos)")
print("=" * 66)
for alvo, acc, nota in [
    ("Volatilidade alta amanha?", "70-80%", "vol e persistente; R2 alto e rotina"),
    ("Esta noticia e material?",  "85-90%", "classificacao de texto, nao previsao"),
    ("Direcao do gap dado o ADR", "75-85%", "quase mecanico -- e ja precificado"),
    ("Direcao da acao em D+1",    "52-53%", "o que voce esta perguntando"),
]:
    print(f"  {alvo:<28} {acc:>8}   {nota}")
