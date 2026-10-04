#!/usr/bin/env python3
"""TIPO de evento x retorno: judicial, legislativo e calendario acertam quanto?

A PERGUNTA, do jeito que foi pedida
  Quanto cada TIPO de evento acerta na DIRECAO do papel, e -- em separado --
  quanto ele explica a VOLATILIDADE, em cada granularidade de tempo. Em
  acertos por 100, sem jargao.

A RESPOSTA CURTA, ANTES DA TABELA: NAO DA PARA MEDIR AINDA.
Nao e evasiva, e aritmetica, e esta neste arquivo justamente para nao ser
esquecida. O arquivo de noticias classificadas tem:

    corporativo  611        <- da para medir
    macro        138        <- da, no limite
    judicial      16        <- NAO da
    legislativo    6        <- NAO da
    calendario     6        <- NAO da

E pior do que parece, porque 16 materias nao sao 16 observacoes. Materias do
mesmo papel na mesma barra compartilham o mesmo retorno futuro e viram UMA
celula (foi assim que 752 eventos viraram 108 celulas em
scripts/evento_noticia.py). As 16 judiciais sao 11 do PETR4, 4 do VALE3, 2 do
B3SA3 e 1 do BBAS3, espalhadas por meses -- na pratica, uma dezena de celulas
por horizonte, e menos ainda com janela disjunta.

POR QUE EU MOSTRO O NUMERO DE QUALQUER FORMA
Porque "nao da para medir" tem de ser VERIFICAVEL. A tabela sai com o n real e
com o intervalo de confianca, e e o intervalo que denuncia: com 10 celulas, o
IC95 de qualquer taxa de acerto cobre de ~20% a ~80%. Um "acertou 70 em 100"
calculado em 10 casos e compativel com uma moeda honesta, e tambem com um
sinal otimo. A medicao nao distingue as duas coisas -- e e exatamente isso que
o numero sozinho esconde.

QUANTO FALTA, EM MATERIAS
`amostra_necessaria()` calcula. Para detectar uma vantagem de 5 pontos sobre o
chute (55 em 100 contra 50) com 80% de poder, sao ~780 celulas. Para 10 pontos
(60 contra 50), ~200 celulas. Com a taxa atual de materias judiciais por
celula, isso e da ordem de 1.000 a 4.000 materias judiciais -- duas ordens de
grandeza acima das 16. O caminho nao e refinar a estatistica, e o ponto 6
(radar judicial: fonte dedicada em vez de depender de a imprensa noticiar).

O QUE JA DA PARA DIZER HOJE, e esta na secao AUDITORIA
Com 16 casos nao da para medir acerto, mas da para LER os 16 e conferir se o
sinal aponta para o lado certo. Isso nao e estatistica, e revisao -- e acha
defeito que estatistica nenhuma acharia com n=16.

USO
    python3 scripts/tipo_evento_test.py             # tudo
    python3 scripts/tipo_evento_test.py --simples   # so acertos em 100
    python3 scripts/tipo_evento_test.py --auditoria # so a leitura dos casos
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import config                                       # noqa: E402
from obs.db import connect                                   # noqa: E402

from orientacao_test import (                                # noqa: E402
    FDR_Q, HORIZONTES, MIN_N, ORDEM_GRAN, SEMENTE,
    base_direcional, bh, celulas, mede, rotulo_gran, series_diaria,
    series_intra)

# Os tipos pedidos primeiro; os dois que ja tem massa entram como REFERENCIA,
# para a comparacao ser possivel em vez de o leitor ter de confiar na palavra
# "pouco".
TIPOS = ("judicial", "legislativo", "calendario", "macro", "corporativo")
PEDIDOS = ("judicial", "legislativo", "calendario")


# --------------------------------------------------------------- amostra ----
def amostra_necessaria(vantagem_pp: float, poder: float = 0.80,
                       alfa: float = 0.05) -> int:
    """Quantas CELULAS para detectar `vantagem_pp` pontos acima de 50.

    Teste de uma proporcao contra 0,5, bilateral. Formula fechada, nao
    simulacao: n = ((z_a/2 * sqrt(0,25) + z_b * sqrt(p(1-p))) / (p - 0,5))^2.
    Serve para responder "falta quanto?" com numero, em vez de "falta mais".
    """
    p = 0.5 + vantagem_pp / 100.0
    za, zb = 1.959964, 0.8416212 if poder == 0.80 else 1.281552
    num = za * math.sqrt(0.25) + zb * math.sqrt(p * (1 - p))
    return int(math.ceil((num / (p - 0.5)) ** 2))


# ------------------------------------------------------------------ dados ---
def eventos(con) -> list[dict]:
    """Um registro por (artigo, ticker), agora carregando o TIPO do evento."""
    rows = con.execute("""
        SELECT a.published_ts ts, sc.ticker, sc.s, sc.magnitude, sc.novelty,
               sc.tipo_evento, sc.orientacao, m.relevance, m.driver,
               m.sinal_driver, a.domain, a.title
        FROM scores sc
        JOIN mentions m ON m.article_id=sc.article_id AND m.ticker=sc.ticker
        JOIN articles a ON a.id=sc.article_id
        WHERE sc.ticker != '__none__' AND sc.tipo_evento IS NOT NULL
        ORDER BY a.published_ts""").fetchall()
    src = config.sources()
    peso_dom = src.get("domains", {})
    padrao = src.get("default_weight", 0.35)
    out = []
    for r in rows:
        s = r["s"]
        if r["driver"] and (r["sinal_driver"] or 1) < 0:
            s = -s
        peso = (peso_dom.get(r["domain"], padrao) * r["relevance"]
                * r["novelty"] * r["magnitude"])
        out.append({
            "ts": r["ts"], "ticker": r["ticker"], "tipo": r["tipo_evento"],
            "orient": set((r["orientacao"] or "").split(",")) - {""},
            "titulo": r["title"], "s": s,
            "forca": s * r["magnitude"],
            "intensidade": abs(s) * r["magnitude"] * peso,
        })
    return out


# ------------------------------------------------------------------ nucleo ---
def roda(gran, evs, series, rnd, alvo_vol):
    res = []
    for tipo in TIPOS:
        for h in HORIZONTES[gran]:
            linhas = []
            papeis = sorted({e["ticker"] for e in evs if e["tipo"] == tipo})
            for p in papeis:
                if p not in series:
                    continue
                sel = [e for e in evs if e["ticker"] == p and e["tipo"] == tipo]
                if not sel:
                    continue
                linhas += celulas(sel, series[p], h,
                                  abs(h) if abs(h) > 1 else 1,
                                  diario=(gran == "diario"))
            base_dir = (None if alvo_vol
                        else base_direcional(series, papeis, h))
            m = mede(linhas, alvo_vol, rnd, base_dir)
            if m:
                res.append({"gran": gran, "tipo": tipo, "h": h,
                            "janela": "passado" if h < 0 else "futuro",
                            "papeis": len(papeis), **m})
            else:
                res.append({"gran": gran, "tipo": tipo, "h": h,
                            "janela": "passado" if h < 0 else "futuro",
                            "papeis": len(papeis), "n": len(linhas),
                            "vazio": True})
    return res


def imprime(titulo, res, corte_fdr):
    print(f"\n{'=' * 104}\n{titulo}\n{'=' * 104}")
    print(f"{'tipo':<13}{'janela':<9}{'h':>5}{'papeis':>8}{'celulas':>9}"
          f"{'IC':>9}{'p':>7}{'acerto em 100':>15}{'chute':>7}"
          f"{'IC95 do acerto':>18}  veredito")
    for r in sorted(res, key=lambda x: (TIPOS.index(x["tipo"]), x["h"])):
        if r.get("vazio"):
            print(f"{r['tipo']:<13}{r['janela']:<9}{r['h']:>5}"
                  f"{r['papeis']:>8}{r['n']:>9}"
                  f"{'—':>9}{'—':>7}{'—':>15}{'—':>7}{'—':>18}"
                  f"  menos de 8 celulas: nao calcula")
            continue
        desc = r["n"] < MIN_N
        if desc:
            vd = f"DESCRITIVO (n={r['n']} < {MIN_N})"
        elif r["p"] <= corte_fdr and corte_fdr > 0:
            vd = "PASSA (FDR)"
        elif r["p"] < 0.05:
            vd = "p<0,05 mas cai no FDR"
        else:
            vd = "nulo"
        print(f"{r['tipo']:<13}{r['janela']:<9}{r['h']:>5}{r['papeis']:>8}"
              f"{r['n']:>9}{r['ic']:>+9.4f}{r['p']:>7.3f}"
              f"{r['acerto']:>15.1f}{r['base']:>7.1f}"
              f"   [{r['ic95'][0]:>5.1f} – {r['ic95'][1]:>5.1f}]  {vd}")


def em_100(res, titulo, alvo_vol):
    """A mesma coisa sem jargao: acertos por 100 e o que o intervalo permite.

    O COMPARADOR MUDA COM A PERGUNTA, e confundir os dois inverte a leitura:

    DIRECAO     -- "acertar" e o papel ter ido para o lado que o sinal disse.
        Chutar as cegas acerta ~50 em 100 (a moeda), e chutar sempre o lado
        mais frequente DESTE papel acerta um pouco mais. O comparador e esse
        segundo numero.

    VOLATILIDADE -- "acertar" e o papel ter ficado entre os 20% que mais se
        mexeram. Por construcao, chutar as cegas acerta ~20 em 100, NAO 50.
        Logo 35 em 100 aqui e BOM e 45 em 100 na direcao e RUIM -- o mesmo
        numero quer dizer coisas opostas nas duas tabelas. Comparar
        volatilidade com 50 foi um defeito da primeira versao desta funcao, e
        fazia um resultado bom parecer pessimo.
    """
    print(f"\n{'-' * 104}\n{titulo} — EM ACERTOS POR 100\n{'-' * 104}")
    uteis = [r for r in res if not r.get("vazio")]
    if not uteis:
        print("  nenhuma combinacao tem celula suficiente para calcular nada.")
        return
    if alvo_vol:
        print("  LEMBRE: aqui 'acertar' = o papel ficou entre os 20% que mais")
        print("  se mexeram. Chutar as cegas acerta ~20 em 100, nao 50.")
    for r in sorted(uteis, key=lambda x: (TIPOS.index(x["tipo"]), x["h"])):
        lo, hi = r["ic95"]
        larg = hi - lo
        acerto, chute = r["acerto"], r["base"]
        vant = acerto - chute
        print(f"\n  {r['tipo'].upper()}, {r['janela']}, h={r['h']}  "
              f"({r['n']} celulas, {r['papeis']} papel(is))")
        if alvo_vol:
            print(f"    acertou {acerto:.0f} em 100 entre os casos que o sinal "
                  f"apontou como mais agitados.")
            print(f"    Chutar as cegas acerta {chute:.0f} em 100.")
        else:
            print(f"    acertou {acerto:.0f} em 100.  Chutar sempre o lado mais "
                  f"comum deste papel acerta {chute:.0f} em 100.")
        if vant >= 0:
            print(f"    vantagem: {vant:+.0f} acertos em 100.")
        else:
            print(f"    perdeu do chute por {-vant:.0f} acertos em 100.")
        print(f"    MAS a margem de erro vai de {lo:.0f} a {hi:.0f} em 100 "
              f"(largura de {larg:.0f} pontos).")
        if lo <= chute <= hi:
            print(f"    -> o chute ({chute:.0f} em 100) esta DENTRO da margem. "
                  f"Este numero nao distingue sinal de sorte.")
        elif lo > chute:
            print("    -> a margem toda fica acima do chute. Aqui ha algo, "
                  "sujeito a correcao de teste multiplo.")
        else:
            print("    -> a margem toda fica abaixo do chute: acerta menos "
                  "que o chute, de forma consistente.")
        if r["n"] < MIN_N:
            falta = amostra_necessaria(max(abs(vant), 5.0))
            print(f"    para esta vantagem virar resultado seriam ~{falta} "
                  f"celulas; ha {r['n']}.")


# ------------------------------------------------------------ instabilidade --
def instabilidade(res, nome):
    """O MESMO sinal, lado a lado, em granularidades vizinhas.

    E a prova mais clara de que n=10 nao mede nada, e nao precisa de
    estatistica para ser lida: se o mesmo tipo de evento "acerta 88 em 100" em
    5 minutos e "29 em 100" em 15 minutos, com 10 casos em cada, o que varia
    nao e o mercado -- e o sorteio de quais 10 casos cairam em cada celula.
    Um numero que pula 59 pontos entre duas medicoes vizinhas nao e medida.
    """
    print(f"\n{'=' * 104}")
    print(f"O MESMO SINAL, EM GRANULARIDADES VIZINHAS — {nome}")
    print(f"{'=' * 104}")
    print("Se o numero fosse medida, mudaria pouco de uma linha para a vizinha.")
    print("Olhe o tamanho do pulo, e o n de cada uma.\n")
    for tipo in TIPOS:
        linhas = [r for r in res if r["tipo"] == tipo and not r.get("vazio")
                  and r["h"] > 0]
        if not linhas:
            continue
        print(f"  {tipo.upper()} — noticia sobre movimento FUTURO")
        print(f"    {'granularidade':<16}{'h':>4}{'celulas':>9}"
              f"{'acertou em 100':>16}{'chute':>8}")
        for g in ORDEM_GRAN:
            for r in sorted([x for x in linhas if x["gran"] == g],
                            key=lambda x: x["h"]):
                print(f"    {rotulo_gran(g):<16}{r['h']:>4}{r['n']:>9}"
                      f"{r['acerto']:>16.0f}{r['base']:>8.0f}")
        acertos = [r["acerto"] for r in linhas]
        ns = [r["n"] for r in linhas]
        pulo = max(acertos) - min(acertos)
        print(f"    -> variou de {min(acertos):.0f} a {max(acertos):.0f} em 100 "
              f"({pulo:.0f} pontos de pulo) com n entre {min(ns)} e {max(ns)}.")
        if max(ns) < MIN_N:
            print(f"       NENHUMA linha chega a {MIN_N} celulas. O pulo e o "
                  f"tamanho do ruido, nao um efeito de prazo.")
        print()


# --------------------------------------------------------------- auditoria ---
def auditoria(evs):
    """Le os casos a mao. Com n=16 isto acha mais defeito que a estatistica.

    "Judicial tambem deve julgar se e ruim para o papel" -- o sinal EXISTE
    (coluna `s`, com sinal, a mesma do grafico). A pergunta e se ele aponta
    para o lado certo, e isso se confere lendo.
    """
    print(f"\n{'=' * 104}")
    print("AUDITORIA A MAO -- os casos dos tres tipos pedidos, um por um")
    print(f"{'=' * 104}")
    print("O sinal de `s` e o efeito NO PAPEL: negativo = ruim para o papel.")
    print("Leia a manchete e julgue se o sinal aponta para o lado certo.\n")
    for tipo in PEDIDOS:
        sel = [e for e in evs if e["tipo"] == tipo]
        print(f"\n  {tipo.upper()}  ({len(sel)} caso(s))")
        if not sel:
            print("    nenhum")
            continue
        for e in sorted(sel, key=lambda x: x["s"]):
            marca = "ruim" if e["s"] < -0.05 else (
                "bom" if e["s"] > 0.05 else "neutro")
            orient = ",".join(sorted(e["orient"])) or "—"
            print(f"    {e['ticker']:<7}{e['s']:+.2f} {marca:<7}[{orient}]")
            print(f"            {e['titulo'][:88]}")


# ------------------------------------------------------------------- main ----
def main(simples=False, so_auditoria=False):
    con = connect()
    evs = eventos(con)
    print(f"{'=' * 104}")
    print("TIPO DE EVENTO x RETORNO -- quanto cada tipo acerta")
    print(f"{'=' * 104}")
    cont = {}
    for e in evs:
        cont[e["tipo"]] = cont.get(e["tipo"], 0) + 1
    print("\nMATERIAS CLASSIFICADAS POR TIPO (a restricao que manda em tudo):")
    for t in TIPOS:
        n = cont.get(t, 0)
        veredito = ("da para medir" if n >= 300 else
                    "no limite" if n >= 100 else
                    "NAO da para medir")
        marca = "  <- pedido" if t in PEDIDOS else ""
        print(f"  {t:<13}{n:>5}   {veredito}{marca}")
    print("\nQUANTAS CELULAS SERIAM NECESSARIAS (teste de proporcao vs 50%, "
          "poder 80%):")
    for v in (3, 5, 10, 15, 20):
        print(f"  para provar vantagem de {v:>2} acertos em 100: "
              f"{amostra_necessaria(v):>6} celulas")

    if so_auditoria:
        auditoria(evs)
        con.close()
        return

    rnd = random.Random(SEMENTE)
    series_por_gran = {}
    for g in ORDEM_GRAN:
        series_por_gran[g] = (series_diaria(con) if g == "diario"
                              else series_intra(con, g))
    con.close()

    todos = {"direcao": [], "volatilidade": []}
    for g in ORDEM_GRAN:
        series = series_por_gran[g]
        if not series:
            print(f"\n{'=' * 104}\n{rotulo_gran(g)}: sem serie no banco\n"
                  f"{'=' * 104}")
            continue
        for alvo, chave in ((False, "direcao"), (True, "volatilidade")):
            res = roda(g, evs, series, rnd, alvo)
            todos[chave] += res

    for chave in ("direcao", "volatilidade"):
        res = todos[chave]
        ps = [r["p"] for r in res if not r.get("vazio") and r["n"] >= MIN_N]
        corte = bh(ps, FDR_Q) if ps else 0.0
        nome = ("DIRECAO (o papel sobe ou cai?)" if chave == "direcao"
                else "VOLATILIDADE (o papel se mexe muito?)")
        print(f"\n\n{'#' * 104}")
        print(f"#  {nome}")
        print("#  grafico separado, como pedido -- um resultado nao autoriza "
              "o outro")
        print(f"{'#' * 104}")
        for g in ORDEM_GRAN:
            sub = [r for r in res if r["gran"] == g]
            if not sub:
                continue
            if not simples:
                imprime(f"{rotulo_gran(g)} — {nome}", sub, corte)
            em_100(sub, f"{rotulo_gran(g)} — {nome}", chave == "volatilidade")
        aprov = [r for r in res if not r.get("vazio")
                 and r["n"] >= MIN_N and corte > 0 and r["p"] <= corte]
        pedidos_uteis = [r for r in res if not r.get("vazio")
                         and r["tipo"] in PEDIDOS and r["n"] >= MIN_N]
        print(f"\n  RESUMO {nome}: {len(aprov)} linha(s) sobrevivem ao FDR "
              f"(q={FDR_Q}), de {len([r for r in res if not r.get('vazio')])} "
              f"calculadas.")
        print(f"  Dos TIPOS PEDIDOS (judicial, legislativo, calendario): "
              f"{len(pedidos_uteis)} linha(s) chegaram ao piso de "
              f"{MIN_N} celulas.")
        instabilidade(res, nome)

    auditoria(evs)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(simples="--simples" in a, so_auditoria="--auditoria" in a)
