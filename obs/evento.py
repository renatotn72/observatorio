"""Classificacao de evento em DUAS dimensoes independentes.

O PROBLEMA
Hoje todo evento e tratado como "noticia que explica o preco". Duas coisas
faltam, e elas sao ortogonais:

  A) ORIENTACAO TEMPORAL -- a que tempo o conteudo se refere. Uma decisao
     judicial ja proferida explica movimento PASSADO; um recurso pendente
     aponta risco FUTURO. A MESMA materia pode ter as duas marcas, e por isso
     orientacao e CONJUNTO, nunca campo unico.

  B) TIPO DE EVENTO -- de que natureza e o fato. O `event_type` atual tem 12
     valores mas 44% caem em `unclassified`, e nao distingue judicial de
     operacional: MEDIDO, "MPF apresenta novo recurso contra exploracao de
     petroleo" estava classificado como `operational`.

POR QUE SEPARAR
Orientacao e tipo respondem perguntas diferentes e erram de formas diferentes.
Juntar as duas num campo so obriga a escolher entre "judicial" e "futuro"
quando a resposta certa e as duas.

CUSTO DE ERRAR E BAIXO, de proposito: nenhuma das duas entra no sinal. Elas
descrevem e filtram. Classificacao errada polui a leitura da tela, nao a
medicao -- diferente do `s`, onde errar o lado estraga o resultado.

ORDEM: regra primeiro, LLM depois. O que e inequivoco (TRF, STJ, liminar,
projeto de lei) nao precisa de modelo; o resto precisa, porque orientacao
temporal exige leitura -- "recurso protocolado na segunda contestando decisao
de quarta" tem dois tempos e nenhuma palavra-chave os separa.
"""
from __future__ import annotations
import re

from .util import norm, sem_html

# ------------------------------------------------------------- orientacao ---
PASSADO, PRESENTE, FUTURO = "passado", "presente", "futuro"

# O PRESENTE JORNALISTICO E PASSADO. Manchete escreve "Petrobras anuncia
# dividendo" para um ato que ja ocorreu -- exigir "anunciou" perderia a maioria
# dos casos reais.
MARCAS_PASSADO = (
    r"\b(anunci(?:a|ou)|divulg(?:a|ou)|registr(?:a|ou)|fech(?:a|ou)"
    r"|encerr(?:a|ou)|conclu(?:i|iu)|aprov(?:a|ou)|decid(?:e|iu)"
    r"|protocol(?:a|ou)|apresent(?:a|ou)|assin(?:a|ou)|pag(?:a|ou)"
    r"|obt(?:em|eve)|exting(?:ue|uiu)|conden(?:a|ou)|determin(?:a|ou)"
    r"|public(?:a|ou)|elev(?:a|ou)|reduz(?:iu)?|teve|foi)\b",
    r"\b(no \d+t\d+|no trimestre|no ano passado|em \d{4}|ontem"
    r"|na semana passada|na (?:segunda|terca|quarta|quinta|sexta) passada)\b",
    # NAO incluir "balanco do|resultado do" aqui: sao marcas de TOPICO, nao de
    # tempo. MEDIDO: "Vale divulgara balanco do 3T26 em 28 de outubro" era
    # classificada como PASSADO por causa de "balanco do", embora "divulgara"
    # seja futuro explicito.
)
MARCAS_PRESENTE = (
    r"\b(negocia|discute|avalia|analisa|opera|enfrenta|disputa|tramita"
    r"|esta em|segue em|mantem)\b",
    r"\b(em curso|em andamento|nesta (?:segunda|terca|quarta|quinta|sexta)|hoje)\b",
)
MARCAS_FUTURO = (
    r"\b(pode|podera|deve|devera|planeja|pretende|projeta|preve|estima"
    r"|espera|vai|ira|aguarda|solicita|pede|pleiteia)\b",
    r"\b(guidance|projecao|perspectiva|outlook|meta para|previsao)\b",
    r"\b(recurso|apelacao|embargos|liminar pendente|ainda pode|a decidir"
    r"|em julgamento|sera julgado|aguarda decisao)\b",
    r"\b(a partir de|no proximo|no futuro|ate \d{4})\b",
    # Futuro explicito por flexao: divulgara, sera, pagara, julgara...
    r"\b\w+(?:ara|erao|ira|irao|era|arao)\b",
    r"\b(sinaliza|promete|anuncia que (?:vai|ira)|preve que)\b",
)

# ------------------------------------------------------------------ tipo ---
CORPORATIVO, MACRO = "corporativo", "macro"
JUDICIAL, LEGISLATIVO, CALENDARIO = "judicial", "legislativo", "calendario"

# Ordem IMPORTA: judicial vence operacional. Antes, "MPF apresenta recurso
# contra exploracao de petroleo" casava com `producao` e virava operacional.
TIPOS = [
    (JUDICIAL,
     r"\b(mpf|ministerio publico|justica federal|justica|trf\d?|stj|stf|tst"
     r"|acao civil publica|liminar|recurso|apelacao|embargos|sentenca"
     r"|decisao judicial|juiz|desembargador|processo judicial|acao judicial"
     r"|interdito|tutela|agravo)\b"),
    (LEGISLATIVO,
     # "congresso" SOZINHO foi retirado. Medido em 2026-10-04: 53 artigos do
     # acervo contem a palavra e so 7 contem "congresso nacional" -- 87% sao
     # congresso DE AREA ("Congresso IBGC: o ser humano na lideranca da
     # transformacao" vinha marcada como ato legislativo). Na imprensa de
     # negocios a palavra significa evento, nao Legislativo.
     r"\b(projeto de lei|pl \d+|pec|medida provisoria|mp \d+|camara dos deputados"
     # "senado" SOZINHO tambem fica de fora, e pelo mesmo motivo medido:
     # 103 artigos do acervo citam a palavra e a maioria e COBERTURA
     # ELEITORAL ("Quem esta na frente para senador em Pernambuco?"), nao ato
     # legislativo. Vale a casa agindo, nao a casa mencionada.
     r"|senado federal|senado (?:aprov|rejeit|vot)\w*"
     r"|camara (?:aprov|rejeit|vot)\w*|congresso nacional|relator do projeto"
     r"|votacao no plenario|sancao presidencial"
     r"|decreto|consulta publica|tomada de subsidio|audiencia publica)\b"),
    (CALENDARIO,
     # ESTA REGRA ESTAVA ERRADA, e errada de um jeito que inutilizava o tipo.
     # Ela casava "fato relevante" e "comunicado ao mercado", que sao os NOMES
     # DO VEICULO de arquivamento na CVM, nao eventos de calendario: aparecem
     # no corpo de praticamente qualquer anuncio corporativo. Resultado
     # medido: 6 de 6 materias marcadas `calendario` no acervo eram outra
     # coisa -- descoberta de gas, fabrica de baterias, venda de operacao,
     # plano de investimento, aquisicao. O tipo tinha 100% de erro.
     #
     # O pedido (6.3) e CALENDARIO CONTABIL: quando a empresa divulga, nao o
     # que ela divulgou. Logo a regra agora exige construcao que ANUNCIA DATA
     # ou agenda, e nao o nome do documento.
     r"\b(calendario de (?:eventos|resultados|divulgacao)"
     r"|agenda de (?:resultados|divulgacao)|data de divulgacao"
     r"|divulgar[aá] (?:o |os |seu |seus )?(?:balanco|resultado|numero)"
     r"|divulga(?:cao|r) (?:do |dos )?(?:balanco|resultado)s? (?:em|no dia|na data)"
     r"|teleconferencia de resultados|data (?:ex|com)-(?:dividendo|direito)"
     r"|passar[aá] a divulgar|antecipa(?:r|cao d[ao]) divulgacao"
     r"|reuniao do conselho para aprovar (?:o )?(?:balanco|resultado))\b"),
    (MACRO,
     r"\b(selic|copom|ipca|igp-m|inflacao|pib|cambio|dolar|juros basicos"
     r"|payroll|fed|banco central|politica monetaria)\b"),
]

# ORGAO COMO ATOR x ORGAO COMO FONTE -- a distincao que faltava.
#
# O DEFEITO (medido em 2026-10-04): "Producao de petroleo e gas natural no
# Brasil supera marca inedita de 6 milhoes de boe/dia, DIZ ANP" vinha
# classificada como JUDICIAL. Nenhuma regra judicial casou; quem decidiu foi o
# fallback pelo `event_type` legado, que marca "anp" como `regulatory` e o
# mapa manda `regulatory -> judicial`. Ali a ANP e a FONTE da estatistica, nao
# autora de ato nenhum.
#
# O pedido e explicito sobre o que o icone judicial deve significar: "acoes,
# liminares, decisoes de agencia". Decisao de agencia entra; boletim de
# agencia nao.
ORGAOS = (r"\b(anp|aneel|anatel|cvm|cade|ibama|bacen|banco central|susep|antt"
          r"|anvisa|ancine|receita federal|tcu|cgu)\b")
# Verbo de ATO administrativo. "diz", "informa", "divulga", "segundo" e
# "de acordo com" ficam DE FORA de proposito: sao verbos de reporte.
ACOES_ORGAO = (r"\b(aprov(?:a|ou|ar)|autoriz(?:a|ou)|neg(?:a|ou)|suspend(?:e|eu)"
               r"|multa(?:r|ou)?|autu(?:a|ou)|determin(?:a|ou)|decid(?:e|iu)"
               r"|notific(?:a|ou)|embarg(?:a|ou)|interdit(?:a|ou)|cancel(?:a|ou)"
               r"|revog(?:a|ou)|homolog(?:a|ou)|abre processo|instaur(?:a|ou)"
               r"|condicion(?:a|ou)|veda(?:r|ou)?|exig(?:e|iu)|avanca para"
               r"|impugn(?:a|ou))\b")
JANELA_ORGAO = 80       # caracteres entre o orgao e o ato


def _orgao_como_ator(texto_norm: str) -> bool:
    """O orgao APARECE AGINDO, ou so e citado como fonte?

    Procura ato administrativo perto do nome do orgao, nas duas direcoes:
    "ANP aprova" e "aprovado pela ANP" sao o mesmo fato.
    """
    import itertools
    orgaos = [(m.start(), m.end()) for m in re.finditer(ORGAOS, texto_norm)]
    if not orgaos:
        return False
    atos = [(m.start(), m.end()) for m in re.finditer(ACOES_ORGAO, texto_norm)]
    for (o0, o1), (a0, a1) in itertools.product(orgaos, atos):
        if min(abs(a0 - o1), abs(o0 - a1)) <= JANELA_ORGAO:
            return True
    # disputa CONTRA o orgao tambem e materia judicial/regulatoria
    return bool(re.search(r"\bcontra\b.{0,40}" + ORGAOS, texto_norm)
                or re.search(ORGAOS + r".{0,40}\bcontra\b", texto_norm))


# Mapa do event_type antigo -> tipo novo, para nao perder o que ja existe.
DE_EVENT_TYPE = {
    "earnings": CORPORATIVO, "guidance": CORPORATIVO, "mna": CORPORATIVO,
    "rating": CORPORATIVO, "dividend": CORPORATIVO, "equity_offer": CORPORATIVO,
    "management": CORPORATIVO, "distress": CORPORATIVO, "operational": CORPORATIVO,
    "macro_linked": MACRO, "regulatory": JUDICIAL,
}


def orientacao(texto: str) -> list[str]:
    """Conjunto de orientacoes temporais. Pode devolver mais de uma.

    Devolve lista ORDENADA para que o valor gravado seja estavel e comparavel
    (um set em texto variaria de ordem entre execucoes).
    """
    t = norm(texto)
    out = set()
    for grupo, marca in ((MARCAS_PASSADO, PASSADO),
                         (MARCAS_PRESENTE, PRESENTE),
                         (MARCAS_FUTURO, FUTURO)):
        if any(re.search(p, t) for p in grupo):
            out.add(marca)
    if not out:
        out.add(PRESENTE)          # sem marca, o fato e tratado como corrente
    return sorted(out)


def tipo(texto: str, event_type_antigo: str | None = None) -> str:
    """Tipo do evento. Regra primeiro; o event_type antigo e o fallback.

    O FALLBACK PARA JUDICIAL E CONDICIONAL. O balde `regulatory` do legado
    mistura ato de agencia com agencia citada como fonte de dado, e so o
    primeiro e judicial/regulatorio. Sem esta guarda, boletim de producao da
    ANP ganhava icone de processo. Ver `_orgao_como_ator`.
    """
    t = norm(texto)
    for nome, pad in TIPOS:
        if re.search(pad, t):
            return nome
    if event_type_antigo:
        alvo = DE_EVENT_TYPE.get(event_type_antigo, CORPORATIVO)
        if alvo == JUDICIAL and not _orgao_como_ator(t):
            return CORPORATIVO
        return alvo
    return CORPORATIVO


def classifica(texto: str, event_type_antigo: str | None = None) -> dict:
    return {"orientacao": orientacao(texto),
            "tipo_evento": tipo(texto, event_type_antigo)}


# Rotulos, icones e FORMAS que a tela usa. Ficam aqui, e nao no HTML, pela
# mesma razao que os numeros de qualidade ficam em medidas.py: fonte unica.
#
# `icone`  -- glifo unicode, para terminal, lista de noticias e tooltip.
# `forma`  -- chave da geometria que o SVG desenha. Existe porque glifo
#             unicode em marcador de 8px nao e confiavel: "§" e "⚖" variam de
#             largura por fonte e "📅" cai em emoji colorido em parte dos
#             sistemas, o que destroi a leitura de forma num grafico. A
#             legenda desenha a MESMA geometria do marcador, senao a legenda
#             deixa de ser legenda.
# `ordem`  -- ordem de exibicao na legenda, do mais frequente ao mais raro.
# ATENCAO AO ACENTO: `rotulo` e `ajuda` vao DIRETO para a tela, nao sao
# comentario. Mesma regra de obs/medidas.py. O resto do arquivo segue sem
# acento porque e codigo e padrao de regex, que trabalham sobre texto
# normalizado por `norm`.
ICONES = {
    CORPORATIVO: {"rotulo": "Corporativo", "icone": "●", "forma": "direcional",
                  "ordem": 1,
                  "ajuda": "Fato da empresa: resultado, provento, M&A, gestão. "
                           "Mantém o marcador histórico — triângulo para cima "
                           "ou para baixo pela direção, círculo quando neutra."},
    MACRO: {"rotulo": "Macroeconômico", "icone": "▲", "forma": "triangulo_vazado",
            "ordem": 2,
            "ajuda": "Sinal macro que chega ao papel pela cadeia de afetação. "
                     "Triângulo vazado, para não se confundir com o fato da "
                     "própria empresa."},
    JUDICIAL: {"rotulo": "Judicial / regulatório", "icone": "§", "forma": "diamante",
               "ordem": 3,
               "ajuda": "Ação judicial, liminar, recurso, decisão de agência "
                        "ou de órgão de controle."},
    LEGISLATIVO: {"rotulo": "Legislativo / política", "icone": "⚖", "forma": "bandeira",
                  "ordem": 4,
                  "ajuda": "Projeto de lei, medida provisória, consulta pública, "
                           "tomada de subsídio, votação."},
    CALENDARIO: {"rotulo": "Calendário contábil", "icone": "📅", "forma": "calendario",
                 "ordem": 5,
                 "ajuda": "Data de divulgação de resultado, fato relevante CVM, "
                          "agenda contábil. É agenda, não fato consumado."},
}
MARCAS_ORIENTACAO = {
    PASSADO: {"rotulo": "Passado", "marca": "←", "ordem": 1,
              "ajuda": "Relata fato consumado. Deveria explicar movimento JÁ "
                       "ocorrido, não prever o próximo."},
    PRESENTE: {"rotulo": "Presente", "marca": "●", "ordem": 2,
               "ajuda": "Fato em curso agora: negociação, disputa, processo em "
                        "tramitação."},
    FUTURO: {"rotulo": "Futuro", "marca": "→", "ordem": 3,
             "ajuda": "Guidance, projeção, risco prospectivo, processo ainda a "
                      "decidir. É a marca de interesse para radar: o fato "
                      "ainda não aconteceu."},
}


def legenda() -> dict:
    """Mapas para a tela. O HTML nao escreve rotulo nem forma a mao."""
    return {
        "tipos": [{"id": k, **v} for k, v in
                  sorted(ICONES.items(), key=lambda kv: kv[1]["ordem"])],
        "orientacoes": [{"id": k, **v} for k, v in
                        sorted(MARCAS_ORIENTACAO.items(),
                               key=lambda kv: kv[1]["ordem"])],
        "nota": ("Nenhuma das duas dimensoes entra no sinal: elas descrevem e "
                 "filtram. Classificacao errada polui a leitura da tela, nao a "
                 "medicao."),
    }


# Caracteres de CORPO LIMPO que entram na classificacao. Escolhido por
# medicao, nao por gosto -- sobre os 777 scores do banco, contando quantas
# noticias recebem 2 marcas (o caso informativo, "decisao passada + recurso
# pendente") contra 3 marcas (que nao informa nada: tudo marcado como tudo):
#
#   limite   1 marca   2 marcas   3 marcas   tres %
#        0       691         83          3     0,4%   <- so manchete: perde o corpo
#      120       490        246         41     5,3%
#      200       421        300         56     7,2%
#      300       359        341         77     9,9%   <- 2 marcas no maximo
#      450       340        341         96    12,4%   <- 2 marcas para; 3 sobe
#      600       338        339        100    12,9%
#
# Em 300 os casos de duas marcas chegam ao maximo e as tres marcas ficam sob
# 10%. Acima disso so a marcacao inutil cresce: 2 marcas fica parado em 341
# enquanto 3 marcas vai de 77 a 100. Por isso 300, e nao os 600 de
# `score_lexicon`.
#
# A tabela e com corpo LIMPO (util.sem_html). Com o markup dentro, as tres
# marcas iam a 18,5% em 600 chars contra 12,9% limpo. A limpeza muda a
# orientacao de 17 dos 684 corpos (2%) -- efeito modesto e medido, nao
# suposto; ver o docstring de util.sem_html para o que ela NAO conserta.
LIMITE_CORPO = 300


def de_texto(titulo: str, corpo: str | None = None,
             event_type_antigo: str | None = None) -> dict:
    """Classifica a partir do par (titulo, corpo), que e como a base guarda.

    O CORPO ENTRA, limpo de HTML e truncado. Orientacao temporal depende de
    oracao subordinada -- "contestando a decisao de quarta" mora no corpo, nao
    na manchete -- e e exatamente o caso do bloco FZA-M-59.

    `sem_html` entra antes do corte porque 73% dos corpos COMECAM com uma tag
    <img>, que empurra texto real para fora da janela. Medido: a limpeza muda
    a orientacao de 17 dos 684 corpos (2%). Ver obs/util.py:sem_html.
    """
    return classifica(f"{titulo} {sem_html(corpo)[:LIMITE_CORPO]}",
                      event_type_antigo)


# ---------------------------------------------------------- reclassificar ---
def reclassificar(scorer: str | None = None, aplicar: bool = False,
                  verbose: bool = True) -> dict:
    """Recomputa tipo_evento e orientacao no acervo, sob as regras ATUAIS.

    POR QUE ISTO E NECESSARIO E NAO OPCIONAL
    `score.run` so pontua par (artigo,ticker) que ainda NAO tem score. Logo,
    mudar uma regra aqui nao recalcula nada do que ja esta gravado -- o mesmo
    defeito que obs/limpeza.py documenta para o lexico. E pior: enquanto nada
    chamava este modulo, a classificacao do banco ficou CONGELADA no momento
    em que alguem a rodou a mao, e materia nova entrava com as duas colunas em
    NULL.

    SIMULA por padrao, como todo o resto do projeto. `aplicar=True` escreve.

    Idempotente: rodar duas vezes seguidas devolve 0 alteracoes na segunda.
    """
    from .db import connect

    con = connect()
    onde, args = "", []
    if scorer:
        onde, args = "WHERE sc.scorer = ?", [scorer]
    rows = con.execute(f"""
        SELECT sc.article_id, sc.ticker, sc.scorer, sc.event_type,
               sc.tipo_evento, sc.orientacao, a.title, a.body
        FROM scores sc JOIN articles a ON a.id = sc.article_id
        {onde}""", args).fetchall()

    antes_t, antes_o = {}, {}
    depois_t, depois_o = {}, {}
    mudancas, nulos, exemplos = [], 0, []
    for r in rows:
        at, ao = r["tipo_evento"], r["orientacao"]
        antes_t[at] = antes_t.get(at, 0) + 1
        antes_o[ao] = antes_o.get(ao, 0) + 1
        if at is None or ao is None:
            nulos += 1
        cls = de_texto(r["title"], r["body"], r["event_type"])
        dt_, do_ = cls["tipo_evento"], ",".join(cls["orientacao"])
        depois_t[dt_] = depois_t.get(dt_, 0) + 1
        depois_o[do_] = depois_o.get(do_, 0) + 1
        if at != dt_ or ao != do_:
            mudancas.append((r["article_id"], r["ticker"], r["scorer"], dt_, do_))
            if len(exemplos) < 12:
                exemplos.append({"id": r["article_id"], "ticker": r["ticker"],
                                 "titulo": r["title"][:88],
                                 "de": f"{at} / {ao}", "para": f"{dt_} / {do_}"})

    if aplicar and mudancas:
        with con:
            con.executemany(
                "UPDATE scores SET tipo_evento=?, orientacao=? "
                "WHERE article_id=? AND ticker=? AND scorer=?",
                [(dt_, do_, aid, tkr, sc) for aid, tkr, sc, dt_, do_ in mudancas])
    con.close()

    out = {"aplicou": aplicar, "scores": len(rows), "sem_classificacao": nulos,
           "alteracoes": len(mudancas), "exemplos": exemplos,
           "antes": {"tipo": antes_t, "orientacao": antes_o},
           "depois": {"tipo": depois_t, "orientacao": depois_o}}
    if verbose:
        print(f"scores examinados        : {len(rows)}")
        print(f"sem classificacao (NULL) : {nulos}")
        print(f"alteracoes {'aplicadas' if aplicar else 'que seriam feitas'}: "
              f"{len(mudancas)}")
        print("\ntipo de evento:")
        for k in sorted(set(antes_t) | set(depois_t), key=lambda x: str(x)):
            print(f"  {str(k):<16}{antes_t.get(k,0):>6} -> {depois_t.get(k,0):>6}")
        print("\norientacao temporal:")
        for k in sorted(set(antes_o) | set(depois_o), key=lambda x: str(x)):
            print(f"  {str(k):<28}{antes_o.get(k,0):>6} -> {depois_o.get(k,0):>6}")
        if exemplos:
            print("\nexemplos de mudanca:")
            for e in exemplos:
                print(f"  {e['ticker']:<6} {e['de']:<28} -> {e['para']}")
                print(f"         {e['titulo']}")
        if not aplicar and mudancas:
            print("\nPara gravar: python3 -m obs.cli classificar --aplicar")
    return out
