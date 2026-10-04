"""Conjunto-ouro da DIRECAO: acuracia antes x depois, por regra explicita.

POR QUE POR REGRA, E NAO "a olho"
Rotular 50 manchetes por intuicao e inauditavel: ninguem sabe depois por que
cada uma recebeu o rotulo que recebeu, e a acuracia vira opiniao. Aqui cada
rotulo vem de um PADRAO declarado, e o script imprime qual padrao decidiu cada
caso. Discordar de um rotulo passa a ser discordar de uma regra, que da para
mudar e re-rodar.

As regras sao sobre o EFEITO NO PAPEL, nunca sobre o tom:
  - a empresa e alvo de acao de terceiro (MPF, ANP, CVM, CADE, acao judicial)
    -> NEGATIVO, mesmo que o texto descreva a acao em tom neutro
  - a empresa resiste/contesta/perde numa disputa -> NEGATIVO
  - provento, recompra, contrato ganho, upgrade -> POSITIVO
  - prejuizo, queda, multa, rebaixamento, acidente -> NEGATIVO
  - retrospectiva de preco ("subiu 5% no mes") -> NEUTRO: ja aconteceu

O que nao casa com regra nenhuma fica FORA do conjunto-ouro. Preencher a
amostra com caso duvidoso rotulado no chute inflaria a acuracia das duas
medicoes e esconderia a diferenca entre elas.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re                                                     # noqa: E402

from obs.db import connect                                    # noqa: E402
from obs.util import norm                                     # noqa: E402

# (rotulo, nome da regra, padrao). Ordem importa: a primeira que casar decide.
REGRAS = [
    (0, "retrospectiva de preco",
     r"\b(suba|subiu|caiu|avancou|recuou|fechou)\b.{0,30}\b\d+[,.]?\d*\s?%"),
    (-1, "alvo de acao de orgao/justica",
     r"\b(mpf|ministerio publico|cvm|cade|ibama|anp|aneel|anatel|justica"
     r"|trf\d?|stj|stf)\b.{0,40}\b(aciona|processa|multa|autua|investiga"
     r"|abre processo|move acao|condena|suspende|embarga|notifica)\b"),
    (-1, "acao judicial contra a empresa",
     r"\b(acao civil publica|liminar|recurso|embargo|interdito|acao judicial)\b"
     r".{0,40}\bcontra\b"),
    (-1, "empresa resiste ou contesta",
     r"\b(apesar d[ao]s? resistencia|resistencia d[ao]|contesta|recorre"
     r"|vai ao governo contra|entra com recurso)\b"),
    (1, "provento ou recompra",
     r"\b(dividendo|dividendos|jcp|juros sobre (o )?capital|proventos"
     r"|recompra|bonificacao)\b"),
    (1, "upgrade ou alvo elevado",
     r"\b(upgrade|elevou (o )?preco-alvo|preco-alvo elevado|recomendacao de compra"
     r"|eleva recomendacao)\b"),
    (1, "contrato ou descoberta",
     r"\b(assina contrato|fecha contrato|vence (o )?leilao|nova descoberta"
     r"|descoberta de petroleo|contrato de)\b"),
    (-1, "prejuizo ou rebaixamento",
     r"\b(prejuizo|downgrade|rebaixou|rebaixamento|corte de recomendacao"
     r"|recuperacao judicial|calote|default)\b"),
    (-1, "acidente ou dano operacional",
     r"\b(acidente|vazamento|rompimento|incendio|paralisacao|greve"
     r"|extravasamento|interdicao)\b"),
    (1, "lucro acima do esperado",
     r"\b(lucro).{0,30}\b(recorde|acima do esperado|supera)\b"),
]


def rotula(titulo: str):
    t = norm(titulo)
    for rot, nome, pad in REGRAS:
        if re.search(pad, t):
            return rot, nome
    return None, None


def acerta(s, rotulo):
    """Direcao do score bate com o rotulo? Neutro exige |s| pequeno."""
    if rotulo == 0:
        return abs(s) < 0.15
    return (s > 0) == (rotulo > 0) and abs(s) >= 0.05


def main():
    con = connect()
    rows = con.execute("""
        SELECT a.id, a.title, sc.ticker, sc.s
        FROM scores sc JOIN articles a ON a.id = sc.article_id
        WHERE sc.scorer='lexicon' AND sc.ticker != '__none__'
        ORDER BY a.published_ts DESC""").fetchall()
    con.close()

    ouro = []
    for r in rows:
        rot, regra = rotula(r["title"])
        if rot is None:
            continue
        ouro.append({"id": r["id"], "titulo": r["title"], "ticker": r["ticker"],
                     "rotulo": rot, "regra": regra, "s_antes": r["s"]})
    print(f"menções pontuadas: {len(rows)}")
    print(f"conjunto-ouro (casaram com alguma regra): {len(ouro)}\n")
    if not ouro:
        return

    from collections import Counter
    print("composição por regra:")
    for regra, n in Counter(o["regra"] for o in ouro).most_common():
        rot = next(o["rotulo"] for o in ouro if o["regra"] == regra)
        print(f"  {n:>4}  [{'+' if rot > 0 else ('0' if rot == 0 else '-')}] {regra}")

    # ISOLA A MUDANCA. Comparar o `s` GRAVADO com o recalculado misturaria
    # todas as alteracoes de lexico desde que aquele score foi escrito. Para
    # medir SO o condicionamento ao papel, roda-se o MESMO codigo duas vezes:
    # sem ticker (regra desligada) e com ticker (regra ligada).
    from obs.score import score_lexicon, _posicao_no_fato, _aliases_norm
    from obs.util import norm as _n
    for o in ouro:
        o["s_antes"] = score_lexicon(o["titulo"], None, "")["s"]
        o["s_depois"] = score_lexicon(o["titulo"], None, o["ticker"])["s"]
        o["regra_disparou"] = _posicao_no_fato(
            _n(o["titulo"]), _aliases_norm(o["ticker"])) != 0

    ant = sum(acerta(o["s_antes"], o["rotulo"]) for o in ouro)
    dep = sum(acerta(o["s_depois"], o["rotulo"]) for o in ouro)
    n = len(ouro)
    print(f"\n{'':20}{'acertos':>9}{'em 100':>9}")
    print(f"  {'ANTES':<18}{ant:>9}{100*ant/n:>8.1f}")
    print(f"  {'DEPOIS':<18}{dep:>9}{100*dep/n:>8.1f}")
    print(f"  {'diferença':<18}{dep-ant:>+9}{100*(dep-ant)/n:>+8.1f}")

    # O SUBCONJUNTO QUE IMPORTA: onde a regra de posicao de fato disparou.
    # Na amostra inteira o efeito se dilui -- 93 dos 115 casos sao provento,
    # que a regra nem toca, e uma mudanca boa em 3 casos some no meio deles.
    alvo = [o for o in ouro if o["regra_disparou"]]
    if alvo:
        an = sum(acerta(o["s_antes"], o["rotulo"]) for o in alvo)
        dp = sum(acerta(o["s_depois"], o["rotulo"]) for o in alvo)
        print(f"\nSO onde a regra disparou ({len(alvo)} casos):")
        print(f"  ANTES  {an}/{len(alvo)} = {100*an/len(alvo):.1f} em 100")
        print(f"  DEPOIS {dp}/{len(alvo)} = {100*dp/len(alvo):.1f} em 100")
        for o in alvo:
            a_ok = "ok" if acerta(o["s_antes"], o["rotulo"]) else "ERRO"
            d_ok = "ok" if acerta(o["s_depois"], o["rotulo"]) else "ERRO"
            print(f"    [{o['ticker']}] {o['s_antes']:+.3f} ({a_ok}) -> "
                  f"{o['s_depois']:+.3f} ({d_ok})  {o['titulo'][:50]}")

    mudou = [o for o in ouro if abs(o["s_depois"] - o["s_antes"]) > 1e-9]
    print(f"\nnotícias cuja direção MUDOU: {len(mudou)}")
    mudou.sort(key=lambda o: -abs(o["s_depois"] - o["s_antes"]))
    print(f"\n{'papel':<7}{'antes':>8}{'depois':>8}  cert  titulo")
    for o in mudou[:30]:
        a_ok = "A" if acerta(o["s_antes"], o["rotulo"]) else " "
        d_ok = "D" if acerta(o["s_depois"], o["rotulo"]) else " "
        print(f"  {o['ticker']:<5}{o['s_antes']:>+8.3f}{o['s_depois']:>+8.3f}"
              f"  {a_ok}{d_ok}  {o['titulo'][:56]}")


if __name__ == "__main__":
    main()
