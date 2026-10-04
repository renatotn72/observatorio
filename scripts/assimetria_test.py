"""Beta de baixa persiste? Grade de especificacoes, TODAS reportadas.

Reportar a grade inteira e o ponto. Rodar seis especificacoes e publicar a
melhor e p-hacking: com seis tentativas independentes a p=0.05, a chance de
alguma passar por acaso e ~26%. Entao a leitura correta e a tabela toda, com
o alerta de multiplicidade embaixo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from obs import assimetria as A                              # noqa: E402

GRADE = [
    (252, 21), (252, 63), (252, 126),
    (504, 63), (504, 126), (126, 21),
]

print(f"{'janela':>7}{'horiz':>7}{'cortes':>8}{'IC':>9}{'t':>7}{'p':>8}  veredito")
passaram = 0
for jan, hor in GRADE:
    r = A.teste_persistencia(janela_est=jan, horizonte=hor, n_perm=400)
    if r.get("n_cortes", 0) == 0:
        print(f"{jan:>7}{hor:>7}{'0':>8}   historico insuficiente")
        continue
    t = r["t"] if r["t"] is not None else float("nan")
    passaram += r["veredito"] == "PASSOU"
    print(f"{jan:>7}{hor:>7}{r['n_cortes']:>8}{r['ic_spearman']:>+9.4f}"
          f"{t:>7.2f}{r['p_permutacao']:>8.3f}  {r['veredito']}", flush=True)

print(f"\n{passaram} de {len(GRADE)} especificacoes passaram.")
print("Com 6 testes a 5%, esperar ~0.3 falso positivo. Uma aprovacao isolada "
      "nesta grade NAO e evidencia -- precisaria sobreviver a correcao de "
      "multiplicidade e a uma janela de validacao separada.")
