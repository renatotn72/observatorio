"""NOTICIA -> PRECO: a forca da noticia prevê o movimento dos minutos seguintes?

E o teste da tese do projeto, e ele e diferente de tudo que foi medido antes.
Os testes anteriores eram PRECO -> PRECO (driver se move, acao se move) e
mostraram que o arbitramento fecha em menos de 5 minutos. Este e
NOTICIA -> PRECO: a materia sai as 10h03, o que acontece as 10h04?

DESENHO DE ESTUDO DE EVENTO
Para cada mencao (artigo, papel) com `published_ts` dentro do pregao:
    t0 = barra de 1 minuto imediatamente APOS a publicacao   (nunca a mesma:
         a barra que contem o instante da noticia ja pode conter a reacao)
    retorno acumulado residual em [t0, t0+k] para k = 1, 5, 15, 30, 60 min
`forca` = s * magnitude do scorer (direcao x intensidade). IC de Spearman
entre forca e retorno acumulado.

O RESIDUO E TRANSVERSAL na mesma barra: remove o que moveu a bolsa inteira
naquele minuto, que e o que separa "a noticia moveu o papel" de "o mercado
subiu junto".

AVISO DE AMOSTRA
Com poucas dezenas de eventos nenhum IC aqui significa coisa alguma. O script
imprime n e so chama de resultado acima de MIN_EVENTOS. Abaixo disso, a saida
e descritiva -- serve para ver a maquinaria funcionando e para acompanhar o
acumulo, nao para decidir nada.

COMPARACAO DE LEITORES (2026-10-04)
    python3 scripts/evento_noticia.py --scorer lexicon --scorer llm

Este e o UNICO juiz valido da pergunta "qual leitor de noticia e melhor".
O conjunto-ouro de scripts/ouro_llm.py nao serve para isso, e nao por falta de
amostra: o gabarito dele e feito de palavra-chave, e 93 dos 115 casos vem de
uma regra unica (dividendo|jcp|proventos|recompra) cujos cinco termos ESTAO no
dicionario POS do lexico. Naquela fatia o lexico acerta 98,9 em 100 por
construcao; nas outras oito regras cai para 50,0 -- o chute. Medir leitor
contra gabarito de palavra-chave premia quem le palavra-chave.

Aqui o juiz e o retorno residual realizado. Ele nao sabe quais palavras cada
leitor usa.

DOIS CUIDADOS NO DESENHO DA COMPARACAO
1. MESMAS CELULAS. Cada leitor ve exatamente o mesmo conjunto (papel, minuto),
   senao a diferenca de IC pode ser so diferenca de amostra.
2. FORCA ZERO CONTA. A versao anterior descartava evento com forca 0, e isso
   escondia justamente a cegueira de um leitor: "Petrobras anuncia nova
   descoberta de petroleo" vale 0,00 no lexico (nenhuma palavra do dicionario)
   e +0,60 na leitura estruturada. Descartar o zero apagaria o caso em que os
   dois mais diferem. A celula entra quando ALGUM leitor viu algo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections                                            # noqa: E402
import datetime as dt                                         # noqa: E402
import math                                                   # noqa: E402
import random                                                 # noqa: E402

from obs import intraday                                      # noqa: E402
from obs.assimetria import _spearman                          # noqa: E402
from obs.db import connect                                    # noqa: E402

JANELAS = (1, 5, 15, 30, 60)
MIN_EVENTOS = 120
N_PERM = 1000


def acertos(ic):
    return 100 * (0.5 + math.asin(max(-0.999, min(0.999, ic))) / math.pi)


def _celulas(con, scorer, idx, resid):
    """forca por celula (papel, primeira barra apos a publicacao).

    A forca da celula e a MEDIA das materias dela -- e o que o agregador faria.
    AGREGA POR CELULA porque, MEDIDO, 752 eventos caiam em apenas 108 celulas:
    replicacao media de 7x, com UMA celula concentrando 163. Varias materias do
    mesmo papel no mesmo minuto compartilham o MESMO retorno futuro, entao
    conta-las como independentes infla o n por 7 e encolhe o p-valor pela raiz
    disso. E o mesmo erro das janelas sobrepostas que ja derrubou tres
    resultados neste projeto.
    """
    eventos = con.execute("""
        SELECT a.published_ts ts, m.ticker, sc.s, sc.magnitude, a.title
        FROM scores sc
        JOIN mentions m ON m.article_id=sc.article_id AND m.ticker=sc.ticker
        JOIN articles a ON a.id=sc.article_id
        WHERE m.ticker != '__none__' AND sc.scorer=?
        ORDER BY a.published_ts""", (scorer,)).fetchall()
    cel = collections.defaultdict(list)
    for e in eventos:
        tk = e["ticker"]
        if tk not in idx:
            continue
        ts_list = idx[tk]
        # primeira barra ESTRITAMENTE posterior: a barra corrente pode conter
        # o proprio instante da noticia e ja embutir a reacao
        i = next((j for j, t in enumerate(ts_list) if t > e["ts"]), None)
        if i is None:
            continue
        acum = {}
        for k in JANELAS:
            if i + k - 1 >= len(ts_list):
                continue
            acum[k] = sum(resid[tk][ts_list[j]] for j in range(i, i + k))
        if not acum:
            continue
        forca = (e["s"] or 0.0) * (e["magnitude"] or 0.0)
        cel[(tk, ts_list[i])].append((forca, acum, e["title"]))
    return {ch: {"forca": sum(x[0] for x in it) / len(it), "acum": it[0][1],
                 "titulo": it[0][2], "n": len(it)}
            for ch, it in cel.items()}, len(eventos)


def _mede(nome, cels, chaves, rnd):
    print(f"\n== leitor: {nome} ==")
    print(f"{'janela':<10}{'n':>6}{'IC':>9}{'p':>8}{'acertos/100':>13}  veredito")
    saida = {}
    for k in JANELAS:
        xs = [cels[c]["forca"] for c in chaves if k in cels[c]["acum"]]
        ys = [cels[c]["acum"][k] for c in chaves if k in cels[c]["acum"]]
        if len(xs) < 8:
            print(f"  {k:>3} min{'':<4}{len(xs):>6}   amostra insuficiente")
            continue
        ic = _spearman(xs, ys)
        nulos = []
        for _ in range(N_PERM):
            emb = ys[:]
            rnd.shuffle(emb)
            nulos.append(_spearman(xs, emb))
        pv = sum(1 for z in nulos if abs(z) >= abs(ic)) / len(nulos)
        vd = ("DESCRITIVO (n < %d)" % MIN_EVENTOS if len(xs) < MIN_EVENTOS
              else ("SIG" if pv < 0.05 else "nao significativo"))
        print(f"  {k:>3} min{'':<4}{len(xs):>6}{ic:>+9.4f}{pv:>8.3f}"
              f"{acertos(ic):>12.1f}  {vd}")
        saida[k] = ic
    mudos = sum(1 for c in chaves if abs(cels[c]["forca"]) < 1e-9)
    print(f"  celulas em que este leitor nao viu nada (forca 0): "
          f"{mudos}/{len(chaves)}")
    for k in JANELAS:
        par = [(cels[c]["forca"], cels[c]["acum"][k]) for c in chaves
               if k in cels[c]["acum"] and abs(cels[c]["forca"]) > 1e-9]
        if len(par) < 8:
            continue
        ok = sum(1 for f, r in par if (f > 0) == (r > 0))
        print(f"  concordancia de sinal em {k:>3} min: {ok}/{len(par)} = "
              f"{100*ok/len(par):.1f} em 100")
    return saida


def main(scorers=("lexicon",)):
    con = connect()
    ser = intraday.series(con, "1m", so_pregao=True)
    acoes = {s: v for s, v in ser.items() if not s.startswith(("USD", "BRENT", "DXY"))}
    if not acoes:
        print("sem barras de 1m. Rode: python3 -m obs.cli intraday --intervalo 1m")
        con.close()
        return
    rets = {s: intraday.retornos(v) for s, v in acoes.items()}
    resid = intraday.residual_transversal(rets)
    carimbos = sorted({t for v in resid.values() for t in v})
    print(f"barras de 1m: {len(carimbos)} minutos alinhados, {len(resid)} papeis")
    if carimbos:
        print(f"periodo: {dt.datetime.fromtimestamp(carimbos[0]):%Y-%m-%d %H:%M}"
              f" .. {dt.datetime.fromtimestamp(carimbos[-1]):%Y-%m-%d %H:%M}")

    idx = {s: sorted(v) for s, v in resid.items()}
    porleitor, brutos = {}, {}
    for sc in scorers:
        porleitor[sc], brutos[sc] = _celulas(con, sc, idx, resid)
        print(f"{sc:<10}: {brutos[sc]} mencoes pontuadas -> "
              f"{len(porleitor[sc])} celulas (papel, minuto)")
    con.close()

    vazios = [sc for sc in scorers if not porleitor[sc]]
    if vazios:
        print(f"\nsem evento casado para: {', '.join(vazios)}")
        print("Causas possiveis, em ordem:")
        print("  1. noticia publicada FORA do pregao (a maioria dos feeds)")
        print("  2. barras de 1m so cobrem 5 dias; noticia mais antiga nao casa")
        print("  3. este leitor ainda nao pontuou (python3 -m obs.cli score"
              " --scorer <leitor>)")
        if len(vazios) == len(scorers):
            return

    presentes = [sc for sc in scorers if porleitor[sc]]
    # MESMAS CELULAS para todos: a intersecao. Celula onde NENHUM leitor viu
    # nada nao entra -- ela nao distingue ninguem.
    chaves = set.intersection(*(set(porleitor[sc]) for sc in presentes))
    chaves = sorted(c for c in chaves
                    if any(abs(porleitor[sc][c]["forca"]) > 1e-9 for sc in presentes))
    print(f"\ncelulas comparaveis (intersecao, algum leitor com forca != 0): "
          f"{len(chaves)}")
    if not chaves:
        return

    rnd = random.Random(20261002)
    ics = {sc: _mede(sc, porleitor[sc], chaves, rnd) for sc in presentes}

    if len(presentes) > 1:
        print("\n== diferenca de IC, mesmas celulas ==")
        print(f"{'janela':<10}" + "".join(f"{sc:>12}" for sc in presentes) + "   delta")
        base = presentes[0]
        for k in JANELAS:
            if any(k not in ics[sc] for sc in presentes):
                continue
            linha = f"  {k:>3} min{'':<4}" + "".join(f"{ics[sc][k]:>+12.4f}"
                                                     for sc in presentes)
            print(linha + f"{ics[presentes[-1]][k] - ics[base][k]:>+9.4f}")
        print("\nLer com cuidado: IC maior aqui NAO libera o leitor como sinal.")
        print("As portas de docs/validacao.md continuam valendo -- corte")
        print("temporal, embargo, ganho sobre preco/drivers e permutacao.")
        print("Com n abaixo de %d a tabela acima e descritiva." % MIN_EVENTOS)


if __name__ == "__main__":
    args = sys.argv[1:]
    escolhidos = [args[i + 1] for i, a in enumerate(args)
                  if a == "--scorer" and i + 1 < len(args)]
    main(tuple(escolhidos) if escolhidos else ("lexicon",))
