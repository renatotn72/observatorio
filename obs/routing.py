"""Roteamento: a cadeia de afetacao decide QUE ASSUNTOS cada papel escuta.

Resolve tres coisas de uma vez:

1. DESCOBERTA DE ASSUNTOS -- os assuntos nao sao escritos a mao por papel.
   Saem do vetor de exposicao estimado: se a PETR4 e 49% Brent, ela escuta
   petroleo, OPEP e estoques; se a CSNA3 carrega minerio, ela escuta minerio
   e siderurgia chinesa.

2. SELECAO DE DRIVERS POR PAPEL -- medimos que 14 drivers dao PIOR que 4
   (IC -0.002 contra -0.081). Aqui cada papel fica com os seus top-k, em vez
   de todos carregarem o painel inteiro.

3. IMPRENSA ESTRANGEIRA -- cada assunto tem termos em portugues E em ingles.
   Os termos em ingles alcancam Reuters, Bloomberg e FT pelo proprio GDELT,
   sem nenhuma fonte nova. E justamente a imprensa estrangeira que cobre os
   DRIVERS (petroleo, minerio, China) antes da brasileira.

O que isto NAO faz: nao aumenta o IC por evento. Aumenta a CONTAGEM de
eventos -- hoje 23 scores em 156 artigos, porque um papel so reage a materia
que escreve o nome dele. O efeito sobre o IC por evento e ambiguo e precisa
ser medido: noticia de petroleo afeta a PETR4 de forma menos especifica que
noticia da Petrobras.
"""
from __future__ import annotations

from . import config

# driver -> (termos PT, termos EN). Os termos EN sao o que traz imprensa de fora.
TOPICOS: dict[str, tuple[list[str], list[str]]] = {
    "BRENT":   (["petroleo", "petroleo brent", "opep"],
                ["crude oil", "brent crude", "OPEC", "oil inventories"]),
    "GAS":     (["gas natural"], ["natural gas", "LNG"]),
    "MINERIO": (["minerio de ferro", "siderurgia"],
                ["iron ore", "steel demand", "China steel"]),
    "COBRE":   (["cobre"], ["copper prices", "copper demand"]),
    "OURO":    (["ouro"], ["gold prices"]),
    "SOJA":    (["soja", "safra de soja"], ["soybean", "soybean exports"]),
    "ACUCAR":  (["acucar", "etanol"], ["sugar prices", "ethanol"]),
    "CAFE":    (["cafe", "safra de cafe"], ["coffee prices", "coffee harvest"]),
    "USDBRL":  (["dolar", "cambio", "real brasileiro"],
                ["Brazilian real", "BRL exchange rate"]),
    "DXY":     (["dolar forte", "juros americanos", "federal reserve"],
                ["dollar index", "Federal Reserve", "US rates"]),
    "EURUSD":  (["euro", "banco central europeu"], ["euro", "ECB"]),
    "USDCNY":  (["yuan", "economia chinesa"], ["yuan", "China economy"]),
    "SPX":     (["wall street", "bolsas americanas"], ["S&P 500", "Wall Street"]),
    "HSI":     (["china", "hong kong"], ["China growth", "Hang Seng"]),
}

TOP_K = 4            # drivers por papel; medimos que o painel inteiro dilui
SHARE_MIN = 0.08     # abaixo disso a exposicao nao justifica uma consulta


def drivers_do_papel(exposicao: dict, k: int = TOP_K,
                     share_min: float = SHARE_MIN) -> list[tuple[str, float, float]]:
    """Top-k drivers de um papel: [(driver, share, beta)], filtrados por share."""
    itens = [(d, v["share"], v["beta"]) for d, v in exposicao["drivers"].items()]
    itens.sort(key=lambda t: -t[1])
    return [t for t in itens[:k] if t[1] >= share_min]


# Topicos de SETOR. A terceira camada, ao lado de empresa e driver macro.
#
# POR QUE SETOR E A GRANULARIDADE CERTA PARA ESTE ALVO
# O alvo e o retorno residual TRANSVERSAL (acao menos a media das outras). Isso
# decide o que pode funcionar:
#   macro   move todas as acoes juntas -> cancela na subtracao, por construcao.
#           E a explicacao estrutural das 6 reprovacoes da camada de surpresa.
#   setor   move um SUBCONJUNTO -> sobrevive. "Regulacao nova para bancos"
#           mexe com ITUB4, BBDC4 e BBAS3 contra a media, nao com a media.
#   empresa move uma -> sobrevive.
# Setor estava em config/watchlist.yml desde o inicio, mas so era usado para
# IMPRIMIR na tela: nenhum modulo de coleta, ligacao ou pontuacao o lia.
#
# Termos deliberadamente especificos: "banco" sozinho casaria com metade do
# noticiario economico. O que se quer e o evento que atinge o setor inteiro.
TOPICOS_SETOR: dict[str, tuple[list[str], list[str]]] = {
    "banks": (["bancos brasileiros", "setor bancario", "spread bancario",
               "inadimplencia bancaria", "Banco Central regulacao",
               "credito bancario"],
              ["Brazilian banks", "bank regulation Brazil", "banking sector Brazil"]),
    "mining": (["setor de mineracao", "mineradoras", "licenca ambiental mineracao",
                "royalties minerarios"],
               ["mining sector Brazil", "iron ore miners", "mining royalties"]),
    "oil_gas": (["setor petrolifero", "politica de precos combustiveis",
                 "leilao de blocos", "ANP producao", "pre-sal"],
                ["Brazil oil sector", "fuel price policy Brazil", "pre-salt"]),
    "retail": (["varejo brasileiro", "vendas no varejo", "e-commerce brasil",
                "consumo das familias", "endividamento das familias"],
               ["Brazilian retail", "retail sales Brazil", "e-commerce Brazil"]),
    "pulp_paper": (["celulose", "papel e celulose", "preco da celulose"],
                   ["pulp prices", "paper and pulp", "hardwood pulp"]),
    "beverages": (["setor de bebidas", "consumo de cerveja", "imposto sobre bebidas"],
                  ["beverage sector Brazil", "beer consumption Brazil"]),
    "industrials": (["producao industrial", "bens de capital", "industria brasileira"],
                    ["Brazil industrial production", "capital goods Brazil"]),
    "financials": (["bolsa brasileira volume", "mercado de capitais brasil",
                    "regulacao CVM"],
                   ["Brazilian capital markets", "B3 volumes", "CVM regulation"]),
}

# Noticia de setor pesa MENOS que noticia da empresa: ela atinge o papel por
# pertencimento, nao por citacao. O numero e palpite ate haver medicao -- o
# teste esta em scripts/setor_test.py.
PESO_SETOR = 0.35


def setores_da_watchlist() -> dict[str, list[str]]:
    """{setor: [tickers]}, so setores que tem topico definido."""
    out: dict[str, list[str]] = {}
    for tkr, meta in config.tickers().items():
        s = meta.get("sector")
        if s and s in TOPICOS_SETOR:
            out.setdefault(s, []).append(tkr)
    return out


def consultas_setor(incluir_ingles: bool = True) -> list[dict]:
    """Uma consulta por SETOR presente na watchlist, nao por papel.

    Mesma economia da deduplicacao por driver: tres bancos compartilham a
    mesma consulta setorial, entao pergunta-se uma vez e distribui.
    """
    out = []
    for setor, tickers in sorted(setores_da_watchlist().items()):
        pt, en = TOPICOS_SETOR[setor]
        out.append({"tipo": "setor", "setor": setor, "tickers": tickers,
                    "driver": f"setor:{setor}", "peso": PESO_SETOR,
                    "sinal_beta": 1,
                    "termos_pt": pt, "termos_en": en if incluir_ingles else []})
    return out


def consultas(ticker: str, exposicao: dict | None = None,
              incluir_ingles: bool = True) -> list[dict]:
    """Consultas de noticia que este papel deve rodar.

    A primeira e a do nome da empresa (o que o sistema ja fazia). As demais
    vem da cadeia de afetacao, cada uma com o peso da exposicao -- o score
    daquela noticia entra no sinal multiplicado por `peso` e pelo sinal do
    beta (exposicao negativa inverte a direcao da noticia).
    """
    meta = config.tickers().get(ticker, {})
    out = [{"tipo": "empresa", "driver": None, "peso": 1.0, "sinal_beta": 1,
            "termos_pt": [a for a in meta.get("aliases", []) if " " in a or len(a) > 4],
            "termos_en": []}]
    if not exposicao:
        return out

    for driver, share, beta in drivers_do_papel(exposicao):
        pt, en = TOPICOS.get(driver, ([], []))
        if not pt and not en:
            continue
        out.append({"tipo": "driver", "driver": driver, "peso": round(share, 4),
                    "sinal_beta": 1 if beta >= 0 else -1,
                    "termos_pt": pt, "termos_en": en if incluir_ingles else []})
    return out


def gdelt_query(consulta: dict, max_termos: int = 6) -> str:
    termos = (consulta["termos_pt"] + consulta["termos_en"])[:max_termos]
    if not termos:
        return ""
    return "(" + " OR ".join(f'"{t}"' for t in termos) + ")"


def plano(exposicoes: dict[str, dict]) -> dict[str, list[dict]]:
    """Plano de roteamento da watchlist inteira."""
    return {t: consultas(t, exposicoes.get(t)) for t in config.tickers()}
