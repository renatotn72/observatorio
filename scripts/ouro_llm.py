"""Lexico x LLM no mesmo conjunto-ouro. Qual merece ser o scorer padrao?

O lexico esta documentado em score.py como "o baseline honesto: roda offline,
sem dependencia, e e fraco -- e justamente por isso serve de piso a ser
batido". Ninguem tinha batido porque ninguem tinha medido. Este script mede.

A CONTAMINACAO QUE ESTE TESTE *NAO* RESOLVE -- leia antes de confiar
Um modelo treinado ate hoje SABE o que aconteceu com o papel. Numa manchete de
2026 ele pode estar lembrando do desfecho em vez de lendo o texto. O prompt
proibe inferir data e nunca pede desfecho, mas proibicao nao e garantia.
Entao: acuracia alta aqui prova que o LLM LE MELHOR, nao que ele PREVE melhor.
A prova de previsao so vem do estudo de evento, em janela posterior ao cutoff.
"""
import sys

sys.path.insert(0, "/mnt/nvmep2/home/rtnati/Downloads/projeto_final/observatorio")
import json                                                   # noqa: E402
import time                                                   # noqa: E402

from ouro_direcao import acerta, rotula                       # noqa: E402
from obs.db import connect                                    # noqa: E402
from obs.score import score_lexicon, score_llm                # noqa: E402


def main(limite=None):
    con = connect()
    rows = con.execute("""
        SELECT a.id, a.title, sc.ticker FROM scores sc
        JOIN articles a ON a.id = sc.article_id
        WHERE sc.scorer='lexicon' AND sc.ticker != '__none__'
        ORDER BY a.published_ts DESC""").fetchall()
    con.close()

    ouro = []
    for r in rows:
        rot, regra = rotula(r["title"])
        if rot is not None:
            ouro.append({"titulo": r["title"], "ticker": r["ticker"],
                         "rotulo": rot, "regra": regra})
    if limite:
        ouro = ouro[:limite]
    print(f"conjunto-ouro: {len(ouro)} casos\n", flush=True)

    falhas = 0
    for i, o in enumerate(ouro, 1):
        o["s_lex"] = score_lexicon(o["titulo"], None, o["ticker"])["s"]
        try:
            r = score_llm(o["titulo"], None, o["ticker"])
            o["s_llm"] = r.get("s")
            raw = json.loads(r.get("raw") or "{}")
            o["papel"] = raw.get("papel_no_fato")
        except Exception as e:                               # noqa: BLE001
            o["s_llm"] = None
            o["papel"] = f"erro: {type(e).__name__}"
            falhas += 1
        if i % 20 == 0:
            print(f"  ... {i}/{len(ouro)}", flush=True)
        time.sleep(0.15)

    val = [o for o in ouro if o["s_llm"] is not None]
    n = len(val)
    if not n:
        print("nenhuma resposta do LLM"); return
    a_lex = sum(acerta(o["s_lex"], o["rotulo"]) for o in val)
    a_llm = sum(acerta(o["s_llm"], o["rotulo"]) for o in val)
    print(f"\nrespostas validas: {n} ({falhas} falhas)\n")
    print(f"{'scorer':<12}{'acertos':>9}{'em 100':>9}")
    print(f"  {'lexico':<10}{a_lex:>9}{100*a_lex/n:>8.1f}")
    print(f"  {'LLM':<10}{a_llm:>9}{100*a_llm/n:>8.1f}")
    print(f"  {'diferenca':<10}{a_llm-a_lex:>+9}{100*(a_llm-a_lex)/n:>+8.1f}")

    # Onde discordam e o que importa: mostra quem acertou
    disc = [o for o in val if (o["s_lex"] > 0) != (o["s_llm"] > 0)
            or abs(o["s_lex"] - o["s_llm"]) > 0.5]
    print(f"\ndiscordancias relevantes: {len(disc)}")
    print(f"{'papel':<7}{'lex':>8}{'llm':>8}  quem acertou  titulo")
    for o in sorted(disc, key=lambda x: -abs(x["s_lex"] - x["s_llm"]))[:25]:
        ql = acerta(o["s_lex"], o["rotulo"])
        qm = acerta(o["s_llm"], o["rotulo"])
        quem = "LLM" if (qm and not ql) else ("lexico" if (ql and not qm)
                else ("ambos" if ql else "nenhum"))
        print(f"  {o['ticker']:<5}{o['s_lex']:>+8.2f}{o['s_llm']:>+8.2f}"
              f"  {quem:<12}  {o['titulo'][:48]}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
