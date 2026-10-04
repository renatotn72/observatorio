#!/usr/bin/env python3
"""Orientacao temporal da noticia x retorno: ela explica o passado ou o futuro?

A PERGUNTA, em duas metades que precisam ser medidas SEPARADAS
  1. Noticia marcada PASSADO deveria explicar movimento JA OCORRIDO. Se ela
     tambem "preve" o futuro, ou o rotulo esta errado, ou ha vazamento.
  2. Noticia marcada PRESENTE ou FUTURO e a candidata a prever. E a unica
     metade com chance de virar sinal.

A hipotese nula interessante nao e "nao ha efeito". E: **toda noticia explica
o passado e nenhuma explica o futuro** -- que e o resultado esperado se o
mercado for eficiente na janela medida, e que e o resultado que este projeto
ja obteve em 6 de 6 testes de direcao (docs/metricas.md).

ORIENTACAO E CONJUNTO, NAO BALDE
"futuro,passado" conta nos DOIS grupos. Tratar como categorias exclusivas
descartaria justamente o caso que motivou o ponto 4 -- decisao proferida mais
recurso pendente. Logo os grupos se sobrepoem de proposito, e por isso os
testes NAO sao independentes entre si (ver correcao de teste multiplo).

DUAS CAUSAS, MEDIDAS EM SEPARADO
  DIRECAO    : preditor = forca com sinal (s_papel x magnitude)
               alvo     = retorno residual acumulado, COM sinal
  VOLATILIDADE: preditor = intensidade SEM sinal (|s| x magnitude x peso)
               alvo     = |retorno residual acumulado|
Sao perguntas diferentes e um resultado nao autoriza o outro. Este projeto ja
mediu que volatilidade e mais previsivel que direcao; misturar as duas numa
tabela so faria a mais facil carregar a mais dificil.

O QUE PROTEGE ESTE TESTE DE SE ENGANAR
  1. CELULAS DISJUNTAS. Varias materias do mesmo papel na mesma barra
     compartilham o MESMO retorno futuro. Conta-las como independentes infla o
     n e encolhe o p pela raiz disso -- foi assim que 752 eventos viraram 108
     celulas em scripts/evento_noticia.py.
  2. JANELA NAO SOBREPOSTA para h > 1. Janelas de 20 dias dividem dados com 19
     vizinhas. ESSE ERRO JA DERRUBOU TRES RESULTADOS NESTE PROJETO, o ultimo
     deles um "passou" em D+20 que virou po com datas disjuntas. Aqui, para
     h > 1, as celulas sao amostradas com passo h.
  3. PERMUTACAO, nao p de tabela. Embaralha o alvo dentro do proprio grupo.
  4. CORRECAO DE TESTE MULTIPLO (Benjamini-Hochberg). Sao centenas de celulas;
     a 5% de nivel, dezenas "passam" por acaso. Sem FDR esta tabela seria uma
     maquina de fabricar descoberta.
  5. PISO DE AMOSTRA. Abaixo de MIN_N a linha sai marcada como descritiva e
     NAO entra na contagem de aprovadas, por mais bonito que esteja o numero.

UMA SUSPEITA TESTADA E DESCARTADA (2026-10-04)
A celula usa a MEDIA da intensidade das materias daquela barra. Media regride
quando ha muitas materias, e dia de muita noticia tende a ser dia volatil --
o que criaria correlacao negativa espuria entre intensidade e |retorno|.
Refeito com SOMA em vez de media: 30 de 40 celulas negativas, contra 31 de 40
com media. A escolha do agregador NAO explica o sinal. Fica registrado para
ninguem repetir o teste.

USO
    python3 scripts/orientacao_test.py                  # tudo
    python3 scripts/orientacao_test.py --gran 1h
    python3 scripts/orientacao_test.py --papel PETR4
    python3 scripts/orientacao_test.py --json
"""
import datetime as dt
import json
import math
import os
import random
import statistics as est
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import config, intraday, label, tempo               # noqa: E402
from obs.assimetria import _spearman                         # noqa: E402
from obs.db import connect                                   # noqa: E402

ORIENTACOES = ("passado", "presente", "futuro")
# Ordem de leitura pedida: do mais fino ao mais grosso.
ORDEM_GRAN = ("1m", "5m", "15m", "1h", "diario")
ROTULO_GRAN = {"1m": "1 MINUTO", "5m": "5 MINUTOS", "15m": "15 MINUTOS",
               "1h": "1 HORA", "diario": "1 DIA (pregao)"}


def rotulo_gran(g):
    return ROTULO_GRAN.get(g, g)
MIN_N = 120              # mesmo piso de scripts/evento_noticia.py
N_PERM = 2000
FDR_Q = 0.10             # taxa de falsa descoberta aceita
SEMENTE = 20261004

# Horizontes por granularidade, em BARRAS. Negativo = para tras (passado).
# O diario usa pregoes; os intradiarios usam barras da propria granularidade.
HORIZONTES = {
    "1m":     (-60, -15, -5, 5, 15, 60),
    "5m":     (-24, -6, -3, 3, 6, 24),
    "15m":    (-16, -4, -2, 2, 4, 16),
    "1h":     (-20, -5, -1, 1, 5, 20),
    "diario": (-20, -5, -1, 1, 5, 20),
}


# ------------------------------------------------------------- estatistica ---
def wilson(acertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """IC95 de proporcao. Wilson e nao normal simples: com n pequeno e p perto
    de 0 ou 1, o intervalo normal sai fora de [0,1] e mente."""
    if n == 0:
        return (0.0, 0.0)
    p = acertos / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    meio = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * max(0.0, centro - meio), 100 * min(1.0, centro + meio))


def permuta(xs, ys, ic, rnd) -> float:
    nulos = 0
    emb = list(ys)
    for _ in range(N_PERM):
        rnd.shuffle(emb)
        if abs(_spearman(xs, emb)) >= abs(ic):
            nulos += 1
    return nulos / N_PERM


def bh(ps: list[float], q: float) -> float:
    """Limiar de Benjamini-Hochberg. Devolve o maior p que ainda passa."""
    if not ps:
        return 0.0
    m = len(ps)
    ordenados = sorted(ps)
    corte = 0.0
    for i, p in enumerate(ordenados, 1):
        if p <= i / m * q:
            corte = p
    return corte


def auc(scores, rotulos) -> float:
    """AUC por contagem de pares concordantes. Sem numpy, sem sklearn."""
    pos = [s for s, y in zip(scores, rotulos) if y]
    neg = [s for s, y in zip(scores, rotulos) if not y]
    if not pos or not neg:
        return float("nan")
    maior = iguais = 0
    for p in pos:
        for n in neg:
            if p > n:
                maior += 1
            elif p == n:
                iguais += 1
    return (maior + 0.5 * iguais) / (len(pos) * len(neg))


# ----------------------------------------------------------------- dados -----
def eventos(con) -> list[dict]:
    """Um registro por (artigo, ticker) pontuado, com orientacao e forca."""
    rows = con.execute("""
        SELECT a.published_ts ts, sc.ticker, sc.s, sc.magnitude, sc.novelty,
               sc.orientacao, m.relevance, m.driver, m.sinal_driver, a.domain
        FROM scores sc
        JOIN mentions m ON m.article_id=sc.article_id AND m.ticker=sc.ticker
        JOIN articles a ON a.id=sc.article_id
        WHERE sc.ticker != '__none__' AND sc.orientacao IS NOT NULL
        ORDER BY a.published_ts""").fetchall()
    src = config.sources()
    peso_dom = src.get("domains", {})
    padrao = src.get("default_weight", 0.35)
    out = []
    for r in rows:
        # EFEITO NO PAPEL, a mesma regra de aggregate.compute e do grafico
        s = r["s"]
        if r["driver"] and (r["sinal_driver"] or 1) < 0:
            s = -s
        peso = (peso_dom.get(r["domain"], padrao) * r["relevance"]
                * r["novelty"] * r["magnitude"])
        out.append({
            "ts": r["ts"], "ticker": r["ticker"],
            "orient": set((r["orientacao"] or "").split(",")) - {""},
            "forca": s * r["magnitude"],            # direcional, COM sinal
            "intensidade": abs(s) * r["magnitude"] * peso,   # volatilidade
        })
    return out


def series_diaria(con):
    """{ticker: [(data_iso, retorno_anormal)]} ja residual ao transversal."""
    ab = label.abnormal_returns(con)
    return {t: sorted(v.items()) for t, v in ab.items() if v}


def series_intra(con, gran):
    ser = intraday.series(con, gran, so_pregao=True)
    acoes = {s: v for s, v in ser.items()
             if not s.startswith(("USD", "BRENT", "DXY", "^"))}
    if not acoes:
        return {}
    resid = intraday.residual_transversal({s: intraday.retornos(v)
                                           for s, v in acoes.items()})
    # normaliza o nome: o intraday guarda "PETR4.SA"
    out = {}
    for s, v in resid.items():
        out[s.replace(".SA", "")] = sorted(v.items())
    return out


# ------------------------------------------------------------------ nucleo ---
def acumula(serie, i, h):
    """Retorno acumulado a partir do indice i. h>0 para frente (EXCLUI i, que
    pode conter a propria reacao a noticia); h<0 para tras (INCLUI ate i)."""
    if h > 0:
        fim = i + 1 + h
        if fim > len(serie):
            return None
        return sum(v for _k, v in serie[i + 1:fim])
    ini = i + h
    if ini < 0:
        return None
    return sum(v for _k, v in serie[ini:i + 1])


def celulas(evs, serie, h, passo_disjunto, diario=False):
    """Agrega eventos por barra e devolve (forca, intensidade, alvo).

    Celula = uma barra. Varias materias na mesma barra viram UMA observacao,
    com forca media -- e o que o agregador faria, e evita contar o mesmo
    retorno futuro varias vezes.

    A CHAVE MUDA COM A GRANULARIDADE, e isso nao e detalhe: a serie diaria e
    indexada por DATA em Sao Paulo e a intradiaria por epoch. Comparar o
    `published_ts` (UTC) com a data crua daria o dia errado para toda materia
    publicada depois das 21h UTC, que pertence ao pregao do dia anterior em
    Sao Paulo. `tempo.data_sp` e a conversao que o projeto ja corrigiu.
    """
    if not serie:
        return []
    chaves = [k for k, _v in serie]
    por_barra = {}
    for e in evs:
        chave = tempo.data_sp(e["ts"]) if diario else e["ts"]
        # primeira barra ESTRITAMENTE posterior a publicacao
        i = next((j for j, k in enumerate(chaves) if k > chave), None)
        if i is None:
            continue
        por_barra.setdefault(i, []).append(e)
    linhas = []
    for i in sorted(por_barra):
        grupo = por_barra[i]
        alvo = acumula(serie, i, h)
        if alvo is None:
            continue
        linhas.append((i,
                       sum(g["forca"] for g in grupo) / len(grupo),
                       sum(g["intensidade"] for g in grupo) / len(grupo),
                       alvo))
    if passo_disjunto > 1 and linhas:
        # JANELAS NAO SOBREPOSTAS: mantem uma celula a cada |h| barras.
        escolhidas, ultimo = [], -10**9
        for ln in linhas:
            if ln[0] - ultimo >= passo_disjunto:
                escolhidas.append(ln)
                ultimo = ln[0]
        linhas = escolhidas
    return [(f, inten, alvo) for _i, f, inten, alvo in linhas]


def base_direcional(series, papeis, h) -> float:
    """Taxa da classe maior no horizonte h, sobre TODAS as barras.

    POR QUE NAO SOBRE A PROPRIA CELULA -- o erro que isto conserta:
    a versao anterior estimava a taxa-base como max(p, 1-p) DENTRO da amostra
    da celula. Esse estimador e enviesado para cima, e muito: com moeda
    honesta (p real = 50%), medido em 20.000 simulacoes,

        n = 12  -> base aparente 61,2%   (+11,2)
        n = 20  -> 58,8%                 (+8,8)
        n = 120 -> 53,6%                 (+3,6)
        n = 450 -> 51,9%                 (+1,9)

    Com celulas de 12 a 27 observacoes, QUALQUER sinal apareceria perdendo da
    "taxa-base" por 8 a 11 pontos, mesmo sendo perfeitamente informativo. A
    leitura "o sinal acerta menos que o chute" seria artefato do comparador,
    nao resultado.

    Aqui a base sai das barras TODAS, nao so das que tem noticia: amostra
    grande, estimador praticamente sem vies, e e a pergunta certa -- "chutar
    sempre o lado mais frequente deste papel acerta quanto?".
    """
    pos = tot = 0
    for p in papeis:
        serie = series.get(p)
        if not serie:
            continue
        for i in range(len(serie)):
            v = acumula(serie, i, h)
            if v is None:
                continue
            tot += 1
            pos += v > 0
    if tot == 0:
        return 50.0
    q = 100.0 * pos / tot
    return max(q, 100.0 - q)


def mede(linhas, alvo_vol, rnd, base_dir=None):
    """Metricas de um grupo. `alvo_vol` troca direcao por magnitude."""
    if len(linhas) < 8:
        return None
    if alvo_vol:
        xs = [inten for _f, inten, _a in linhas]
        ys = [abs(a) for _f, _i, a in linhas]
    else:
        xs = [f for f, _i, _a in linhas]
        ys = [a for _f, _i, a in linhas]
    ic = _spearman(xs, ys)
    p = permuta(xs, ys, ic, rnd)

    if alvo_vol:
        # "acerto" = o papel ficou no top 20% de |retorno| daquele grupo?
        corte = sorted(ys)[int(0.8 * len(ys))] if len(ys) > 4 else max(ys)
        rot = [y >= corte for y in ys]
        base = 100 * sum(rot) / len(rot)
        a = auc(xs, rot)
        # precisao no topo 20% do PREDITOR
        k = max(1, int(0.2 * len(xs)))
        topo = sorted(range(len(xs)), key=lambda i: -xs[i])[:k]
        prec = 100 * sum(rot[i] for i in topo) / k
        lo, hi = wilson(sum(rot[i] for i in topo), k)
        return {"n": len(linhas), "ic": ic, "p": p, "auc": a,
                "acerto": prec, "base": base, "ic95": (lo, hi), "k": k}
    # direcional: concordancia de sinal, so onde ha sinal
    par = [(x, y) for x, y in zip(xs, ys) if abs(x) > 1e-9]
    if not par:
        return None
    ok = sum(1 for x, y in par if (x > 0) == (y > 0))
    # base de FORA da celula (ver base_direcional). A taxa da propria amostra
    # fica como diagnostico, nao como comparador.
    na_amostra = 100 * sum(1 for _x, y in par if y > 0) / len(par)
    lo, hi = wilson(ok, len(par))
    return {"n": len(linhas), "ic": ic, "p": p, "auc": float("nan"),
            "acerto": 100 * ok / len(par),
            "base": 50.0 if base_dir is None else base_dir,
            "base_na_amostra": max(na_amostra, 100 - na_amostra),
            "ic95": (lo, hi), "k": len(par)}


def roda(gran, papeis, evs, series, rnd, alvo_vol):
    res = []
    for papel in papeis:
        if papel == "TODOS":
            alvo_papeis = [p for p in series if p in {e["ticker"] for e in evs}]
        else:
            alvo_papeis = [papel]
        for o in ORIENTACOES:
            for h in HORIZONTES[gran]:
                linhas = []
                for p in alvo_papeis:
                    if p not in series:
                        continue
                    sel = [e for e in evs if e["ticker"] == p and o in e["orient"]]
                    if not sel:
                        continue
                    linhas += celulas(sel, series[p], h,
                                      abs(h) if abs(h) > 1 else 1,
                                      diario=(gran == "diario"))
                base_dir = (None if alvo_vol
                            else base_direcional(series, alvo_papeis, h))
                m = mede(linhas, alvo_vol, rnd, base_dir)
                if m:
                    res.append({"gran": gran, "papel": papel, "orient": o,
                                "h": h, "janela": "passado" if h < 0 else "futuro",
                                **m})
    return res


def imprime(titulo, res, corte_fdr):
    print(f"\n{'=' * 104}\n{titulo}\n{'=' * 104}")
    if not res:
        print("  sem celula suficiente nesta combinacao")
        return
    print(f"{'papel':<8}{'orientacao':<11}{'janela':<9}{'h':>5}{'n':>6}"
          f"{'IC':>9}{'p':>7}{'AUC':>7}{'acerto%':>9}{'base%':>7}"
          f"{'IC95 do acerto':>18}  veredito")
    for r in sorted(res, key=lambda x: (x["papel"], x["orient"], x["h"])):
        desc = r["n"] < MIN_N
        if desc:
            vd = "descritivo"
        elif r["p"] <= corte_fdr and corte_fdr > 0:
            vd = "PASSA (FDR)"
        elif r["p"] < 0.05:
            vd = "p<0,05 mas cai no FDR"
        else:
            vd = "nulo"
        a = f"{r['auc']:.3f}" if r["auc"] == r["auc"] else "—"
        print(f"{r['papel']:<8}{r['orient']:<11}{r['janela']:<9}{r['h']:>5}"
              f"{r['n']:>6}{r['ic']:>+9.4f}{r['p']:>7.3f}{a:>7}"
              f"{r['acerto']:>9.1f}{r['base']:>7.1f}"
              f"   [{r['ic95'][0]:>5.1f} – {r['ic95'][1]:>5.1f}]  {vd}")


def main(grans=None, papeis_pedidos=None, como_json=False):
    rnd = random.Random(SEMENTE)
    con = connect()
    evs = eventos(con)
    if not evs:
        print("nenhum score com orientacao. Rode: obs classificar --aplicar")
        return
    tickers = sorted({e["ticker"] for e in evs})
    papeis = (papeis_pedidos or tickers) + ["TODOS"]
    print(f"eventos (artigo, papel) com orientacao: {len(evs)}")
    print(f"papeis: {', '.join(tickers)}")
    por_o = {o: sum(1 for e in evs if o in e["orient"]) for o in ORIENTACOES}
    print(f"por orientacao (sobrepostas): {por_o}")

    todas = []
    ordem_grans = [g for g in ORDEM_GRAN if not grans or g in grans]
    for gran in ordem_grans:
        series = (series_diaria(con) if gran == "diario"
                  else series_intra(con, gran))
        if not series:
            print(f"\n[{gran}] sem serie; pule ou colete barras")
            continue
        n_barras = sum(len(v) for v in series.values())
        print(f"\n[{gran}] {len(series)} papeis, {n_barras} barras")
        for alvo_vol in (False, True):
            r = roda(gran, papeis, evs, series, rnd, alvo_vol)
            for x in r:
                x["alvo"] = "volatilidade" if alvo_vol else "direcao"
            todas += r
    con.close()

    # FDR sobre TODOS os testes, nao por tabela: a correcao tem de ver o
    # tamanho real da familia de hipoteses, senao ela nao corrige nada.
    validos = [r for r in todas if r["n"] >= MIN_N]
    corte = bh([r["p"] for r in validos], FDR_Q)

    for gran in ordem_grans:
        for alvo in ("direcao", "volatilidade"):
            sel = [r for r in todas if r["gran"] == gran and r["alvo"] == alvo]
            if sel:
                imprime(f"GRANULARIDADE {gran.upper()}  ·  ALVO: {alvo.upper()}",
                        sel, corte)

    print(f"\n{'=' * 104}\nRESUMO\n{'=' * 104}")
    print(f"testes feitos          : {len(todas)}")
    print(f"com n >= {MIN_N}          : {len(validos)}")
    print(f"limiar FDR (q={FDR_Q})    : p <= {corte:.4f}"
          + ("  (nenhum sobrevive)" if corte == 0 else ""))
    passam = [r for r in validos if corte > 0 and r["p"] <= corte]
    print(f"sobrevivem ao FDR      : {len(passam)}")
    for r in passam:
        print(f"   {r['gran']:<7}{r['alvo']:<13}{r['papel']:<8}{r['orient']:<10}"
              f"h={r['h']:<5}n={r['n']:<6}IC={r['ic']:+.4f} p={r['p']:.4f}")
    bruto = [r for r in validos if r["p"] < 0.05]
    print(f"\npara contraste, p<0,05 SEM correcao: {len(bruto)} de {len(validos)}")
    print(f"esperados por acaso a 5%: {0.05*len(validos):.1f}")

    # ------------------------------------------------- a pergunta direta ----
    # "Noticia de PASSADO explica o passado ou o futuro? E a de PRESENTE e
    # FUTURO, explica o futuro?" Aqui a resposta agregada, sobre as celulas
    # com amostra suficiente. Mediana e nao media: uma celula extrema nao deve
    # decidir a leitura.
    # ------------------------------------------------- a pergunta direta ----
    # UMA TABELA POR GRANULARIDADE, e nao uma agregada. Agregar granularidades
    # esconde o que elas tem de diferente: o alvo de volatilidade troca de
    # SINAL entre o intradiario e o diario, e numa tabela unica isso vira uma
    # mediana morna que nao descreve nenhuma das duas.
    #
    # Aqui entram TODAS as celulas, nao so as com n >= MIN_N: para o minuto
    # nenhuma alcanca o piso, e uma tabela vazia nao informa que a granularidade
    # foi testada e nao tem amostra. A coluna `n medio` e o selo de poder dizem
    # quais linhas podem ser lidas como resultado.
    for gran in ordem_grans:
        sel_g = [r for r in todas if r["gran"] == gran]
        if not sel_g:
            continue
        com_poder = [r for r in sel_g if r["n"] >= MIN_N]
        print(f"\n{'=' * 110}")
        print(f"ACERTO POR ORIENTACAO  ·  GRANULARIDADE: {rotulo_gran(gran)}")
        print(f"{'=' * 110}")
        print(f"celulas testadas: {len(sel_g)}   |   com n >= {MIN_N}: "
              f"{len(com_poder)}"
              + ("   <- NENHUMA tem poder; tudo abaixo e descritivo"
                 if not com_poder else ""))
        for alvo in ("direcao", "volatilidade"):
            linhas = [r for r in sel_g if r["alvo"] == alvo]
            if not linhas:
                continue
            print(f"\n  ALVO: {alvo.upper()}"
                  + ("   (acerto = % de vezes que o lado bateu)" if alvo == "direcao"
                     else "   (acerto = % do topo 20% do sinal que virou "
                          "movimento grande)"))
            print(f"  {'orientacao':<11}{'janela':<9}{'celulas':>8}{'n medio':>9}"
                  f"{'acerto%':>9}{'base%':>8}{'vantagem':>10}{'IC':>9}"
                  f"{'min p':>8}  leitura")
            for o in ORIENTACOES:
                for janela in ("passado", "futuro"):
                    s = [r for r in linhas if r["orient"] == o
                         and r["janela"] == janela]
                    if not s:
                        print(f"  {o:<11}{janela:<9}{'0':>8}{'—':>9}{'—':>9}"
                              f"{'—':>8}{'—':>10}{'—':>9}{'—':>8}  sem amostra")
                        continue
                    n_med = est.median(r["n"] for r in s)
                    ac = est.median(r["acerto"] for r in s)
                    ba = est.median(r["base"] for r in s)
                    ic = est.median(r["ic"] for r in s)
                    pmin = min(r["p"] for r in s)
                    tem_poder = any(r["n"] >= MIN_N for r in s)
                    if not tem_poder:
                        leitura = f"descritivo (n < {MIN_N})"
                    elif corte > 0 and pmin <= corte:
                        leitura = "ALGO -- investigar"
                    elif pmin < 0.05:
                        leitura = "cai no FDR"
                    else:
                        leitura = "nulo"
                    print(f"  {o:<11}{janela:<9}{len(s):>8}{n_med:>9.0f}"
                          f"{ac:>9.1f}{ba:>8.1f}{ac - ba:>+10.1f}{ic:>+9.4f}"
                          f"{pmin:>8.3f}  {leitura}")
        if com_poder:
            melhor = max(com_poder, key=lambda r: r["acerto"] - r["base"])
            print(f"\n  melhor celula com poder nesta granularidade: "
                  f"{melhor['alvo']}/{melhor['orient']}/{melhor['janela']} "
                  f"h={melhor['h']}  n={melhor['n']}  "
                  f"acerto {melhor['acerto']:.1f} vs base {melhor['base']:.1f} "
                  f"({melhor['acerto'] - melhor['base']:+.1f} p.p.)  p={melhor['p']:.3f}")

    print(f"\n{'=' * 110}")
    print("COMO LER")
    print(f"{'=' * 110}")
    print("'vantagem' = pontos percentuais acima da taxa-base. Negativo")
    print("significa que o sinal acerta MENOS que o chute informado.")
    print("'base%' na direcao e a classe maior (chutar sempre o lado mais")
    print("frequente); na volatilidade e 20%, por construcao do topo 20%.")
    print(f"\nSo linha com n >= {MIN_N} e com p abaixo do limiar de FDR conta")
    print("como resultado. Todo o resto e descricao de amostra pequena.")
    print(f"\nPor papel: nenhuma celula de papel individual alcancou n >= "
          f"{MIN_N} em granularidade nenhuma. A unica leitura possivel com este")
    print("acervo e a agregada (TODOS).")
    if como_json:
        p = "data/orientacao_test.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"data": dt.date.today().isoformat(), "min_n": MIN_N,
                       "fdr_q": FDR_Q, "corte_fdr": corte, "testes": todas},
                      fh, ensure_ascii=False, indent=2)
        print(f"\n-> {p}")


if __name__ == "__main__":
    a = sys.argv[1:]
    g = [a[i + 1] for i, x in enumerate(a) if x == "--gran" and i + 1 < len(a)]
    p = [a[i + 1] for i, x in enumerate(a) if x == "--papel" and i + 1 < len(a)]
    main(g or None, p or None, "--json" in a)
