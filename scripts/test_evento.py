#!/usr/bin/env python3
"""Classificacao de evento em duas dimensoes: antes e depois, caso a caso.

O CASO 4.1 e o motivo deste arquivo existir. Materia real de 30/09/2026:

    "MPF apresenta novo recurso contra exploracao de petroleo na Foz do
     Amazonas pela Petrobras (PETR4)"
    Corpo: recurso protocolado no TRF1 na segunda (28) pedindo paralisacao da
    perfuracao no bloco FZA-M-59, contestando a decisao da Justica Federal do
    Amapa de quarta (23) que extinguiu a acao civil publica do MPF contra
    Uniao, Ibama e Petrobras.

    ANTES : event_type = "operational". Um campo so, e errado -- nada ali e
            operacao da empresa; e processo judicial. E nenhuma dimensao
            temporal: o sistema nao tinha como dizer que o fato ja ocorreu E
            que ainda pode mudar.
    DEPOIS: tipo_evento = "judicial"; orientacao = {passado, futuro}.
            Passado porque a decisao de 23/09 e o protocolo de 28/09 estao
            consumados. Futuro porque o recurso ainda pode paralisar a
            perfuracao.

Rode com banco isolado:
    OBS_DB=/tmp/obs_evt.db python3 scripts/test_evento.py
O proprio script define OBS_DB se nao vier definido.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "OBS_DB", os.path.join(tempfile.mkdtemp(prefix="obs_evt_"), "teste.db"))

from obs import db, evento, score                            # noqa: E402
from obs.db import connect                                   # noqa: E402
from obs.util import sem_html                                # noqa: E402

FALHAS = []


def ok(cond, desc, det=""):
    marca = "OK " if cond else "FALHOU"
    if not cond:
        FALHAS.append(desc)
    print(f"  [{marca}] {desc}" + (f"  -- {det}" if det else ""))


# ------------------------------------------------------------- caso 4.1 -----
T41 = ("MPF apresenta novo recurso contra exploração de petróleo na Foz do "
       "Amazonas pela Petrobras (PETR4)")
C41 = ("Recurso protocolado no TRF1 na segunda (28) pedindo paralisação da "
       "perfuração no bloco FZA-M-59, contestando a decisão da Justiça Federal "
       "do Amapá de quarta (23) que extinguiu a ação civil pública do MPF "
       "contra União, Ibama e Petrobras.")

print("\n1. CASO 4.1 -- MPF / bloco FZA-M-59")
antes = score.score_lexicon(T41, C41, "PETR4")
print(f"     ANTES  : event_type={antes['event_type']!r}, "
      f"sem dimensao temporal (o campo nao existia no pipeline)")
depois = evento.de_texto(T41, C41, antes["event_type"])
print(f"     DEPOIS : tipo_evento={depois['tipo_evento']!r}, "
      f"orientacao={depois['orientacao']}")
ok(antes["event_type"] == "operational",
   "antes: o legado classificava como 'operational' -- errado", antes["event_type"])
ok(depois["tipo_evento"] == evento.JUDICIAL, "depois: tipo judicial")
ok(sorted(depois["orientacao"]) == ["futuro", "passado"],
   "depois: PASSADO + FUTURO, as duas marcas", depois["orientacao"])
ok(evento.PRESENTE not in depois["orientacao"],
   "nao marca presente: nao ha fato em curso, ha um ja feito e um por vir")
so_titulo = evento.de_texto(T41)
ok(sorted(so_titulo["orientacao"]) == ["futuro", "passado"],
   "a manchete sozinha ja carrega os dois tempos", so_titulo["orientacao"])

print("\n2. orientacao e CONJUNTO, nao campo unico")
casos = [
    ("Petrobras divulgará balanço do 3T26 em 28 de outubro", [evento.FUTURO]),
    ("Vale fecha acordo e pagou dividendo ontem", [evento.PASSADO]),
    ("Petrobras negocia venda de refinaria, em curso desde julho",
     [evento.PRESENTE]),
]
for titulo, esperado in casos:
    got = evento.orientacao(titulo)
    ok(got == esperado, f"{esperado} <- {titulo[:52]}", got)

print("\n3. orgao como ATOR x orgao como FONTE")
# O legado joga tudo que cita uma agencia no balde `regulatory`, e o mapa
# manda regulatory -> judicial. Sem a guarda, boletim de producao da ANP
# ganhava icone de processo.
org = [
    ("ANP aprova delimitação de novas áreas de petróleo", "regulatory",
     evento.JUDICIAL, "ato administrativo"),
    ("T4F fecha capital após CVM aprovar cancelamento de registro", "regulatory",
     evento.JUDICIAL, "decisão de agência"),
    ("Petrobras vai ao Governo contra ANP para manter poder no mercado de gás",
     "regulatory", evento.JUDICIAL, "disputa contra o órgão"),
    ("Produção de petróleo e gás natural supera marca inédita, diz ANP",
     "regulatory", evento.CORPORATIVO, "agência como FONTE do dado"),
]
for titulo, legado, esperado, porque in org:
    got = evento.tipo(titulo, legado)
    ok(got == esperado, f"{esperado:<12} ({porque})", f"{got} <- {titulo[:46]}")

print("\n4. HTML no corpo nao pode virar marca temporal")
# O MECANISMO REAL, medido em 3 de 400 corpos: a entidade numerica `&#8230;`
# (reticencias) normaliza para "8230", entao "em &#8230;" vira "em 8230" e
# casa com o padrao `em \\d{4}`, marcando PASSADO falso.
#
# E O QUE *NAO* ACONTECE, registrado para ninguem reintroduzir a crenca: ano
# dentro de URL de imagem ("/bs/2025/") NAO cria PASSADO -- o padrao exige
# "em " imediatamente antes do ano. Medido no banco: `em \\d{4}` casa 8 vezes
# no corpo sujo e 9 no limpo.
# A frase so pode ter UM sinal de passado -- a propria entidade. "fechou",
# "anunciou" e afins marcariam PASSADO sozinhos e o teste passaria por engano.
entidade = "A empresa projeta crescer em &#8230; no próximo ano."
ok(evento.PASSADO in evento.orientacao(entidade),
   "com a entidade crua, 'em 8230' vira PASSADO falso",
   evento.orientacao(entidade))
ok(evento.PASSADO not in evento.orientacao(sem_html(entidade)),
   "limpa, a reticencia nao marca tempo nenhum",
   evento.orientacao(sem_html(entidade)))

url = ('<img src="https://s2.glbimg.com/internal_photos/bs/2025/K/foto.jpg"> '
       'A empresa projeta investir mais no próximo ano.')
ok(evento.PASSADO not in evento.orientacao(url),
   "ano em URL NAO cria PASSADO: o padrao exige 'em' antes",
   evento.orientacao(url))
ok("glbimg" not in sem_html(url) and "projeta" in sem_html(url),
   "a limpeza tira o markup e preserva o texto", sem_html(url)[:52])
ok(evento.de_texto("Empresa projeta investimento", url)["orientacao"]
   == [evento.FUTURO], "de_texto limpa antes de classificar")

print("\n5. a classificacao PERSISTE pelo pipeline, nao so em memoria")
db.init()
con = connect()
with con:
    con.execute("DELETE FROM scores"); con.execute("DELETE FROM mentions")
    con.execute("DELETE FROM articles")
    con.execute(
        "INSERT INTO articles(id,url,title,body,domain,lang,published_ts,"
        "ingested_ts,source,simhash,cluster_id) VALUES "
        "(1,'http://x/41',?,?,'exemplo.com','pt',1790000000,1790000000,"
        "'rss',41,NULL)", (T41, C41))
    con.execute("INSERT INTO mentions(article_id,ticker,relevance,matched_alias)"
                " VALUES (1,'PETR4',0.9,'Petrobras')")
con.close()
score.run(scorer="lexicon", verbose=False)
con = connect()
r = con.execute("SELECT tipo_evento, orientacao, event_type FROM scores").fetchone()
con.close()
ok(r["tipo_evento"] == evento.JUDICIAL, "tipo_evento gravado", r["tipo_evento"])
ok(sorted((r["orientacao"] or "").split(",")) == ["futuro", "passado"],
   "orientacao gravada como conjunto", r["orientacao"])
ok(r["event_type"] == "operational",
   "o campo legado fica intacto, para nao quebrar medicao antiga",
   r["event_type"])

print("\n6. repontuar NAO apaga as duas dimensoes")
# INSERT OR REPLACE apaga a linha e insere outra: coluna omitida volta a NULL.
# Era assim que `limpar --aplicar` zerava a classificacao do acervo inteiro.
con = connect()
with con:
    con.execute("DELETE FROM scores")
con.close()
score.run(scorer="lexicon", verbose=False)
con = connect()
r2 = con.execute("SELECT tipo_evento, orientacao FROM scores").fetchone()
con.close()
ok(r2["tipo_evento"] == evento.JUDICIAL and r2["orientacao"],
   "sobrevive a uma repontuacao completa",
   f"{r2['tipo_evento']} / {r2['orientacao']}")

print("\n7. reclassificar o acervo e idempotente")
p1 = evento.reclassificar(aplicar=True, verbose=False)
p2 = evento.reclassificar(aplicar=True, verbose=False)
ok(p2["alteracoes"] == 0, "segunda passada nao muda nada",
   f"1a: {p1['alteracoes']} alteracoes, 2a: {p2['alteracoes']}")
ok(p1["sem_classificacao"] == 0, "nenhuma linha sem classificacao")

print("\n8. a legenda cobre todos os tipos que o classificador produz")
leg = evento.legenda()
ids = {x["id"] for x in leg["tipos"]}
ok(ids == set(evento.ICONES), "legenda e ICONES nao divergem", ids)
ok(all(x.get("forma") for x in leg["tipos"]),
   "todo tipo tem forma geometrica para o grafico desenhar")
ok({x["id"] for x in leg["orientacoes"]}
   == {evento.PASSADO, evento.PRESENTE, evento.FUTURO},
   "legenda temporal completa")

print("\n9. o nome do VEICULO nao e o TIPO do evento")
# DEFEITO MEDIDO em 2026-10-04, na auditoria dos 6 casos `calendario` do
# acervo: a regra casava "fato relevante" e "comunicado ao mercado", que sao os
# NOMES DO DOCUMENTO que a empresa arquiva na CVM, nao eventos de calendario.
# Como esses termos aparecem no corpo de quase qualquer anuncio corporativo,
# 6 de 6 materias marcadas `calendario` eram outra coisa -- descoberta de gas,
# fabrica de baterias, venda de operacao, plano de investimento, aquisicao.
# O tipo tinha 100% de erro, e com n=6 nenhuma estatistica acharia isso.
veic = [
    ("Petrobras anuncia descoberta de gás em águas profundas; veja o fato "
     "relevante", evento.CORPORATIVO, "'fato relevante' é o veículo, não o tipo"),
    ("WEG anuncia plano de investimento de R$ 840 milhões; comunicado ao "
     "mercado na CVM", evento.CORPORATIVO, "'comunicado ao mercado' idem"),
    ("Itaú divulgará o balanço do 3T26 em 5 de novembro",
     evento.CALENDARIO, "anuncia DATA de divulgação: é calendário"),
    ("Vale passará a divulgar relatório de vendas junto com resultados",
     evento.CALENDARIO, "muda a AGENDA de divulgação"),
    ("Petrobras divulga calendário de eventos de 2027",
     evento.CALENDARIO, "calendário explícito"),
]
for titulo, esperado, porque in veic:
    got = evento.tipo(titulo)
    ok(got == esperado, f"{esperado:<12} ({porque})", f"{got} <- {titulo[:46]}")

print("\n10. 'congresso' de area nao e o Congresso Nacional")
# Medido: 53 artigos do acervo contem "congresso", 7 contem "congresso
# nacional". 87% sao congresso DE AREA, e um deles -- "Congresso IBGC: o ser
# humano na lideranca da transformacao" -- estava marcado como ato legislativo.
# Idem "senado": 103 artigos citam a palavra e a maioria e cobertura
# ELEITORAL. A regra passou a exigir a casa AGINDO (aprova, rejeita, vota),
# nao a casa citada.
cong = [
    ("Congresso IBGC: o ser humano na liderança da transformação",
     evento.CORPORATIVO, "congresso de área"),
    ("Congresso Nacional aprova a LDO de 2027",
     evento.LEGISLATIVO, "o Legislativo de fato"),
    ("Projeto de lei muda tributação de dividendos",
     evento.LEGISLATIVO, "projeto de lei continua valendo"),
    ("Senado aprova marco legal do mercado de carbono",
     evento.LEGISLATIVO, "a casa AGINDO continua valendo"),
    ("Quem está na frente para senador em Pernambuco? Veja as pesquisas",
     evento.CORPORATIVO, "cobertura eleitoral não é ato legislativo"),
    ("Eleições 2026: bancada feminina pode chegar a 22 integrantes no Senado",
     evento.CORPORATIVO, "a casa MENCIONADA não basta"),
]
for titulo, esperado, porque in cong:
    got = evento.tipo(titulo)
    ok(got == esperado, f"{esperado:<12} ({porque})", f"{got} <- {titulo[:46]}")

print()
if FALHAS:
    print(f"{len(FALHAS)} caso(s) FALHARAM:")
    for d in FALHAS:
        print(f"  - {d}")
    sys.exit(1)
print("todos os casos passaram")
