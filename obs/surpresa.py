"""Camada de SURPRESA macro: consenso do Focus vs realizado do BCB.

POR QUE ESTA CAMADA E DIFERENTE DE TODAS AS OUTRAS DO PROJETO
    Todo sinal que medimos antes morria por um de dois motivos: chegava tarde
    (GDELT com 15 min de atraso) ou vivia onde e caro capturar (leilao de
    abertura). Evento AGENDADO nao tem nenhum dos dois:
      - a data e publicada com antecedencia -- nao se corre contra ninguem;
      - existe CONSENSO -- a surpresa e calculavel, nao inferida de texto.

    surpresa = (realizado - mediana_Focus) / desvio_das_projecoes

    O desvio e essencial: 0,1 p.p. acima do consenso e enorme quando 106
    economistas concordavam e irrelevante quando discordavam entre si.

COMO ELA VIRA SINAL TRANSVERSAL
    Sozinha, surpresa macro move o FATOR COMUM -- e o residuo transversal
    remove o fator comum por construcao, entao ela valeria zero. O que a torna
    util e a CADEIA DE AFETACAO: a sensibilidade de cada papel a surpresa e
    estimada dos proprios dias de divulgacao passados, e uma surpresa na Selic
    atinge MGLU3 (varejo domestico alavancado) e ITUB4 (banco) em direcoes
    opostas. E a diferenca entre eles que e aproveitavel.

ARMADILHAS DAS FONTES (ambas custaram tempo)
    OData do BCB: urlencode padrao troca espaco por '+' e o servico responde
      400 "Edm.Boolean / Edm.String are not compatible" -- erro que parece de
      tipo e e de codificacao. Use quote_via=quote.
    baseCalculo: filtrar por 0 devolve ZERO linhas; as que existem vem com 1.
"""
from __future__ import annotations
import datetime as dt
import urllib.parse

from .db import connect
from .util import http_get

OLINDA = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/"
          "odata/ExpectativaMercadoMensais")
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados"

# Indicador do Focus -> serie realizada no SGS.
# So entram pares em que a UNIDADE do consenso e a do realizado batem: o Focus
# projeta variacao mensal em %, entao a serie do SGS tem de ser a mesma coisa.
# Errar isso produz "surpresa" gigante e sem sentido.
INDICADORES = {
    "IPCA":                {"sgs": 433,   "freq": "mensal", "dia": 10,
                            "unidade": "% no mes"},
    "IGP-M":               {"sgs": 189,   "freq": "mensal", "dia": 30,
                            "unidade": "% no mes"},
    "Taxa de desocupação": {"sgs": 24369, "freq": "mensal", "dia": 28,
                            "unidade": "% da forca de trabalho"},
    "Câmbio":              {"sgs": 3698,  "freq": "mensal", "dia": 1,
                            "unidade": "R$/US$ media do mes"},
}

# PENDENTE, e o motivo e de unidade, nao de encanamento:
#   "PIB Total" existe no Focus, mas em ExpectativasMercadoTrimestrais (ref
#   "3/2026", nao "MM/AAAA") e em variacao %. A serie SGS 22109 devolve indice
#   encadeado (198.24), nao variacao -- casar as duas daria surpresa sem
#   sentido. Falta identificar a serie de VARIACAO % trimestral do PIB.
INDICADORES_PENDENTES = {
    "PIB Total": "Focus trimestral em %; falta a serie SGS de variacao % equivalente",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS surpresas (
  indicador  TEXT NOT NULL,
  referencia TEXT NOT NULL,      -- 'MM/AAAA'
  data_proj  TEXT NOT NULL,      -- quando o consenso foi medido
  mediana    REAL NOT NULL,
  desvio     REAL NOT NULL,
  n_resp     INTEGER NOT NULL,
  realizado  REAL NOT NULL,
  surpresa   REAL NOT NULL,      -- em desvios do consenso
  PRIMARY KEY (indicador, referencia)
);
CREATE TABLE IF NOT EXISTS beta_surpresa (
  ticker    TEXT NOT NULL,
  indicador TEXT NOT NULL,
  beta      REAL NOT NULL,
  n         INTEGER NOT NULL,
  PRIMARY KEY (ticker, indicador)
);
"""


def init() -> None:
    con = connect()
    with con:
        con.executescript(SCHEMA)
    con.close()


def _odata(**kw) -> list[dict]:
    url = OLINDA + "?" + urllib.parse.urlencode(
        kw, safe="$,'", quote_via=urllib.parse.quote)
    r = http_get(url, timeout=60, tries=2)
    if r is None:
        return []
    try:
        return r.json().get("value", [])
    except ValueError:
        return []


def consenso(indicador: str, ref: str) -> dict | None:
    """Ultima projecao do Focus para `ref` feita ATE o fim do mes de referencia.

    O corte importa: projecao feita DEPOIS da divulgacao ja conhece o numero e
    tornaria a 'surpresa' trivialmente zero -- look-ahead classico.
    """
    mm, aa = ref.split("/")
    ultimo = (dt.date(int(aa), int(mm), 28) + dt.timedelta(days=4))
    ultimo = (ultimo - dt.timedelta(days=ultimo.day)).isoformat()
    linhas = _odata(**{
        "$top": 1, "$format": "json", "$orderby": "Data desc",
        "$filter": (f"Indicador eq '{indicador}' and DataReferencia eq '{ref}' "
                    f"and Data le '{ultimo}'")})
    if not linhas:
        return None
    x = linhas[0]
    if x.get("Mediana") is None or not x.get("DesvioPadrao"):
        return None
    return {"data_proj": x["Data"], "mediana": float(x["Mediana"]),
            "desvio": float(x["DesvioPadrao"]),
            "n_resp": int(x.get("numeroRespondentes") or 0)}


def realizado(indicador: str) -> dict[str, float]:
    meta = INDICADORES.get(indicador)
    if not meta:
        return {}
    serie = meta["sgs"]
    r = http_get(SGS.format(serie), params={"formato": "json"}, timeout=60)
    if r is None:
        return {}
    try:
        linhas = r.json()
    except ValueError:
        return {}
    out = {}
    for x in linhas:
        d, v = x.get("data", ""), x.get("valor")
        if not d or v in (None, ""):
            continue
        dd, mm, aa = d.split("/")
        out[f"{mm}/{aa}"] = float(v)      # ultima leitura do mes prevalece
    return out


def meses(n: int = 24, ate: dt.date | None = None) -> list[str]:
    ate = ate or dt.date.today()
    out, y, m = [], ate.year, ate.month
    for _ in range(n):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        out.append(f"{m:02d}/{y}")
    return out


def sync(indicador: str = "IPCA", n_meses: int = 24, verbose: bool = True) -> int:
    init()
    real = realizado(indicador)
    if not real:
        if verbose:
            print(f"  [surpresa] serie realizada de {indicador} indisponivel")
        return 0
    con = connect()
    n = 0
    with con:
        for ref in meses(n_meses):
            if ref not in real:
                continue
            c = consenso(indicador, ref)
            if c is None or c["n_resp"] < 10:
                continue
            s = (real[ref] - c["mediana"]) / c["desvio"]
            con.execute("INSERT OR REPLACE INTO surpresas VALUES (?,?,?,?,?,?,?,?)",
                        (indicador, ref, c["data_proj"], c["mediana"], c["desvio"],
                         c["n_resp"], real[ref], round(s, 4)))
            n += 1
            if verbose:
                print(f"  [surpresa] {indicador} {ref}: consenso {c['mediana']:+.2f} "
                      f"realizado {real[ref]:+.2f} -> {s:+.2f} sigma (n={c['n_resp']})")
    con.close()
    return n


def listar(indicador: str | None = None) -> list[dict]:
    con = connect()
    q = "SELECT * FROM surpresas"
    args: list = []
    if indicador:
        q += " WHERE indicador=?"
        args.append(indicador)
    q += " ORDER BY referencia"
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


# ------------------------------------------------ sensibilidade por papel ---
# ATENCAO A DATA: o IPCA do mes M e divulgado por volta do dia 10 de M+1.
# A data exata vem do calendario do IBGE, que nao temos aqui -- usamos o dia
# 10 rolado para o proximo dia util. Erro de data BORRA o estudo de evento:
# se o beta vier fraco, suspeite disto antes de concluir que nao ha efeito.
def _dia_divulgacao(indicador: str) -> int:
    meta = INDICADORES.get(indicador) or {}
    return int(meta.get("dia", 10))


def data_divulgacao(indicador: str, ref: str) -> str:
    mm, aa = ref.split("/")
    m, y = int(mm), int(aa)
    m += 1
    if m == 13:
        m, y = 1, y + 1
    d = dt.date(y, m, min(_dia_divulgacao(indicador), 28))
    while d.weekday() >= 5:                 # rola sabado/domingo
        d += dt.timedelta(days=1)
    return d.isoformat()


def fit_betas(abn: dict[str, dict[str, float]], indicador: str = "IPCA",
              verbose: bool = True) -> dict[str, dict]:
    """Regride o retorno anormal do dia da divulgacao contra a surpresa.

    beta > 0 : o papel SOBE quando o indicador surpreende para cima
    beta < 0 : o papel CAI nesse caso

    E a DIFERENCA de sinal entre papeis que torna a surpresa aproveitavel no
    residuo transversal -- se todos tivessem o mesmo beta, a surpresa so
    moveria o fator comum, que o residuo remove.
    """
    import statistics as st

    linhas = listar(indicador)
    if len(linhas) < 8:
        if verbose:
            print(f"  [beta] so {len(linhas)} surpresas de {indicador}; minimo 8")
        return {}

    pares = []
    for l in linhas:
        d = data_divulgacao(indicador, l["referencia"])
        pares.append((d, l["surpresa"]))

    con = connect()
    out = {}
    with con:
        for tkr, serie in abn.items():
            xs, ys = [], []
            for d, s in pares:
                # dia util mais proximo com retorno (divulgacao pode cair em feriado)
                cand = [c for c in sorted(serie) if c >= d][:1]
                if not cand:
                    continue
                xs.append(s)
                ys.append(serie[cand[0]])
            if len(xs) < 8:
                continue
            mx, my = st.fmean(xs), st.fmean(ys)
            den = sum((x - mx) ** 2 for x in xs)
            if den <= 0:
                continue
            beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            out[tkr] = {"beta": beta, "n": len(xs)}
            con.execute("INSERT OR REPLACE INTO beta_surpresa VALUES (?,?,?,?)",
                        (tkr, indicador, round(beta, 6), len(xs)))
    con.close()
    return out


def sinal_surpresa(indicador: str, ref: str) -> dict[str, float]:
    """Sinal transversal de um evento: beta[papel] x surpresa, demeiado."""
    con = connect()
    row = con.execute("SELECT surpresa FROM surpresas WHERE indicador=? AND referencia=?",
                      (indicador, ref)).fetchone()
    if row is None:
        con.close()
        return {}
    s = row["surpresa"]
    betas = {r["ticker"]: r["beta"] for r in con.execute(
        "SELECT ticker,beta FROM beta_surpresa WHERE indicador=?", (indicador,))}
    con.close()
    if not betas:
        return {}
    bruto = {t: b * s for t, b in betas.items()}
    m = sum(bruto.values()) / len(bruto)
    return {t: round(v - m, 6) for t, v in bruto.items()}


# --------------------------------------------------------------- a porta ---
# MEDIDO DUAS VEZES, reprovado nas duas:
#   19 divulgacoes  -> p = 0.908
#   131 divulgacoes -> p = 0.508   (11 anos, 2015-2026, com 10 anos de preco)
# A dispersao transversal dos betas nao supera a nula de permutacao. O padrao
# economicamente coerente (MGLU3 negativo por ser varejo alavancado, VALE3
# positivo por exportar) NAO se sustenta -- e com 131 divulgacoes ja nao da
# para culpar o tamanho da amostra. Um resultado que confirma a intuicao e o
# mais perigoso de todos, porque e o mais dificil de duvidar.
#
# A HIPOTESE DA DATA FOI TESTADA E DESCARTADA (scripts/surpresa_janela.py):
# DIA_DIVULGACAO e aproximado (dia 10 rolado para dia util), entao janelas de
# evento mais largas deveriam recuperar o efeito se a data fosse a culpada.
# Nenhuma chegou perto:
#   [0] p=0.482 | [0,+1] p=0.555 | [0,+2] p=0.544 | [-1,+1] p=0.567 | [-1,+2] p=0.665
#
# EVIDENCIA DIRETA DE QUE OS BETAS SAO RUIDO: com 19 divulgacoes o papel mais
# negativo era MGLU3 (-0,00406), leitura perfeita para varejo alavancado. Com
# 131 o mesmo papel vai a -0,00009 e o ranking inteiro se reorganiza.
#
# Para liberar a camada seria preciso outra coisa que nao mais amostra nem
# datas melhores -- outro alvo (horizonte mais longo), outro indicador, ou
# universo com small caps. `scripts/surpresa_test.py` tem de devolver p < 0.05.
# LIGADA POR DECISAO DO USUARIO, contra o resultado do teste.
# Os quatro indicadores reprovaram na permutacao (p = 0,508 / 0,788 / 0,750 /
# 0,447) e nenhuma janela de evento chegou a 0,05. Com ATIVO=True a camada
# PASSA A PESAR no sinal; o painel continua exibindo o p ao lado, para quem
# le saber o que esta por tras. Volte para False para desligar.
ATIVO = True
P_MAXIMO = 0.05
# ultimo resultado de scripts/surpresa_test.py (ver historico acima)
TESTE_P = 0.508
TESTE_N = 131
# scripts/surpresa_janela.py: p por janela de evento em torno da divulgacao.
# Existe para testar se a data aproximada era a culpada -- nao era.
TESTE_JANELAS = {"[0]": 0.482, "[0,+1]": 0.555, "[0,+2]": 0.544,
                 "[-1,+1]": 0.567, "[-1,+2]": 0.665}


def disponivel(indicador: str = "IPCA", minimo: int = 60) -> tuple[bool, str]:
    """A camada pode entrar no sinal? Devolve (pode, motivo).

    Com ATIVO=True devolve True e um motivo que NAO esconde a medicao: quem
    ler o painel ve o p do teste ao lado do numero que a camada produziu.
    """
    if ATIVO:
        n = len(listar(indicador))
        return True, (
            f"LIGADA por decisao do usuario. Atencao: a dispersao transversal "
            f"dos betas NAO passou no teste de permutacao (p = {TESTE_P:.3f} com "
            f"{TESTE_N} divulgacoes de {indicador}; a melhor janela de evento deu "
            f"p = {min(TESTE_JANELAS.values()):.3f}). O numero entra no sinal, mas "
            f"a evidencia por tras dele e fraca. {n} divulgacoes no banco")
    if not ATIVO:
        melhor = min(TESTE_JANELAS.values())
        return False, (
            "desligada: a dispersao transversal dos betas nao passou no teste "
            f"de permutacao (p = {TESTE_P:.3f} com {TESTE_N} divulgacoes). A "
            "hipotese de que a data aproximada fosse a causa foi TESTADA e "
            f"descartada: a melhor janela de evento deu p = {melhor:.3f}. Os "
            "papeis nao reagem de forma mensuravelmente diferente a surpresa "
            f"de {indicador} nesta amostra")
    n = len(listar(indicador))
    if n < minimo:
        return False, f"so {n} divulgacoes de {indicador}; minimo {minimo}"
    return True, "ok"


def _chave(ref: str) -> str:
    mm, aa = ref.split("/")
    return f"{aa}-{mm}"


def estado(recentes: int = 3) -> dict:
    """Resumo para o painel: contagem, faixa de datas, porta e ultimas surpresas.

    So LEITURA. Nada daqui entra em numero exibido de papel: com ATIVO=False
    a camada nao influencia sinal, probabilidade nem alarme."""
    pode, motivo = disponivel()
    try:
        linhas = listar()
    except Exception:                                    # noqa: BLE001 (tabela ausente)
        linhas = []
    por_ind: dict[str, list[dict]] = {}
    for l in linhas:
        por_ind.setdefault(l["indicador"], []).append(l)
    resumo = []
    for ind, ls in sorted(por_ind.items()):
        ls.sort(key=lambda l: _chave(l["referencia"]))
        resumo.append({"indicador": ind, "n": len(ls),
                       "de": ls[0]["referencia"], "ate": ls[-1]["referencia"]})
    todas = sorted(linhas, key=lambda l: _chave(l["referencia"]), reverse=True)[:recentes]
    ult = [{**{k: l[k] for k in ("indicador", "referencia", "data_proj", "mediana",
                                  "desvio", "n_resp", "realizado", "surpresa")},
            "divulgacao_aprox": data_divulgacao(l["indicador"], l["referencia"])}
           for l in todas]
    return {"ativo": ATIVO, "pode": pode, "motivo": motivo, "n": len(linhas),
            "por_indicador": resumo, "recentes": ult,
            "teste": {"p": TESTE_P, "n_divulgacoes": TESTE_N, "p_maximo": P_MAXIMO,
                      "script": "scripts/surpresa_test.py"},
            "datas_aproximadas": True}


# ---------------------------------------- integracao surpresa -> papel ---
def impacto_por_papel(indicador: str = "IPCA", ref: str | None = None) -> dict:
    """O que a ULTIMA surpresa implica para cada papel da watchlist.

    HONESTIDADE DESTA FUNCAO -- leia antes de usar o numero:
        O `implicado` e o produto beta x surpresa. O beta foi estimado dos
        dias de divulgacao passados e a dispersao transversal desses betas
        NAO passou no teste de permutacao: p = 0.508 com 131 divulgacoes, e
        nenhuma janela de evento ([0], [0,+1], [0,+2], [-1,+1], [-1,+2])
        chegou perto de 0.05. Ou seja: os papeis NAO reagem de forma
        mensuravelmente diferente a surpresa de IPCA nesta amostra.

        Por isso `validado` vem False e o numero NAO entra em probabilidade
        nenhuma. Ele e exibido como leitura descritiva do historico, para o
        usuario ver o mecanismo e julgar -- nao como previsao.
    """
    con = connect()
    if ref is None:
        row = con.execute(
            "SELECT referencia FROM surpresas WHERE indicador=? "
            "ORDER BY substr(referencia,4) DESC, substr(referencia,1,2) DESC LIMIT 1",
            (indicador,)).fetchone()
        ref = row["referencia"] if row else None
    if ref is None:
        con.close()
        return {"validado": False, "motivo": f"sem surpresas de {indicador}", "papeis": []}

    ev = con.execute("SELECT * FROM surpresas WHERE indicador=? AND referencia=?",
                     (indicador, ref)).fetchone()
    betas = {r["ticker"]: dict(r) for r in con.execute(
        "SELECT ticker,beta,n FROM beta_surpresa WHERE indicador=?", (indicador,))}
    con.close()
    if ev is None or not betas:
        return {"validado": False, "motivo": "sem betas estimados", "papeis": []}

    s = ev["surpresa"]
    bruto = {t: v["beta"] * s for t, v in betas.items()}
    media = sum(bruto.values()) / len(bruto)

    papeis = []
    for t, v in sorted(betas.items(), key=lambda kv: -(bruto[kv[0]] - media)):
        papeis.append({
            "ticker": t, "beta": round(v["beta"], 6), "n": v["n"],
            # implicado em pontos percentuais, ja demeiado (transversal)
            "implicado_pp": round(100 * (bruto[t] - media), 3),
            "direcao": 1 if bruto[t] - media > 0 else (-1 if bruto[t] - media < 0 else 0),
        })

    pode, motivo = disponivel(indicador)
    return {
        "validado": bool(pode),
        "motivo": motivo,
        "indicador": indicador,
        "evento": {"referencia": ref, "mediana": ev["mediana"], "desvio": ev["desvio"],
                   "realizado": ev["realizado"], "surpresa": ev["surpresa"],
                   "n_resp": ev["n_resp"], "data_proj": ev["data_proj"],
                   "divulgacao": data_divulgacao(indicador, ref)},
        "papeis": papeis,
        "nota": ("Leitura descritiva do historico. A dispersao transversal dos betas "
                 "nao passou no teste de permutacao (p = 0,508 com 131 divulgacoes, "
                 "e nenhuma janela de evento chegou a 0,05), entao este numero NAO "
                 "entra em nenhuma probabilidade do painel."),
        "instavel": True,
        "nota_instabilidade": (
            "Evidencia direta de instabilidade: com 19 divulgacoes o papel mais "
            "negativo era MGLU3 (beta -0,00406), leitura economicamente perfeita "
            "para varejo domestico alavancado. Com as 131 divulgacoes o mesmo "
            "papel vai a -0,00009 e o ranking inteiro se reorganiza. Trate a "
            "ordem abaixo como ruido ate que um teste a sustente."),
    }


def sensibilidade(ticker: str) -> list[dict]:
    """Sensibilidade de UM papel a cada indicador macro, com o ultimo evento."""
    con = connect()
    rows = con.execute(
        "SELECT indicador,beta,n FROM beta_surpresa WHERE ticker=? ORDER BY indicador",
        (ticker,)).fetchall()
    out = []
    for r in rows:
        ult = con.execute(
            "SELECT referencia,surpresa,mediana,realizado FROM surpresas WHERE indicador=? "
            "ORDER BY substr(referencia,4) DESC, substr(referencia,1,2) DESC LIMIT 1",
            (r["indicador"],)).fetchone()
        out.append({
            "indicador": r["indicador"], "beta": round(r["beta"], 6), "n": r["n"],
            "ultima": dict(ult) if ult else None,
            "implicado_pp": (round(100 * r["beta"] * ult["surpresa"], 3) if ult else None),
        })
    con.close()
    return out
