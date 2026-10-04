"""Os sinais escritos a mao em obs/temas.py tem conteudo? Teste sem noticia.

A IDEIA
Nao da para medir o canal de noticia hoje (0 rotulos, GDELT bloqueado). Mas a
parte que mais importa do modelo estrutural nao e a NOTICIA -- e o SINAL. Se
"exportador se beneficia de dolar alto" for falso, a camada inteira esta
errada, e isso da para testar com 10 anos de preco, sem uma manchete sequer.

COMO
Para o tema T com sinais s_i, monta-se a carteira tematica no dia t:
    P_t = soma(s_i * r_i,t) / soma(|s_i|)
onde r e o retorno ANORMAL (residuo transversal). Depois compara com o
retorno do driver que serve de proxy do tema.

DOIS TESTES DIFERENTES, E A DISTINCAO E O PONTO
  1. CONTEMPORANEO  P_t contra d_t.  Responde "meu sinal esta certo sobre a
     economia?". Nao e negociavel: no fim do dia t voce ja sabia os dois.
  2. DEFASADO       P_t+1 contra d_t. Responde "da para ganhar dinheiro?".
     E o unico que vale como sinal.
Um tema pode passar no 1 e falhar no 2 -- isso significa que o modelo descreve
certo e o mercado ja precificou. E o resultado mais provavel, e e informacao
util: valida a estrutura para EXPLICAR, nao para prever.

NULO POR PERMUTACAO: embaralha os sinais entre os papeis, preservando quantos
sao + e quantos sao -. Se o IC sobreviver a isso, nao era o sinal que
importava.
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import math                                                   # noqa: E402
import random                                                 # noqa: E402
import statistics as st                                       # noqa: E402

from obs import drivers, temas                                # noqa: E402
from obs.assimetria import _spearman                          # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.label import abnormal_returns                        # noqa: E402

# Proxy diario de cada tema. So entra tema que TEM proxy -- os demais ficam
# sem veredito, que e melhor que veredito inventado.
PROXY = {
    "cambio_exportador": ("USDBRL", +1),
    "custo_energia_insumo": ("BRENT", +1),
    "risco_politico": ("USDBRL", +1),
}
SEM_PROXY_NOTA = ("sem serie diaria que sirva de proxy; so sera testavel pelo "
                  "proprio fluxo de noticia")
N_PERM = 1000


def carteira(ab, sinais, datas):
    """Retorno diario da carteira tematica (long +1, short -1)."""
    out = {}
    den = sum(abs(s) for s in sinais.values())
    if den == 0:
        return out
    for d in datas:
        num, viu = 0.0, 0
        for tkr, s in sinais.items():
            r = ab.get(tkr, {}).get(d)
            if r is not None:
                num += s * r
                viu += 1
        if viu >= max(2, len(sinais) // 2):
            out[d] = num / den
    return out


def testa(nome, ab, dret, defasado):
    sinais = dict(temas.alvos(nome))
    if not sinais or nome not in PROXY:
        return None
    drv, orient = PROXY[nome]
    if drv not in dret:
        return None
    datas = sorted(set(dret[drv]) & {d for t in ab for d in ab[t]})
    if len(datas) < 200:
        return None
    cart = carteira(ab, sinais, datas)
    xs, ys = [], []
    for i, d in enumerate(datas):
        if defasado:
            if i + 1 >= len(datas):
                break
            alvo = cart.get(datas[i + 1])
        else:
            alvo = cart.get(d)
        if alvo is None:
            continue
        xs.append(orient * dret[drv][d])
        ys.append(alvo)
    if len(xs) < 200:
        return None
    ic = _spearman(xs, ys)
    rnd = random.Random(20261002)

    # NULO 1 -- EMBARALHA AS DATAS. Quebra o alinhamento temporal entre o
    # driver e a carteira, preservando as duas distribuicoes. Responde "essa
    # correlacao e real ou e acaso?". E o nulo primario porque funciona para
    # qualquer tema.
    nulos_t = []
    for _ in range(N_PERM):
        emb = ys[:]
        rnd.shuffle(emb)
        nulos_t.append(_spearman(xs, emb))
    p_tempo = sum(1 for z in nulos_t if abs(z) >= abs(ic)) / len(nulos_t)

    # NULO 2 -- EMBARALHA OS SINAIS entre os papeis. Responde a pergunta mais
    # afiada: "minha atribuicao de sinal bate uma aleatoria?". So vale quando o
    # tema TEM sinais diferentes; com todos iguais, permutar nao muda nada e o
    # p sai 1.000 por construcao -- foi o que apareceu em custo_energia_insumo
    # e risco_politico na primeira rodada, e nao era resultado, era degeneracao.
    vals = list(sinais.values())
    p_sinal = None
    if len(set(vals)) > 1:
        tks = list(sinais)
        nulos_s = []
        for _ in range(N_PERM):
            emb = vals[:]
            rnd.shuffle(emb)
            c2 = carteira(ab, dict(zip(tks, emb)), datas)
            x2, y2 = [], []
            for i, d in enumerate(datas):
                if defasado and i + 1 >= len(datas):
                    break
                a = c2.get(datas[i + 1]) if defasado else c2.get(d)
                if a is None:
                    continue
                x2.append(orient * dret[drv][d])
                y2.append(a)
            if len(x2) >= 200:
                nulos_s.append(_spearman(x2, y2))
        if nulos_s:
            p_sinal = sum(1 for z in nulos_s if abs(z) >= abs(ic)) / len(nulos_s)
    p = p_tempo
    acerto = 100 * (0.5 + math.asin(max(-0.999, min(0.999, ic))) / math.pi)
    return {"ic": ic, "p": p, "p_sinal": p_sinal, "n": len(xs),
            "acerto": acerto, "proxy": drv, "n_papeis": len(sinais)}


def main():
    con = connect()
    ab = abnormal_returns(con)
    dret = drivers.driver_returns(con)
    con.close()

    for defasado, titulo in ((False, "1. CONTEMPORANEO -- o sinal descreve certo?"),
                             (True, "2. DEFASADO (D+1) -- o sinal PREVE?")):
        print(f"\n=== {titulo} ===")
        print(f"{'tema':<26}{'proxy':<9}{'n':>6}{'IC':>9}{'p_tempo':>9}"
              f"{'p_sinal':>9}{'acerto/100':>12}")
        for nome in temas.TEMAS:
            r = testa(nome, ab, dret, defasado)
            if r is None:
                if not defasado:
                    print(f"  {nome:<24}{'--':<9}{'':>6}{'':>9}{'':>8}  {SEM_PROXY_NOTA[:28]}")
                continue
            marca = "  SIG" if r["p"] < 0.05 else ""
            ps = f"{r['p_sinal']:.3f}" if r["p_sinal"] is not None else "n/a"
            print(f"  {nome:<24}{r['proxy']:<9}{r['n']:>6}{r['ic']:>+9.4f}"
                  f"{r['p']:>9.3f}{ps:>9}{r['acerto']:>11.1f}{marca}")

    print("\nLeitura: passar no 1 e falhar no 2 significa que o modelo acerta a")
    print("economia e o mercado ja precificou -- serve para EXPLICAR, nao prever.")


if __name__ == "__main__":
    main()
