"""Modelo de afetacao ESTRUTURAL: o mecanismo, com sinal.

O QUE ESTE MODULO ACRESCENTA
O sistema ja tinha duas formas de uma noticia alcancar um papel:
    empresa  -- o texto cita o nome (obs/entity.py)
    driver   -- o papel se move junto com Brent/dolar (obs/drivers.py, ridge)
    setor    -- a noticia atinge o setor (obs/routing.py)
Falta a quarta, e e a que o usuario descreveu: o MECANISMO. Cadeia de
producao, custo de insumo, politica de credito, tributacao, exposicao
politica. Coisas que mudam o lucro da empresa sem citar o nome dela e sem
aparecer na correlacao de precos de 250 pregoes.

A DIFERENCA QUE IMPORTA: SINAL
A cadeia por ridge e DESCRITIVA -- descobre que VALE3 anda com minerio, nao
que minerio caro e BOM para a VALE3 (o beta carrega isso, mas so para o que
tem preco diario). Aqui o sinal e EXPLICITO e vem de conhecimento do negocio:

    "Copom sobe a Selic"  -> +1 para bancos (spread), -1 para varejo (credito)

A MESMA noticia com sinais opostos em papeis diferentes e exatamente o que um
alvo transversal premia. Noticia que move todos para o mesmo lado cancela na
subtracao da media; noticia que SEPARA sobrevive.

COMO ISSO ESCALA (a pergunta "toda empresa nova ter um modelo")
Nao se escreve um modelo por empresa. Escreve-se por:
    SETOR      -- herdado automaticamente de config/watchlist.yml
    ATRIBUTO   -- `estatal`, `exportador`, `alavancado`, `ciclico`
    OVERRIDE   -- so quando o papel foge do seu setor
Papel novo entra herdando setor + atributos e ja tem modelo. So se escreve
linha nova quando ele contraria a regra do grupo.

POR QUE O ATRIBUTO EXISTE SEPARADO DO SETOR
BBAS3, ITUB4 e BBDC4 sao todos `banks`. Mas BBAS3 e ESTATAL: noticia de
ingerencia politica derruba a BBAS3 e e neutra ou boa para as privadas. Setor
nao expressa isso; atributo sim. Mesmo caso de PETR4 (estatal) contra uma
petroleira privada.

AVISO QUE NAO PODE SUMIR
Tudo aqui e HIPOTESE, nao medicao. Sinal escrito a mao e plausibilidade, e
plausibilidade e barata: da para encher o arquivo de relacoes que soam obvias
e nao preveem nada. Por isso cada tema nasce com `ativo=False` e so entra no
sinal depois de passar em scripts/temas_test.py, com a mesma regua que
reprovou doze outras coisas neste projeto.
"""
from __future__ import annotations

from . import config

# Atributos por papel. O que o setor nao captura.
# Preenchido a mao porque e fato de registro, nao estimativa: quem controla a
# empresa, se ela exporta, se e alavancada.
ATRIBUTOS: dict[str, set[str]] = {
    "PETR4": {"estatal", "exportador", "ciclico"},
    "BBAS3": {"estatal"},
    "VALE3": {"exportador", "ciclico"},
    "SUZB3": {"exportador", "ciclico"},
    "ITUB4": set(),
    "BBDC4": set(),
    "ABEV3": {"defensivo"},
    "WEGE3": {"exportador"},
    "MGLU3": {"alavancado", "ciclico"},
    "B3SA3": set(),
}

# TEMA = (termos de busca, efeito por setor, efeito por atributo)
# Efeito: +1 beneficia, -1 prejudica. Ausencia = sem hipotese, nao neutro.
TEMAS: dict[str, dict] = {
    "juros_credito": {
        "rotulo": "Juros e política de crédito",
        "termos_pt": ["Copom Selic", "taxa basica de juros", "credito direcionado",
                      "deposito compulsorio", "inadimplencia do credito",
                      "concessao de credito"],
        "termos_en": ["Brazil interest rate decision", "Selic rate", "credit policy Brazil"],
        "setor": {"banks": +1, "retail": -1, "industrials": -1, "financials": +1},
        "atributo": {"alavancado": -1},
        "ativo": False,
    },
    "cambio_exportador": {
        "rotulo": "Câmbio e competitividade exportadora",
        "termos_pt": ["dolar alto exportacao", "competitividade das exportacoes",
                      "balanca comercial brasileira"],
        "termos_en": ["Brazil exports competitiveness", "weak real exporters"],
        "setor": {"mining": +1, "pulp_paper": +1, "retail": -1},
        "atributo": {"exportador": +1},
        "ativo": False,
    },
    "intervencao_estatal": {
        "rotulo": "Ingerência política em estatal",
        "termos_pt": ["interferencia politica estatal", "troca de comando estatal",
                      "politica de precos combustiveis", "indicacao politica diretoria",
                      "governo pressiona estatal"],
        "termos_en": ["Brazil state-run company interference",
                      "political appointment state company"],
        "setor": {},
        "atributo": {"estatal": -1},      # o ponto: setor nao captura isso
        "ativo": False,
    },
    "tributacao": {
        "rotulo": "Tributação e reforma tributária",
        "termos_pt": ["reforma tributaria", "aumento de imposto", "IPI bebidas",
                      "tributacao sobre dividendos", "carga tributaria setorial"],
        "termos_en": ["Brazil tax reform", "Brazil corporate tax"],
        "setor": {"beverages": -1, "retail": -1},
        "atributo": {},
        "ativo": False,
    },
    "consumo_renda": {
        "rotulo": "Renda, emprego e consumo das famílias",
        "termos_pt": ["massa salarial", "geracao de emprego", "renda das familias",
                      "vendas no comercio", "endividamento das familias"],
        "termos_en": ["Brazil household income", "Brazil consumer spending"],
        "setor": {"retail": +1, "beverages": +1, "banks": +1},
        "atributo": {},
        "ativo": False,
    },
    "custo_energia_insumo": {
        "rotulo": "Custo de energia e insumos (cadeia de produção)",
        "termos_pt": ["tarifa de energia", "bandeira tarifaria", "custo de insumos",
                      "preco do frete", "gargalo logistico", "custo de producao"],
        "termos_en": ["Brazil energy tariff", "input costs Brazil", "freight costs"],
        "setor": {"industrials": -1, "mining": -1, "pulp_paper": -1, "beverages": -1},
        "atributo": {},
        "ativo": False,
    },
    "infraestrutura_logistica": {
        "rotulo": "Infraestrutura e escoamento",
        "termos_pt": ["ferrovia escoamento", "porto exportacao", "leilao de infraestrutura",
                      "investimento em logistica"],
        "termos_en": ["Brazil port infrastructure", "Brazil railway investment"],
        "setor": {"mining": +1, "pulp_paper": +1, "industrials": +1},
        "atributo": {"exportador": +1},
        "ativo": False,
    },
    "ambiental_regulatorio": {
        "rotulo": "Licenciamento ambiental e passivo regulatório",
        "termos_pt": ["licenciamento ambiental", "multa ambiental", "IBAMA licenca",
                      "barragem risco", "passivo ambiental"],
        "termos_en": ["Brazil environmental license", "mining dam safety"],
        "setor": {"mining": -1, "oil_gas": -1, "pulp_paper": -1},
        "atributo": {},
        "ativo": False,
    },
    "risco_politico": {
        "rotulo": "Risco político e eleitoral",
        "termos_pt": ["risco politico Brasil", "incerteza eleitoral",
                      "pacote fiscal", "arcabouco fiscal"],
        "termos_en": ["Brazil political risk", "Brazil fiscal framework"],
        "setor": {},
        "atributo": {"estatal": -1, "alavancado": -1},
        "ativo": False,
    },
}


# Noticia de tema pesa menos que a que cita a empresa, e menos que a setorial:
# o elo entre a materia e o lucro do papel e mais longo. PALPITE ate medir.
PESO_TEMA = 0.25


def efeito(ticker: str, tema: str) -> int:
    """Sinal do tema sobre o papel: +1, -1 ou 0 (sem hipotese).

    Combina setor e atributos. Quando os dois opinam, SOMA e toma o sinal --
    um banco estatal sob noticia de juros tem +1 de setor; se a noticia fosse
    de ingerencia, teria -1 de atributo. Empate devolve 0, que e a resposta
    honesta: a hipotese nao sabe dizer.
    """
    t = TEMAS.get(tema)
    if not t:
        return 0
    meta = config.tickers().get(ticker.upper(), {})
    total = t["setor"].get(meta.get("sector"), 0)
    for attr in ATRIBUTOS.get(ticker.upper(), set()):
        total += t["atributo"].get(attr, 0)
    return (total > 0) - (total < 0)


def alvos(tema: str) -> list[tuple[str, int]]:
    """[(ticker, sinal)] de todos os papeis que o tema atinge."""
    return [(t, s) for t in config.tickers()
            if (s := efeito(t, tema)) != 0]


def consultas_tema(incluir_ingles: bool = True, so_ativos: bool = True) -> list[dict]:
    """Uma consulta por TEMA, no formato que obs/ingest espera."""
    out = []
    for nome, t in TEMAS.items():
        if so_ativos and not t.get("ativo"):
            continue
        alvo = alvos(nome)
        if not alvo:
            continue
        out.append({"tipo": "tema", "tema": nome, "rotulo": t["rotulo"],
                    "alvos": alvo, "driver": f"tema:{nome}",
                    "termos_pt": t["termos_pt"],
                    "termos_en": t["termos_en"] if incluir_ingles else []})
    return out


def mapa() -> dict[str, dict[str, int]]:
    """{tema: {ticker: sinal}} -- a matriz inteira, para inspecao."""
    return {nome: dict(alvos(nome)) for nome in TEMAS}
