"""Registro das medicoes que dao lastro ao que o painel exibe.

REGRA DO PROJETO: nenhum numero aparece na tela sem lastro medido. Este
modulo e a UNICA fonte dos selos de qualidade e do mapa horizonte -> cabecas.
O front-end nao tem numero de qualidade escrito no HTML: tudo vem daqui via
GET /api/status. Mudou uma medicao? Mude aqui, citando o script que a produziu.
"""
from __future__ import annotations

# ------------------------------------------------------------ medicoes ---
MEDIDAS = {
    # ATENCAO A DISCREPANCIA: este 0,683 vem de uma divisao 60/40 unica com
    # 18-20 papeis. O calibrador do PROPRIO projeto (obs.volatility.fit_calibrator,
    # walk-forward de 6 dobras sobre a watchlist de 10 papeis) obtem AUC 0,551
    # -- e foi REPROVADO na porta por skill de Brier +0,005 (minimo +0,01).
    # O numero estrito e o de baixo; o 0,683 fica como referencia do protocolo
    # mais frouxo, e NAO deve ser usado como selo sozinho.
    "agitacao_auc": {
        "metrica": "AUC", "valor": 0.683,
        "alvo": "top 20% de |retorno anormal| no pregao seguinte",
        "desenho": "logit, divisao 60/40 temporal unica, 18-20 papeis, 2 anos",
        "fonte": "scripts/vol_test2.py (caso C)",
        "protocolo": "frouxo",
    },
    "agitacao_auc_wf": {
        "metrica": "AUC", "valor": 0.551,
        "ic95": [0.527, 0.576],
        "alvo": "top 20% de |retorno anormal| no pregao seguinte",
        "desenho": "walk-forward 6 dobras, watchlist de 10 papeis",
        "fonte": "obs.volatility.fit_calibrator",
        "protocolo": "estrito",
        "aprovado": False,
        "motivo": "skill de Brier +0,005; minimo da porta +0,01",
    },
    "agitacao_ic": {
        "metrica": "IC (Spearman)", "valor": 0.303,
        "alvo": "|retorno anormal| continuo no pregao seguinte",
        "desenho": "minimos quadrados nas mesmas features, 60/40 temporal",
        "fonte": "scripts/vol_test2.py (caso A)",
    },
    # A MEDICAO DIRETA DA DIRECAO EM D+1. Faltava: antes o selo de D+1 citava
    # `preco_ic`, cujo alvo e o GAP DE ABERTURA -- outro alvo. Atribuir a
    # evidencia do gap a previsao de fechamento-a-fechamento era emprestar
    # lastro de uma medicao para outra pergunta.
    "direcao_d1_auc": {
        "metrica": "AUC fora da amostra", "valor": 0.5043,
        "valor_alta": 0.4948, "valor_queda": 0.5043,
        "alvo": "direcao do retorno anormal em D+1 (fechamento a fechamento)",
        "desenho": ("canal de drivers; betas reestimados a cada 21 pregoes com "
                    "fit_exposures(asof=T) lendo so d < T; calibracao "
                    "walk-forward em 5 dobras"),
        "n_oos": 15720,
        "controles": {"oraculo": 1.0000, "ruido_puro": 0.5054},
        # Com acento: esta string vai DIRETO para a tela, nao e comentario.
        "veredito": ("REPROVADO em 6 de 6 especificações (alta e queda, "
                     "h = 1, 5 e 20 pregões). Indistinguível do ruído: 0,504 "
                     "contra 0,505 do controle negativo medido no mesmo arcabouço."),
        "fonte": "scripts/direcao_test.py, scripts/direcao_horizonte.py",
    },
    "preco_ic": {
        "metrica": "IC", "valor": 0.081, "sinal": "reversao (IC medido -0,081)",
        "t_fama_macbeth": -3.81,
        "alvo": "residuo transversal do gap de abertura do pregao seguinte",
        "desenho": "exposicao cambial ex-ante, walk-forward",
        "fonte": "scripts/combo_test.py, scripts/metalabel_test.py, scripts/alvo70.py",
    },
}


def _n(v: float, casas: int = 3) -> str:
    """0.683 -> '0,683'; -3.81 -> '−3,81' (formato pt-BR, menos tipografico)."""
    s = f"{abs(v):.{casas}f}".replace(".", ",")
    return ("−" if v < 0 else "") + s


SELO_NAO_MEDIDO = "não medido"
SELO_AGITACAO = (f"AUC {_n(MEDIDAS['agitacao_auc_wf']['valor'])} walk-forward "
                 f"(protocolo frouxo: {_n(MEDIDAS['agitacao_auc']['valor'])}) · "
                 f"IC {_n(MEDIDAS['agitacao_ic']['valor'])} contínuo")
def _milhar(n: int) -> str:
    """15720 -> '15.720' (pt-BR). Separado para nao colidir com a virgula
    decimal: um .replace(',', '.') aplicado a frase inteira transformava
    'AUC 0,5043' em 'AUC 0.5043'."""
    return f"{n:,}".replace(",", ".")


SELO_DIRECAO = (f"AUC {_n(MEDIDAS['direcao_d1_auc']['valor'], 4)} fora da amostra "
                f"(n = {_milhar(MEDIDAS['direcao_d1_auc']['n_oos'])}) · "
                f"ruído puro deu "
                f"{_n(MEDIDAS['direcao_d1_auc']['controles']['ruido_puro'], 4)} · "
                "canal de notícias não medido")
SELO_DIRECAO_ABERTURA = (f"IC {_n(MEDIDAS['preco_ic']['valor'])} no canal de preço "
                         f"(t = {_n(MEDIDAS['preco_ic']['t_fama_macbeth'], 2)}, Fama-MacBeth) · "
                         "canal de notícias não medido")

# ----------------------------------------------------------- horizontes ---
# `valores`: a API deixa passar saidas de modelo NESTE horizonte (ainda
# sujeitas a flag de calibracao). Onde e False, a API zera as saidas e a tela
# mostra o selo -- nunca um numero.
# HORIZONTES INTRADIARIOS. Existem para PODER MEDIR, nao porque ja funcionem.
# O que foi medido ate aqui: no canal de PRECO o arbitramento fecha dentro de
# 5 minutos (IC defasado +0,017 em 5min, +0,031 em 1h, +0,021 em D+1 -- nenhum
# significativo). O canal de NOTICIA nesses horizontes continua sem veredito:
# scripts/evento_noticia.py roda com n=26 e se recusa a concluir.
# Entao todas as cabecas aqui saem com `valores: False`: a tela mostra o selo,
# nunca um numero. Quando o estudo de evento juntar amostra, estes horizontes
# ja estarao de pe para receber a medicao.
SELO_INTRADIA = ("canal de preço: sem defasagem explorável (IC +0,017 em 5min, "
                 "+0,031 em 1h; nenhum significativo) · canal de notícias: "
                 "em acumulação, ver estudo de evento")

HORIZONTES = [
    {"id": "m1", "rotulo": "1 minuto", "descricao": "próxima barra de 1 minuto",
     "intradia": True, "barras": 1, "intervalo": "1m",
     "cabecas": {
         "direcao": {"valores": False, "selo": SELO_INTRADIA, "medidas": []},
         "agitacao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
     }},
    {"id": "m5", "rotulo": "5 minutos", "descricao": "próximas 5 barras de 1 minuto",
     "intradia": True, "barras": 5, "intervalo": "1m",
     "cabecas": {
         "direcao": {"valores": False, "selo": SELO_INTRADIA, "medidas": []},
         "agitacao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
     }},
    {"id": "h1", "rotulo": "1 hora", "descricao": "próxima barra de 1 hora",
     "intradia": True, "barras": 1, "intervalo": "1h",
     "cabecas": {
         "direcao": {"valores": False, "selo": SELO_INTRADIA, "medidas": []},
         "agitacao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
     }},
    {"id": "h2", "rotulo": "2 horas", "descricao": "próximas 2 barras de 1 hora",
     "intradia": True, "barras": 2, "intervalo": "1h",
     "cabecas": {
         "direcao": {"valores": False, "selo": SELO_INTRADIA, "medidas": []},
         "agitacao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
     }},
    {"id": "abertura", "rotulo": "Próxima abertura (~16h)",
     "descricao": "gap de abertura do próximo pregão",
     "cabecas": {
         "direcao": {"valores": False, "selo": SELO_DIRECAO_ABERTURA,
                     "nota": "canal de preço medido; o painel ainda não calcula esse sinal ao vivo",
                     "medidas": ["preco_ic"]},
         "agitacao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
     }},
    {"id": "d1", "rotulo": "D+1", "descricao": "pregão seguinte, fechamento a fechamento",
     "cabecas": {
         "direcao": {"valores": True, "selo": SELO_DIRECAO,
                     "medidas": ["direcao_d1_auc"]},
         "agitacao": {"valores": True, "selo": SELO_AGITACAO,
                      "medidas": ["agitacao_auc", "agitacao_ic"]},
     }},
    {"id": "d5", "rotulo": "D+5", "descricao": "cinco pregões à frente",
     "cabecas": {
         "direcao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
         "agitacao": {"valores": False, "selo": SELO_NAO_MEDIDO, "medidas": []},
     }},
]
HORIZONTE_PADRAO = "d1"
POR_ID = {h["id"]: h for h in HORIZONTES}


def horizonte(hid: str | None) -> dict:
    return POR_ID.get(hid or HORIZONTE_PADRAO, POR_ID[HORIZONTE_PADRAO])


# campos de saida de modelo por cabeca: o que a API apaga quando a cabeca
# nao tem valores no horizonte pedido
CAMPOS = {
    "direcao": ["p_up", "p_flat", "p_down", "base_up", "base_flat", "base_down"],
    "agitacao": ["p_vol", "vol_base", "vol_faixa", "vol_ordem"],
}


def aplicar(sig: dict, hid: str | None) -> dict:
    """Copia de `sig` so com o que tem lastro no horizonte `hid`."""
    h = horizonte(hid)
    out = dict(sig)
    out.pop("vol_score", None)                 # escore provisorio: nunca sai da API
    # taxa-base sem rotulos e um 1/3 de fabrica, nao medicao: so com calibrador
    if not out.get("calibrated"):
        for k in ("base_up", "base_flat", "base_down"):
            out[k] = None
    for cab, campos in CAMPOS.items():
        if not h["cabecas"][cab]["valores"]:
            for k in campos:
                out[k] = None
            if cab == "direcao":
                out["calibrated"] = 0
            else:
                out["vol_calib"] = 0
    out["horizonte"] = h["id"]
    return out


# ---------------------------------------------------------------- portas ---
# AS DUAS CABECAS TEM PORTAS DIFERENTES, e confundi-las ja gerou texto errado
# na tela: o painel anunciava "n >= 500 · AUC >= 0,55 · skill >= 0,01" como
# criterio da DIRECAO, quando esses sao os CAL_MIN_* da AGITACAO. A direcao
# nunca teve limiar de AUC -- tinha so o minimo de rotulos, e ate 2026-10-02
# nem porta de desempenho tinha.
def portas() -> dict:
    from .calibrate import MIN_N, MIN_SKILL
    from .volatility import CAL_MIN_AUC, CAL_MIN_OOS, CAL_MIN_SKILL
    return {
        "direcao": {
            "min_rotulos": MIN_N,
            "min_skill_brier": MIN_SKILL,
            "exige_skill_nos_dois_lados": True,
            "min_auc": None,
            "nota": ("sem limiar de AUC: a direcao e avaliada por skill de "
                     "Brier contra a taxa-base, nos dois lados"),
            "fonte": "obs/calibrate.py",
        },
        "agitacao": {
            "min_oos": CAL_MIN_OOS,
            "min_auc": CAL_MIN_AUC,
            "min_skill_brier": CAL_MIN_SKILL,
            "nota": "o limite inferior do IC 95% do AUC tambem precisa passar de 0,5",
            "fonte": "obs/volatility.py",
        },
    }
