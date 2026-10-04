#!/usr/bin/env python3
"""Exercita o caminho do leitor por LLM com respondedor FALSO, sem rede.

NAO MEDE ACURACIA, e a distincao importa. Acurácia de leitor se mede contra
retorno realizado (scripts/evento_noticia.py) ou contra gabarito independente
-- nunca contra resposta que o proprio teste escreveu. Aqui o alvo e outro:
provar que o ENCANAMENTO faz o que o desenho promete, caso a caso.

Doze casos, cada um amarrado a uma decisao de desenho de obs/score.py:

  1. sem autorizacao -> cai para o lexico DIZENDO que caiu
  2. schema do LLM -> schema comum, com os descontos aplicados
  3. incoerencia (prejudicada com s>0) -> nota invertida e contradicao gravada
  4. mesma materia duas vezes -> segunda leitura vem do cache, sem chamada
  5. outra materia do mesmo cluster -> reuso, sem chamada
  6. teto de chamadas -> para e deixa o resto pendente
  7. falha de rede -> par fica SEM nota, nao recebe nota de outro leitor
  8. ensemble -> cai para o lexico por materia e marca o fallback
  9. run() passa o ticker ao lexico -> a heuristica de posicao no fato roda
 10. cadeia inteira -> signals grava quem leu, extracao fica em coluna
 11. leitor sem nota na janela -> cai para o lexico em vez de esvaziar o painel
 12. porta de novidade dos alarmes recebe quem leu, nunca None

Rode com banco isolado:
    OBS_DB=/tmp/obs_test.db python3 scripts/test_score_llm.py
O proprio script define OBS_DB se nao vier definido.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "OBS_DB", os.path.join(tempfile.mkdtemp(prefix="obs_test_"), "teste.db"))

from obs import db, llm_client, score                        # noqa: E402
from obs.db import connect                                   # noqa: E402

FALHAS = []


def ok(cond, desc, detalhe=""):
    marca = "OK " if cond else "FALHOU"
    if not cond:
        FALHAS.append(desc)
    print(f"  [{marca}] {desc}" + (f"  -- {detalhe}" if detalhe else ""))


# ----------------------------------------------------------- respondedor ----
class Fake:
    """LLM de mentira. Conta chamadas e devolve o que o caso pedir."""

    def __init__(self, resposta=None, erro=None):
        self.resposta, self.erro, self.n = resposta, erro, 0

    def chat_json(self, system, user, max_tokens=1400):
        self.n += 1
        if self.erro:
            return {"ok": False, "error": self.erro, "external": True}
        return {"ok": True, "data": dict(self.resposta), "model": "fake",
                "external": True}


def liga(fake, autorizado=True):
    llm_client.enabled = lambda: ((True, "ok") if autorizado
                                  else (False, "OBS_ALLOW_EXTERNAL_LLM=1 nao autorizado"))
    llm_client.chat_json = fake.chat_json
    os.environ["OBS_LLM_MODEL"] = "fake-modelo"


def semeia(artigos):
    """Grava artigos + mencoes. `artigos`: (id, titulo, cluster_id, ticker)."""
    con = connect()
    with con:
        con.execute("DELETE FROM scores"); con.execute("DELETE FROM mentions")
        con.execute("DELETE FROM articles")
        try:
            con.execute("DELETE FROM llm_cache")
        except Exception:                                    # noqa: BLE001
            pass
        for aid, titulo, cid, tkr in artigos:
            con.execute(
                "INSERT INTO articles(id,url,title,body,domain,lang,"
                "published_ts,ingested_ts,source,simhash,cluster_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (aid, f"http://x/{aid}", titulo, None, "exemplo.com", "pt",
                 1760000000 + aid, 1760000000 + aid, "rss", aid, cid))
            con.execute("INSERT INTO mentions(article_id,ticker,relevance,"
                        "matched_alias) VALUES (?,?,?,?)", (aid, tkr, 0.9, tkr))
    con.close()


BOA = {"papel_no_fato": "beneficiada", "s": 0.6, "magnitude": 0.9,
       "event_type": "mna", "ja_precificado": False, "is_rumor": False,
       "quote": "assina contrato", "por_que": "contrato novo"}

db.init()
print("\n1. sem autorizacao: degrada para o lexico, com motivo")
liga(Fake(BOA), autorizado=False)
efetivo, motivo = score.resolver("llm", verbose=False)
ok(efetivo == "lexicon", "resolver('llm') -> lexicon", efetivo)
ok("indisponivel" in motivo, "motivo explicito", motivo)

print("\n2. schema do LLM -> schema comum, com descontos")
liga(Fake(BOA))
r = score.score_llm("Empresa assina contrato bilionario", None, "PETR4",
                    usar_cache=False)
ok(r["s"] == 0.6 and r["magnitude"] == 0.9, "nota e magnitude preservadas", r)
ok(r["papel_no_fato"] == "beneficiada", "papel_no_fato em campo proprio")
rumor = dict(BOA, is_rumor=True, ja_precificado=True)
liga(Fake(rumor))
r2 = score.score_llm("Rumor de fusao", None, "PETR4", usar_cache=False)
# a magnitude e gravada arredondada em 4 casas (round no schema de saida)
ok(r2["magnitude"] == round(0.9 * 0.25 * 0.45, 4),
   "rumor e ja_precificado cortam a magnitude", r2["magnitude"])
ok(r2["ja_precificado"] == 1 and r2["is_rumor"] == 1, "flags em coluna")

print("\n3. incoerencia: prejudicada com s>0 e invertida e registrada")
liga(Fake({**BOA, "papel_no_fato": "prejudicada", "s": 0.35}))
r3 = score.score_llm("ANP avanca apesar de resistencia da Petrobras", None,
                     "PETR4", usar_cache=False)
ok(r3["s"] < 0, "nota invertida para o lado da empresa", r3["s"])
ok("incoerencia" in json.loads(r3["raw"]), "contradicao gravada no raw")

print("\n4. cache: a segunda leitura da mesma materia nao chama a rede")
f = Fake(BOA); liga(f)
score.score_llm("Materia unica para cache", None, "VALE3")
antes = f.n
score.score_llm("Materia unica para cache", None, "VALE3")
ok(f.n == antes, f"segunda leitura sem chamada (chamadas={f.n})")
score.score_llm("Materia unica para cache", None, "ITUB4")
ok(f.n == antes + 1, "ticker diferente e leitura diferente", f.n)

print("\n5. reuso por cluster: copia nao paga leitura")
semeia([(1, "Vale anuncia acordo", 7, "VALE3"),
        (2, "Vale anuncia acordo (republicado)", 7, "VALE3"),
        (3, "Vale anuncia acordo (terceira copia)", 7, "VALE3")])
f = Fake(BOA); liga(f)
n = score.run(scorer="llm", verbose=False)
ok(n == 3, "tres pares pontuados", n)
ok(f.n == 1, f"uma chamada para tres copias (chamadas={f.n})")
ok(score.CONTADORES["cluster"] == 2, "duas leituras reaproveitadas",
   score.CONTADORES["cluster"])
con = connect()
raws = [json.loads(r[0]) for r in con.execute(
    "SELECT raw FROM scores WHERE scorer='llm'").fetchall()]
con.close()
ok(sum(1 for x in raws if "reuso_cluster" in x) == 2, "reuso marcado no raw")

print("\n6. teto de chamadas: para e deixa o resto pendente")
semeia([(i, f"Materia distinta numero {i}", None, "PETR4") for i in range(1, 6)])
f = Fake(BOA); liga(f)
n = score.run(scorer="llm", max_chamadas=2, verbose=False)
ok(f.n == 2, f"respeitou o teto de 2 chamadas (chamadas={f.n})")
ok(n == 2, "gravou so o que leu", n)
ok(score.CONTADORES["teto"] == 3, "tres pares deixados para depois",
   score.CONTADORES["teto"])
n2 = score.run(scorer="llm", max_chamadas=10, verbose=False)
ok(n2 == 3, "a rodada seguinte retoma os pendentes", n2)

print("\n7. falha de rede: par fica SEM nota, nao recebe nota de outro leitor")
semeia([(1, "Petrobras tem prejuizo no trimestre", None, "PETR4")])
f = Fake(None, erro="connection refused"); liga(f)
score.TENTATIVAS, orig = 1, score.TENTATIVAS
n = score.run(scorer="llm", verbose=False)
score.TENTATIVAS = orig
ok(n == 0, "nada gravado", n)
con = connect()
ok(con.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0,
   "nenhuma nota de lexico gravada sob o nome 'llm'")
con.close()

print("\n8. ensemble cai para o lexico por materia, e marca o fallback")
f = Fake(None, erro="proxy fora do ar"); liga(f)
score.TENTATIVAS, orig = 1, score.TENTATIVAS
r8 = score.score_ensemble("Petrobras tem prejuizo recorde no trimestre", None, "PETR4")
score.TENTATIVAS = orig
ok(r8["s"] < 0, "nota do lexico assumiu", r8["s"])
ok(json.loads(r8["raw"]).get("fallback") == "lexicon", "fallback registrado")

print("\n9. run() passa o ticker ao lexico (heuristica de posicao no fato)")
titulo = ("ANP avanca para reduzir concentracao no mercado de gas apesar "
          "de resistencia da Petrobras")
semeia([(1, titulo, None, "PETR4")])
score.run(scorer="lexicon", verbose=False)
con = connect()
s_pipeline = con.execute("SELECT s FROM scores WHERE scorer='lexicon'").fetchone()[0]
con.close()
sem_ticker = score.score_lexicon(titulo, None, "")["s"]
ok(sem_ticker > 0, "sem o ticker o lexico erra o lado (+)", sem_ticker)
ok(s_pipeline < 0, "no pipeline a correcao roda e o lado fica certo",
   s_pipeline)

print("\n10. a cadeia inteira: score llm -> agregacao -> signals.scorer")
# Verifica o que a troca de leitor mais arrisca: `aggregate` filtra por
# `sc.scorer=?`, entao leitor novo sem nota gravada esvaziaria o painel. E a
# coluna signals.scorer e o que distingue, depois, sinal lido pelo LLM de
# sinal lido pelo lexico na MESMA tabela.
import time                                                  # noqa: E402
from obs import aggregate                                    # noqa: E402

f = Fake(BOA); liga(f)
con = connect()
with con:
    con.execute("DELETE FROM signals")
con.close()
agora = int(time.time()) - 600
con = connect()
with con:
    con.execute("DELETE FROM scores"); con.execute("DELETE FROM mentions")
    con.execute("DELETE FROM articles")
    con.execute(
        "INSERT INTO articles(id,url,title,body,domain,lang,published_ts,"
        "ingested_ts,source,simhash,cluster_id) VALUES "
        "(1,'http://x/9','Petrobras assina contrato bilionario',NULL,"
        "'exemplo.com','pt',?,?,'rss',9,NULL)", (agora, agora))
    con.execute("INSERT INTO mentions(article_id,ticker,relevance,matched_alias)"
                " VALUES (1,'PETR4',0.9,'Petrobras')")
con.close()
ok(score.resolver()[0] == "llm", "com autorizacao, o padrao e o llm")
score.run(verbose=False)
d = aggregate.compute("PETR4")
ok(d["scorer"] == "llm", "agregacao leu as notas do llm", d["scorer"])
ok(d["n_articles"] == 1, "a materia entrou no sinal", d["n_articles"])
aggregate.run(verbose=False)
con = connect()
r = con.execute("SELECT scorer FROM signals WHERE ticker='PETR4'").fetchone()
col = con.execute("SELECT papel_no_fato,ja_precificado,is_rumor,quote "
                  "FROM scores").fetchone()
con.close()
ok(r and r["scorer"] == "llm", "signals gravou quem leu",
   r["scorer"] if r else None)
ok(col["papel_no_fato"] == "beneficiada" and col["quote"],
   "extracao estruturada em coluna, consultavel", dict(col))

print("\n11. cobertura: leitor sem nota na janela nao esvazia o painel")
# Cenario real da virada: banco cheio de nota do lexico, leitor novo sem
# nenhuma. `escolher_scorer` tem de preferir o lexico e DIZER por que.
con = connect()
with con:
    con.execute("DELETE FROM scores")
    con.execute("INSERT INTO scores(article_id,ticker,scorer,s,magnitude,"
                "event_type,novelty) VALUES (1,'PETR4','lexicon',0.4,0.5,"
                "'mna',1.0)")
con.close()
efetivo, motivo = aggregate.escolher_scorer(scorer="llm")
ok(efetivo == "lexicon", "cai para o lexico por cobertura", efetivo)
ok("sem nota na janela" in motivo, "motivo diz que foi cobertura", motivo)

print("\n12. a porta de novidade recebe QUEM LEU, nunca None")
# REGRESSAO: com --scorer opcional, `cmd_alarms` passava None adiante.
# `_has_novelty` filtra `sc.scorer=?`, entao None nao acha linha nenhuma e
# TODO alarme e barrado em silencio -- como se nunca houvesse primeira
# reportagem. O sinal carrega `scorer`, e e dele que a porta deve tirar.
from obs import alarms                                       # noqa: E402

vistos = []
orig_nov = alarms._has_novelty
alarms._has_novelty = lambda con, tkr, sc, **k: (vistos.append(sc) or True)
alarms.evaluate([{"ticker": "PETR4", "scorer": "llm", "n_eff": 9.0,
                  "calibrated": 1, "p_up": 0.9, "base_up": 0.3,
                  "p_down": 0.01, "base_down": 0.3, "z": 0.8,
                  "dispersion": 0.1, "n_articles": 1, "items": []}])
alarms._has_novelty = orig_nov
ok(vistos == ["llm"], "a porta usou o leitor gravado no sinal", vistos)

print()
if FALHAS:
    print(f"{len(FALHAS)} caso(s) FALHARAM:")
    for d in FALHAS:
        print(f"  - {d}")
    sys.exit(1)
print("todos os casos passaram")
