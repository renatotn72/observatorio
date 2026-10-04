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

from .util import norm

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
     r"\b(projeto de lei|pl \d+|pec|medida provisoria|mp \d+|camara dos deputados"
     r"|senado|congresso|relator|votacao no plenario|sancao presidencial"
     r"|decreto|consulta publica|tomada de subsidio|audiencia publica)\b"),
    (CALENDARIO,
     r"\b(calendario de (?:eventos|resultados)|data de divulgacao"
     r"|divulgara (?:o )?(?:balanco|resultado)|agenda de resultados"
     r"|fato relevante|comunicado ao mercado)\b"),
    (MACRO,
     r"\b(selic|copom|ipca|igp-m|inflacao|pib|cambio|dolar|juros basicos"
     r"|payroll|fed|banco central|politica monetaria)\b"),
]

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
    """Tipo do evento. Regra primeiro; o event_type antigo e o fallback."""
    t = norm(texto)
    for nome, pad in TIPOS:
        if re.search(pad, t):
            return nome
    if event_type_antigo:
        return DE_EVENT_TYPE.get(event_type_antigo, CORPORATIVO)
    return CORPORATIVO


def classifica(texto: str, event_type_antigo: str | None = None) -> dict:
    return {"orientacao": orientacao(texto),
            "tipo_evento": tipo(texto, event_type_antigo)}


# Rotulos e icones que a tela usa. Ficam aqui, e nao no HTML, pela mesma razao
# que os numeros de qualidade ficam em medidas.py: fonte unica.
ICONES = {
    CORPORATIVO: {"rotulo": "Corporativo", "icone": "●"},
    MACRO: {"rotulo": "Macroeconômico", "icone": "▲"},
    JUDICIAL: {"rotulo": "Judicial / regulatório", "icone": "§"},
    LEGISLATIVO: {"rotulo": "Legislativo / política", "icone": "⚖"},
    CALENDARIO: {"rotulo": "Calendário contábil", "icone": "📅"},
}
MARCAS_ORIENTACAO = {
    PASSADO: {"rotulo": "Passado", "marca": "←"},
    PRESENTE: {"rotulo": "Presente", "marca": "●"},
    FUTURO: {"rotulo": "Futuro", "marca": "→"},
}
