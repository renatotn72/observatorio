"""As features de atencao valem alguma coisa? Dois testes, mesma regua.

TESTE A -- AGITACAO: as 8 features de noticia/atencao acrescentam AUC fora da
amostra ao modelo de 5 features de preco e calendario? O numero que importa e
o DELTA, nao o AUC absoluto: um modelo com 13 features sempre ajusta melhor
dentro da amostra.

TESTE B -- DIRECAO: pesar por POPULARIDADE (espalhamento) bate pesar por
NOVIDADE? Essa e a pergunta do usuario sobre o desenho original do TCC. Mede
IC de Spearman entre sinal e retorno anormal do dia seguinte, com os dois
esquemas de peso, na mesma amostra.

AMBOS EXIGEM historico de noticia casado com retorno. Sem isso o script sai
dizendo o que falta, em vez de inventar numero.
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import numpy as np                                            # noqa: E402

from obs import atencao, volatility as vol                    # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.label import abnormal_returns                        # noqa: E402

MIN_EVENTOS = 120


def amostra(con):
    """(ticker, data, asof_ts) de cada dia-papel com noticia pontuada."""
    rows = con.execute("""
        SELECT m.ticker, date(a.published_ts,'unixepoch') d,
               MAX(a.published_ts) ts, COUNT(*) n
        FROM mentions m
        JOIN articles a ON a.id = m.article_id
        JOIN scores sc ON sc.article_id = a.id AND sc.ticker = m.ticker
        WHERE m.ticker != '__none__'
        GROUP BY m.ticker, d ORDER BY d""").fetchall()
    return [(r["ticker"], r["d"], r["ts"], r["n"]) for r in rows]


def teste_b_direcao(con, ab):
    """Popularidade bate novidade como peso na DIRECAO?

    Monta o mesmo sinal com dois esquemas e compara o IC de Spearman contra o
    retorno anormal do dia seguinte:
        NOVIDADE      w *= 1/(1+rank)^0.5          (o que o sistema faz hoje)
        POPULARIDADE  w *= fontes_efetivas          (a proposta do TCC)
        AMBOS         w *= novidade * fontes_efetivas
    """
    rows = con.execute("""
        SELECT sc.ticker, date(a.published_ts,'unixepoch') d, sc.s, sc.magnitude,
               sc.novelty, a.cluster_id, a.domain
        FROM scores sc JOIN articles a ON a.id = sc.article_id
        WHERE sc.ticker != '__none__'""").fetchall()
    porta: dict[tuple, list] = {}
    clusters: dict[int, list[str]] = {}
    for r in rows:
        porta.setdefault((r["ticker"], r["d"]), []).append(r)
        if r["cluster_id"] is not None:
            clusters.setdefault(r["cluster_id"], []).append(r["domain"] or "")

    def z(itens, esquema):
        num = den = 0.0
        for r in itens:
            pop = atencao.fontes_efetivas(clusters.get(r["cluster_id"], [r["domain"] or ""]))
            w = r["magnitude"] * {"novidade": r["novelty"],
                                  "popularidade": pop,
                                  "ambos": r["novelty"] * pop}[esquema]
            num += r["s"] * w
            den += w
        return num / den if den > 0 else 0.0

    saida = {}
    for esquema in ("novidade", "popularidade", "ambos"):
        xs, ys = [], []
        for (tkr, d), itens in porta.items():
            serie = ab.get(tkr) or {}
            datas = sorted(serie)
            if d not in serie:
                continue
            i = datas.index(d)
            if i + 1 >= len(datas):
                continue
            xs.append(z(itens, esquema))
            ys.append(serie[datas[i + 1]])
        from obs.assimetria import _spearman
        saida[esquema] = (_spearman(xs, ys) if len(xs) >= 3 else None, len(xs))
    return saida


def main():
    con = connect()
    am = amostra(con)
    print(f"dias-papel com noticia pontuada: {len(am)}")
    if len(am) < MIN_EVENTOS:
        print(f"\nINSUFICIENTE. Preciso de {MIN_EVENTOS}+ para medir qualquer")
        print("uma das duas hipoteses; tenho", len(am), "- e nenhum numero que")
        print("eu produzisse com esta amostra significaria algo.")
        print("\nO que falta e historico de noticia, nao codigo:")
        print("    python3 -m obs.cli backfill --dias 365")
        print("\nAs features ja estao implementadas e verificadas:")
        ex = atencao.painel_atencao(con, am[0][0], am[0][2]) if am else {}
        for k, v in ex.items():
            print(f"    {k:<20} {v}")
        con.close()
        return

    ab = abnormal_returns(con)
    drv = vol.panel_vol(con)
    X5, X13, y = [], [], []
    for tkr, d, ts, _n in am:
        serie = ab.get(tkr) or {}
        datas = sorted(serie)
        if d not in serie:
            continue
        i = datas.index(d)
        if i < 21 or i + 1 >= len(datas):
            continue
        base = vol.build_features(serie, datas, i, drv, target_date=datas[i + 1])
        if base is None:
            continue
        nt = atencao.painel_atencao(con, tkr, ts)
        cheio = vol.build_features(serie, datas, i, drv, noticia=nt,
                                   target_date=datas[i + 1])
        limiar = np.quantile([abs(serie[x]) for x in datas[:i + 1]], vol.VOL_QUANTIL)
        X5.append(base)
        X13.append(cheio)
        y.append(1.0 if abs(serie[datas[i + 1]]) > limiar else 0.0)

    print(f"observacoes utilizaveis: {len(y)}  taxa-base: {np.mean(y):.3f}")
    if len(y) < MIN_EVENTOS:
        print("INSUFICIENTE apos alinhar com preco.")
        con.close()
        return

    corte = int(len(y) * 0.6)
    for nome, X in (("5 features (preco+calendario)", X5),
                    ("13 features (+ noticia e atencao)", X13)):
        Xa, ya = np.array(X), np.array(y)
        mod = vol.logit_fit(Xa[:corte], ya[:corte])
        p = vol.logit_predict(mod, Xa[corte:])
        print(f"  {nome:<36} AUC_oos = {vol._auc(p, ya[corte:]):.4f}")

    print("\n=== TESTE B -- direcao: popularidade x novidade ===")
    for esquema, (ic, n) in teste_b_direcao(con, ab).items():
        ic_txt = f"{ic:+.4f}" if ic is not None else "n/d"
        print(f"  peso por {esquema:<14} IC = {ic_txt}   n = {n}")
    print("  (IC contra retorno anormal de D+1; so compara entre si, "
          "nao e veredito isolado)")
    con.close()


if __name__ == "__main__":
    main()
