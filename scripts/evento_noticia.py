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
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
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


def main():
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

    eventos = con.execute("""
        SELECT a.published_ts ts, m.ticker, sc.s, sc.magnitude, a.title
        FROM scores sc
        JOIN mentions m ON m.article_id=sc.article_id AND m.ticker=sc.ticker
        JOIN articles a ON a.id=sc.article_id
        WHERE m.ticker != '__none__' AND sc.scorer='lexicon'
        ORDER BY a.published_ts""").fetchall()
    con.close()
    print(f"menções pontuadas no banco: {len(eventos)}")

    # indice por papel para achar a primeira barra apos a publicacao
    idx = {s: sorted(v) for s, v in resid.items()}
    linhas = []
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
        forca = (e["s"] or 0.0) * (e["magnitude"] or 0.0)
        if forca == 0:
            continue
        acum = {}
        for k in JANELAS:
            if i + k - 1 >= len(ts_list):
                continue
            soma = sum(resid[tk][ts_list[j]] for j in range(i, i + k))
            acum[k] = soma
        if acum:
            linhas.append((forca, acum, tk, e["title"], (tk, ts_list[i])))

    # AGREGA POR CELULA (papel, barra). MEDIDO: 752 eventos caiam em apenas 108
    # celulas -- replicacao media de 7x, com UMA celula concentrando 163. Varias
    # materias do mesmo papel no mesmo minuto compartilham o MESMO retorno
    # futuro, entao conta-las como independentes infla o n por 7 e encolhe o
    # p-valor pela raiz disso. E o mesmo erro das janelas sobrepostas que ja
    # derrubou tres resultados neste projeto.
    # A forca da celula e a MEDIA das materias dela: e o que o agregador faria.
    import collections as _c
    cel = _c.defaultdict(list)
    for f, a_, tk, ti, chave in linhas:
        cel[chave].append((f, a_, tk, ti))
    linhas = []
    for chave, itens in cel.items():
        f_med = sum(x[0] for x in itens) / len(itens)
        linhas.append((f_med, itens[0][1], itens[0][2], itens[0][3]))
    print(f"eventos: {sum(len(v) for v in cel.values())} -> "
          f"{len(linhas)} celulas independentes (papel, minuto)")
    if not linhas:
        print("\nNenhum evento casou. Causas possiveis, em ordem:")
        print("  1. noticia publicada FORA do pregao (a maioria dos feeds)")
        print("  2. barras de 1m so cobrem 5 dias; noticia mais antiga nao casa")
        print("  3. poucos papeis com mencao pontuada")
        return

    print(f"\n{'janela':<10}{'n':>6}{'IC':>9}{'p':>8}{'acertos/100':>13}  veredito")
    rnd = random.Random(20261002)
    for k in JANELAS:
        xs = [f for f, a, _t, _ti in linhas if k in a]
        ys = [a[k] for _f, a, _t, _ti in linhas if k in a]
        if len(xs) < 8:
            print(f"  {k:>3} min{'':<4}{len(xs):>6}   amostra insuficiente")
            continue
        ic = _spearman(xs, ys)
        nulos = []
        for _ in range(N_PERM):
            emb = ys[:]
            rnd.shuffle(emb)
            nulos.append(_spearman(xs, emb))
        p = sum(1 for z in nulos if abs(z) >= abs(ic)) / len(nulos)
        vd = ("DESCRITIVO (n < %d)" % MIN_EVENTOS if len(xs) < MIN_EVENTOS
              else ("SIG" if p < 0.05 else "nao significativo"))
        print(f"  {k:>3} min{'':<4}{len(xs):>6}{ic:>+9.4f}{p:>8.3f}"
              f"{acertos(ic):>12.1f}  {vd}")

    print(f"\nconcordancia de sinal (forca e retorno no mesmo lado):")
    for k in JANELAS:
        par = [(f, a[k]) for f, a, _t, _ti in linhas if k in a]
        if len(par) < 8:
            continue
        ok = sum(1 for f, r in par if (f > 0) == (r > 0))
        print(f"  {k:>3} min  {ok}/{len(par)} = {100*ok/len(par):.1f} em 100")


if __name__ == "__main__":
    main()
