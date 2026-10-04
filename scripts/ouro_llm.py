"""Lexico x LLM no mesmo conjunto-ouro.

ESTE SCRIPT NAO DECIDE QUAL LEITOR DEVE SER O PADRAO. Ele decidia, e a
conclusao estava errada. Fica porque a tabela de discordancias e util para
INSPECIONAR caso a caso -- nao para escolher leitor.

O QUE ACONTECEU (rodada em data/ouro_llm.log, 115 casos)
    lexico  101 acertos  87,8 em 100
    LLM      62 acertos  53,9 em 100
Parece veredito. Nao e: o gabarito e circular.

MEDIDO em 2026-10-04 sobre os mesmos 115 casos:
  - 93 deles (81%) vem de UMA regra de ouro_direcao.py, "provento ou
    recompra", cujos cinco termos -- dividendo, dividendos, jcp, proventos,
    recompra -- estao TODOS no dicionario POS de obs/score.py, com peso
    positivo. O gabarito diz "+1 quando a manchete tem a palavra dividendo";
    o lexico pontua +0,5 por essa mesma palavra. Nao ha como errar.
  - nessa fatia o lexico acerta 98,9 em 100;
  - nas outras oito regras (22 casos) ele acerta 50,0 em 100 -- o chute.
  - 16 dos 93 casos da regra dominante sao LISTA de recomendacao ("5 acoes
    para investir em outubro e embolsar dividendos", "as 10 acoes do BTG
    Pactual"). Ali a empresa e apenas citada e o gabarito +1 esta ERRADO para
    o alvo do projeto, que e retorno anormal especifico do papel. O LLM
    devolve ~0 e e contado como erro por estar certo.

Medir leitor de noticia contra gabarito feito de palavra-chave premia quem le
palavra-chave. O resultado acima mede CONCORDANCIA COM O LEXICO, nao acerto.

E ha um segundo sinal de que o gabarito nao mede o que importa: no mesmo
banco, a forca do lexico tem IC indistinguivel de zero contra o retorno
residual realizado (scripts/evento_noticia.py: IC entre -0,10 e +0,06,
p de 0,37 a 0,93, n=77 celulas -- descritivo). Ou seja, 87,8 em 100 no
gabarito convivem com zero poder sobre o preco.

ONDE A PERGUNTA SE RESOLVE
    python3 scripts/evento_noticia.py --scorer lexicon --scorer llm
Retorno residual realizado como juiz. Ele nao sabe quais palavras cada leitor
usa. Mais a amostra humana de auditoria do ponto 2 da ordem pratica
(docs/canal-noticias.md), que e a unica forma de ter gabarito independente.

A CONTAMINACAO QUE ESTE TESTE TAMBEM NAO RESOLVE
Um modelo treinado ate hoje SABE o que aconteceu com o papel. Numa manchete de
2026 ele pode estar lembrando do desfecho em vez de lendo o texto. O prompt
proibe inferir data e nunca pede desfecho, mas proibicao nao e garantia.
Entao: acuracia alta aqui nao prova nem leitura nem previsao. A prova de
previsao so vem do estudo de evento, em janela posterior ao cutoff.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json                                                   # noqa: E402
import time                                                   # noqa: E402

import re                                                      # noqa: E402

from ouro_direcao import REGRAS, acerta, rotula               # noqa: E402
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
    print("  ^ AGREGADO ENGANA: ver a quebra por regra abaixo e o docstring.")

    # QUEBRA POR REGRA DO GABARITO. E a tabela que mostra de onde vem o
    # numero agregado: se uma regra cujos termos estao no dicionario do lexico
    # concentra a amostra, o "acerto" dele e tautologia.
    import collections
    from obs.score import POS, NEG, PHRASES
    vocab = set(POS) | set(NEG) | set(PHRASES)
    porregra = collections.defaultdict(lambda: [0, 0, 0])
    for o in val:
        r = porregra[o["regra"]]
        r[0] += 1
        r[1] += acerta(o["s_lex"], o["rotulo"])
        r[2] += acerta(o["s_llm"], o["rotulo"])
    print(f"\n{'regra do gabarito':<34}{'n':>5}{'lex':>7}{'LLM':>7}  termos no lexico")
    for nome, (tot, al, am) in sorted(porregra.items(), key=lambda kv: -kv[1][0]):
        pad = next((p for _r, nm, p in REGRAS if nm == nome), "")
        com = sorted(t for t in {x.strip() for x in re.findall(r"[a-z][a-z \-]{2,}", pad)}
                     if t.strip() in vocab)
        print(f"  {nome[:32]:<32}{tot:>5}{100*al/tot:>6.0f}%{100*am/tot:>6.0f}%"
              f"  {', '.join(com[:4]) if com else '(nenhum)'}")
    print("\n  Regra com termo no lexico = gabarito escrito com o vocabulario")
    print("  do proprio leitor avaliado. Acerto ali nao e evidencia.")

    # COMO O LLM CLASSIFICOU O PAPEL DA EMPRESA NO FATO. "apenas_citada" em
    # materia de lista de recomendacao e leitura CORRETA contada como erro.
    pap = collections.Counter(o.get("papel") for o in val)
    print("\npapel_no_fato atribuido pelo LLM:")
    for k, v in pap.most_common():
        acc = sum(acerta(o["s_llm"], o["rotulo"]) for o in val if o.get("papel") == k)
        print(f"  {str(k):<18}{v:>5} casos   acerto contra o gabarito: "
              f"{100*acc/v:>5.0f}%")

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
