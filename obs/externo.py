"""Surpresa de indicadores ESTRANGEIROS, por proxy de mercado.

O PROBLEMA QUE ISTO CONTORNA
    Para o Brasil existe o Focus: consenso publicado, com dispersao, de graca.
    Para EUA e China nao ha equivalente alcancavel -- FRED exige chave e o
    World Bank so tem dado anual. Sem consenso, a formula
    (realizado - mediana) / desvio nao existe.

A SAIDA, QUE E METODO PADRAO EM MACRO-FINANCAS
    No dia de uma divulgacao agendada, o movimento do instrumento mais
    sensivel a ela JA E a surpresa: se o CPI americano sai em linha, o dolar
    nao se mexe; se sai acima, o dolar sobe. Usa-se o mercado como termometro
    em vez do consenso.

A CIRCULARIDADE QUE ISTO INTRODUZ -- leia antes de interpretar
    A cadeia de afetacao JA regride o retorno do papel contra o DXY todo dia.
    Restringir aos dias de divulgacao e um SUBCONJUNTO disso. Entao a pergunta
    que este modulo responde nao e "o papel reage a surpresa externa?" e sim
    "a exposicao ao dolar discrimina mais nos dias de divulgacao do que nos
    outros?". E uma pergunta mais estreita, e e a unica que o dado permite.

CALENDARIO POR REGRA, NAO POR FONTE
    As datas seguem regras publicas e estaveis (payroll na primeira sexta,
    CPI por volta do dia 12). Sao APROXIMADAS. No caso brasileiro testamos se
    a aproximacao de data era a culpada por um resultado nulo -- nao era
    (scripts/surpresa_janela.py) -- mas aqui o teste tem de ser refeito.
"""
from __future__ import annotations
import calendar
import datetime as dt

# nome -> (instrumento sensivel, regra de data, descricao)
EVENTOS = {
    "CPI EUA":      {"instr": "DXY", "regra": "dia12", "n_mes": 1,
                     "nota": "inflacao americana move o dolar e a curva de juros"},
    "Payroll EUA":  {"instr": "DXY", "regra": "1a_sexta", "n_mes": 1,
                     "nota": "emprego americano move o dolar"},
    "PMI China":    {"instr": "HSI", "regra": "dia1", "n_mes": 1,
                     "nota": "atividade chinesa move Asia e commodities"},
}


def _primeira_sexta(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 1)
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    return d


def datas(evento: str, meses: int = 132) -> list[str]:
    """Datas aproximadas das divulgacoes, geradas por regra."""
    cfg = EVENTOS[evento]
    hoje = dt.date.today()
    out, y, m = [], hoje.year, hoje.month
    for _ in range(meses):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        if cfg["regra"] == "1a_sexta":
            d = _primeira_sexta(y, m)
        elif cfg["regra"] == "dia1":
            d = dt.date(y, m, 1)
        else:
            d = dt.date(y, m, min(12, calendar.monthrange(y, m)[1]))
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        out.append(d.isoformat())
    return sorted(out)


# ------------------------------------------------ risco conhecido ANTES ---
# Estes eventos possuem uma data aproximada conhecida antes da abertura.
# Eles NAO carregam direcao: o resultado/surpresa ainda e desconhecido.
# A unica entrada em feature por enquanto e Payroll EUA, pois foi o unico
# evento externo com evidencia de dispersao no estudo contemporaneo. Mesmo
# assim ele entra SOMENTE como candidato da cabeca de VOLATILIDADE, nunca no z
# direcional, e precisa passar de novo no walk-forward dessa cabeca.
PRE_EVENTO_ATIVO = True
PRE_EVENTO_EVENTOS = ("Payroll EUA",)


def _data_regra(cfg: dict, y: int, m: int) -> dt.date:
    """Data aproximada de um evento em um mes; sempre rola fim de semana."""
    if cfg["regra"] == "1a_sexta":
        d = _primeira_sexta(y, m)
    elif cfg["regra"] == "dia1":
        d = dt.date(y, m, 1)
    else:
        d = dt.date(y, m, min(12, calendar.monthrange(y, m)[1]))
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def proximas(evento: str, inicio: dt.date | None = None,
             dias: int = 7) -> list[dt.date]:
    """Proximas datas APROXIMADAS no horizonte solicitado."""
    inicio = inicio or dt.date.today()
    fim = inicio + dt.timedelta(days=max(0, dias))
    cfg = EVENTOS[evento]
    out = []
    y, m = inicio.year, inicio.month
    # Dois meses adiante cobrem horizonte curto na virada do mes/ano.
    for _ in range(3):
        d = _data_regra(cfg, y, m)
        if inicio <= d <= fim:
            out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def eventos_em(data: str | dt.date,
               nomes: tuple[str, ...] = PRE_EVENTO_EVENTOS) -> list[str]:
    """Eventos de risco conhecidos de antemao para uma data de pregao."""
    d = dt.date.fromisoformat(data) if isinstance(data, str) else data
    out = []
    for nome in nomes:
        cfg = EVENTOS[nome]
        if _data_regra(cfg, d.year, d.month) == d:
            out.append(nome)
    return out


def risco_calendario(data: str | dt.date) -> float:
    """Feature ex-ante binaria para a cabeca de volatilidade.

    Retorna 1 apenas em data de Payroll EUA pela regra de calendario. Nao usa
    DXY, HSI, valor realizado, consenso ou qualquer dado do proprio dia.
    """
    return 1.0 if PRE_EVENTO_ATIVO and eventos_em(data) else 0.0


def agenda(inicio: dt.date | None = None, dias: int = 7) -> list[dict]:
    """Agenda visivel de eventos; datas sao aproximadas e nunca sinal direcional."""
    inicio = inicio or dt.date.today()
    out = []
    for nome, cfg in EVENTOS.items():
        for d in proximas(nome, inicio, dias):
            r = RESULTADOS.get(nome, {})
            out.append({
                "nome": nome, "data": d.isoformat(),
                "dias_a_frente": (d - inicio).days,
                "instrumento": cfg["instr"], "nota": cfg["nota"],
                "p": r.get("p"), "entra_feature_vol": nome in PRE_EVENTO_EVENTOS,
                "previsao_direcional": False, "data_aproximada": True,
            })
    return sorted(out, key=lambda x: (x["data"], x["nome"]))


def contexto_pre_evento(cadeia: dict | None, inicio: dt.date | None = None,
                        dias: int = 2) -> dict:
    """Contexto de risco por papel, calculado ANTES do evento.

    A forca e a exposicao relativa ja estimada na cadeia (share), nao um
    impacto esperado em retorno. So o Payroll aparece como feature candidata
    para volatilidade; CPI e PMI ficam apenas na agenda porque reprovaram ou
    ficaram marginais no estudo disponivel.
    """
    vec = (cadeia or {}).get("drivers") or {}
    itens = []
    for ev in agenda(inicio, dias):
        exp = vec.get(ev["instrumento"]) or {}
        share, beta = float(exp.get("share", 0.0)), float(exp.get("beta", 0.0))
        urg = 1.0 if ev["dias_a_frente"] == 0 else 0.7
        aplica = bool(ev["entra_feature_vol"])
        itens.append({
            **ev, "share_exposicao": round(share, 4), "beta": round(beta, 6),
            "forca_contexto": round(share * urg if aplica else 0.0, 4),
            "aplica_volatilidade": aplica,
            "motivo": ("feature candidata de volatilidade; precisa passar no walk-forward"
                       if aplica else "apenas agenda/atribuição; não entra em modelo"),
        })
    return {
        "ativo": PRE_EVENTO_ATIVO,
        "previsao_direcional": False,
        "status": "contexto ex-ante, não calibrado",
        "eventos": itens,
        "forca_max": round(max((x["forca_contexto"] for x in itens), default=0.0), 4),
    }


def proxy(evento: str, dret: dict[str, dict[str, float]],
          meses: int = 132) -> list[tuple[str, float]]:
    """(data, surpresa_padronizada) usando o retorno do instrumento sensivel.

    Padroniza pelo desvio do PROPRIO instrumento no periodo, para a escala
    ficar comparavel com a surpresa do Focus (que vem em desvios).
    """
    import statistics as st

    cfg = EVENTOS[evento]
    serie = dret.get(cfg["instr"]) or {}
    if not serie:
        return []
    ds = sorted(serie)
    sd = st.pstdev([serie[d] for d in ds]) or 1.0
    import bisect

    # TOLERANCIA OBRIGATORIA: sem ela, toda data de evento anterior ao inicio
    # da serie casa com o PRIMEIRO pregao disponivel. Na primeira versao isso
    # deu 25 datas distintas para 132 eventos -- o mesmo valor repetido 8x
    # seguidas, com media 1,0 e desvio 0,5 (estatisticas impossiveis entre si).
    TOL = 5
    out, vistos = [], set()
    for d in datas(evento, meses):
        j = bisect.bisect_left(ds, d)
        if j >= len(ds):
            continue
        achado = ds[j]
        if (dt.date.fromisoformat(achado) - dt.date.fromisoformat(d)).days > TOL:
            continue                              # evento fora da cobertura da serie
        if achado in vistos:
            continue                              # um pregao conta uma vez so
        vistos.add(achado)
        out.append((achado, serie[achado] / sd))
    return out


# --------------------------------------------------------------- a porta ---
# MEDIDO (scripts/externo_test.py e scripts/externo_controle.py, 10 anos):
#   CPI EUA      p = 0.689  -> nada
#   PMI China    p = 0.087  -> marginal
#   Payroll EUA  p = 0.000  -> dispersao 0.00362 vs nula 0.00149
#     e o CONTROLE confirma que nao e circularidade: em dias aleatorios a
#     dispersao media e 0.00218 (p95 = 0.00337), p = 0.020 contra o payroll.
#     Ou seja: em dia de payroll a sensibilidade ao dolar e de fato mais
#     dispersa entre os papeis do que num dia comum.
#
# POR QUE MESMO ASSIM NAO ENTRA NO SINAL -- e esta e a parte que importa:
#   A proxy de surpresa E o movimento do DXY no MESMO dia do retorno da acao.
#   Para aplicar o beta voce precisaria conhecer o movimento do dolar, que
#   chega junto com o movimento da acao. Isso EXPLICA o dia, nao o preve.
#
#   Serve para ATRIBUICAO ("o papel caiu porque e exposto ao dolar e hoje teve
#   payroll"), nunca para previsao. Virar preditivo exigiria o consenso
#   publicado antes da divulgacao -- que e justamente o que nao existe de
#   graca para indicadores estrangeiros.
ATIVO = False
RESULTADOS = {
    "CPI EUA":     {"p": 0.689, "passa": False},
    "Payroll EUA": {"p": 0.000, "passa": True, "p_controle": 0.020,
                    "contemporaneo": True},
    "PMI China":   {"p": 0.087, "passa": False},
}


def disponivel() -> tuple[bool, str]:
    """Pode entrar em sinal? Nao -- e o motivo nao e falta de efeito."""
    if not ATIVO:
        return False, (
            "desligada: o Payroll EUA passa no teste (p = 0,000 contra a nula e "
            "p = 0,020 contra dias aleatorios), mas a proxy de surpresa e o "
            "movimento do dolar no MESMO dia do retorno da acao. Isso explica o "
            "dia, nao o preve -- para aplicar o beta seria preciso conhecer o "
            "movimento do dolar, que chega junto. Serve para atribuicao. CPI EUA "
            "(p = 0,689) e PMI China (p = 0,087) nao passam")
    return True, "ok"
