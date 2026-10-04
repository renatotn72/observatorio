"""Scorers: texto -> evento estruturado.

Todo scorer devolve o MESMO schema, para serem trocaveis e comparaveis:
    {s: -1..+1 direcao, magnitude: 0..1, event_type: str}

`lexicon` e o baseline honesto: roda offline, sem dependencia, e e fraco --
e justamente por isso serve de piso a ser batido. `llm` e o caminho do meu
desenho anterior (LLM como SENSOR que preenche schema, nunca como oraculo
que preve preco).
"""
from __future__ import annotations
import json
import os
import re

from .db import connect
from .dedupe import novelty
from .util import norm

# ---------------------------------------------------------------- lexicon ----
POS = {
    "lucro": .5, "lucros": .5, "recorde": .7, "alta": .4, "sobe": .45, "subiu": .45,
    "avanca": .35, "avancou": .35, "crescimento": .45, "cresce": .45, "cresceu": .45,
    "supera": .6, "superou": .6, "acima": .4, "melhor": .4, "forte": .3,
    "aprovacao": .4, "aprovado": .4, "aprova": .4, "acordo": .35, "contrato": .4,
    "dividendo": .5, "dividendos": .5, "proventos": .5, "jcp": .45, "recompra": .55,
    "upgrade": .7, "elevou": .45, "eleva": .45, "expansao": .4, "aquisicao": .35,
    "parceria": .3, "investimento": .3, "reducao de divida": .5, "desalavancagem": .45,
    "beat": .6, "outperform": .6, "buy": .5, "surged": .6, "rally": .5,
    "profit": .5, "record": .6, "beats": .6, "raises": .5, "upgraded": .7,
}
NEG = {
    "prejuizo": -.7, "queda": -.45, "cai": -.45, "caiu": -.45, "recuo": -.4,
    "recua": -.4, "despenca": -.7, "tombo": -.65, "perda": -.45, "perdas": -.5,
    "abaixo": -.4, "pior": -.45, "fraco": -.35, "frustra": -.55, "decepciona": -.6,
    "corte": -.45, "corta": -.45, "reduz": -.4, "reducao": -.35, "suspende": -.5,
    "suspensao": -.5, "cancela": -.5, "multa": -.5, "multado": -.5, "processo": -.3,
    "investigacao": -.5, "fraude": -.85, "greve": -.5, "paralisacao": -.5,
    "acidente": -.6, "vazamento": -.55, "rompimento": -.7, "downgrade": -.7,
    "rebaixou": -.6, "rebaixamento": -.6, "renuncia": -.45, "demissao": -.3,
    "liminar": -.4, "divida": -.3, "alavancagem": -.3, "despesa": -.2,
    "miss": -.6, "misses": -.6, "underperform": -.6, "sell": -.5, "plunge": -.7,
    "loss": -.6, "cuts": -.5, "downgraded": -.7, "probe": -.5, "lawsuit": -.4,
}
# Expressoes de VARIAS palavras. O scorer por token nao as enxerga: "juros
# sobre o capital proprio" escrito por extenso passava como neutro enquanto a
# sigla "jcp" pontuava -- a mesma noticia valia coisas diferentes conforme o
# jornal abreviasse ou nao.
PHRASES = {
    "juros sobre o capital proprio": .5, "juros sobre capital proprio": .5,
    "acima do esperado": .55, "abaixo do esperado": -.55,
    "acima das expectativas": .55, "abaixo das expectativas": -.55,
    "aumento de capital": -.3, "sobras de acoes": -.25, "diluicao": -.4,
    "oferta subsequente": -.3, "follow on": -.3,
    "preco-alvo elevado": .6, "preco-alvo reduzido": -.6,
    # "record" e POS (+.6), mas em ingles ele qualifica o substantivo seguinte:
    # "record loss" somava +.6 e -.6 e dava ZERO numa noticia claramente ruim.
    # Frase vem antes do token, entao estas resolvem.
    "record loss": -.75, "record losses": -.75, "record low": -.6,
    "record decline": -.65, "record high": .6, "record profit": .75,
    "recorde de prejuizo": -.75, "prejuizo recorde": -.75,
    "fato relevante": .15, "pedido de recuperacao judicial": -.9,
    "recuperacao judicial": -.8, "day after": 0.0,
    "lucro liquido": .35, "prejuizo liquido": -.6,
    "better than expected": .55, "worse than expected": -.55,
}

NEGATORS = {"nao", "nao ha", "sem", "descarta", "nega", "negou", "desmente", "not", "no", "denies"}
HEDGES = {"pode", "poderia", "deve", "estuda", "avalia", "cogita", "rumor", "boato",
          "especula", "may", "could", "weighs", "considers", "rumored"}

# Tipo de evento -> (regex, materialidade tipica). Espelha o schema que o LLM
# preencheria, para que trocar de scorer nao mude o resto do pipeline.
EVENTS = [
    ("earnings",      r"\b(balanco|resultado|trimestre|lucro liquido|ebitda|earnings)\b", .9),
    ("guidance",      r"\b(guidance|projecao|perspectiva|outlook)\b", .95),
    ("mna",           r"\b(aquisicao|fusao|compra de|incorporacao|merger|acquisition)\b", .9),
    ("rating",        r"\b(upgrade|downgrade|preco-alvo|recomendacao|rating|rebaixou)\b", .7),
    ("dividend",      r"\b(dividendo|dividendos|jcp|proventos|recompra"
                      r"|juros sobre (o )?capital proprio)\b", .75),
    ("equity_offer",  r"\b(aumento de capital|sobras de acoes|oferta subsequente"
                      r"|follow on|diluicao|subscricao)\b", .7),
    ("regulatory",    r"\b(cade|cvm|aneel|anp|anatel|multa|liminar|regulador|probe)\b", .8),
    ("operational",   r"\b(greve|paralisacao|acidente|vazamento|rompimento|producao)\b", .8),
    ("distress",      r"\b(recuperacao judicial|falencia|default|calote"
                      r"|rolagem de divida|covenant)\b", .95),
    ("management",    r"\b(ceo|cfo|presidente|conselho|renuncia|assembleia)\b", .55),
    ("macro_linked",  r"\b(selic|copom|cambio|dolar|inflacao|ipca|petroleo brent|minerio)\b", .4),
]


# --------------------------------------------- posicao do papel no fato ---
# O DEFEITO QUE ISTO CORRIGE (medido em 2026-10-04, caso real no banco):
#   "ANP avanca para reduzir concentracao no mercado de gas APESAR DE
#    RESISTENCIA DA PETROBRAS"  ->  s = +0,350 para PETR4
# "avanca" vale +0,35 no POS, e o scorer soma tokens do TEXTO sem nunca
# perguntar qual e a posicao da empresa no fato. A oracao "apesar da
# resistencia de X" marca X como a parte PERDEDORA -- invisivel para contagem
# de palavras, e o sinal sai com o lado trocado.
#
# `ticker` ja era parametro de score_lexicon e NUNCA era usado. A assinatura
# admitia o papel e o ignorava.
#
# LIMITE DESTA HEURISTICA: ela so pega o marcador adversativo seguido do nome
# da empresa numa janela curta. "Petrobras avanca apesar da resistencia do
# MPF" NAO inverte, porque quem vem depois do marcador e o MPF -- e e esse o
# teste que separa a regra util do estrago.
ADVERSO = (
    r"apesar d[ao]s? resistencia d[ao]s?", r"apesar d[ao]s?", r"contra",
    r"resistencia d[ao]s?", r"enfrenta", r"derrota d[ao]s?",
    r"em desfavor d[ao]s?", r"prejudica", r"as custas d[ao]s?",
    r"reduzir? (?:o )?poder d[ao]s?", r"reduzir? (?:a )?concentracao",
)
FAVORAVEL = (
    r"a favor d[ao]s?", r"beneficia", r"vitoria d[ao]s?",
    r"em favor d[ao]s?", r"favorece",
)
JANELA_PAPEL = 60        # caracteres apos o marcador em que se procura o nome


def _posicao_no_fato(text: str, aliases: list[str]) -> int:
    """+1 se a empresa e a parte beneficiada, -1 se e a perdedora, 0 indefinido.

    `text` ja vem normalizado por norm(); `aliases` tambem.
    """
    if not aliases:
        return 0
    def perto(padroes):
        for pad in padroes:
            for m in re.finditer(pad, text):
                trecho = text[m.end():m.end() + JANELA_PAPEL]
                if any(a in trecho for a in aliases):
                    return True
        return False
    adverso = perto(ADVERSO)
    favoravel = perto(FAVORAVEL)
    if adverso and not favoravel:
        return -1
    if favoravel and not adverso:
        return +1
    return 0


def _aliases_norm(ticker: str) -> list[str]:
    if not ticker:
        return []
    try:
        from . import config
        meta = config.tickers().get(ticker.upper(), {}) or {}
    except Exception:                                    # noqa: BLE001
        return []
    brutos = list(meta.get("aliases", [])) + [meta.get("name", "")]
    # so nomes, nao codigos: "PETR4" nao aparece em "resistencia da Petrobras"
    return [norm(a) for a in brutos if a and not re.fullmatch(r"[A-Z]{4}\d+", a)]


def score_lexicon(title: str, body: str | None = None, ticker: str = "") -> dict:
    """Soma ponderada com negacao local e desconto de hedge."""
    text = norm(f"{title} {(body or '')[:600]}")
    toks = text.split()
    total, hits = 0.0, 0

    for phrase, w in PHRASES.items():          # multi-palavra antes dos tokens
        if phrase in text:
            total += w
            hits += 1
    for i, t in enumerate(toks):
        w = POS.get(t) or NEG.get(t)
        if w is None:
            continue
        window = set(toks[max(0, i - 3):i])
        if window & NEGATORS:
            w = -w * 0.7            # negado e mais fraco que o afirmado oposto
        total += w
        hits += 1

    s = 0.0 if hits == 0 else max(-1.0, min(1.0, total / (hits ** 0.5)))

    # CONDICIONA AO PAPEL. Se a empresa e a parte perdedora do fato, uma acao
    # de tom positivo e MA para ela. Inverte-se o sinal e corta-se a
    # magnitude: a regra acerta o lado mas e heuristica, entao nao deve entrar
    # com a mesma confianca de uma manchete direta sobre a empresa.
    posicao = _posicao_no_fato(text, _aliases_norm(ticker))
    if posicao < 0 and s > 0:
        s = -s
    elif posicao > 0 and s < 0:
        s = -s

    event_type, mag = "unclassified", 0.25
    for name, pat, m in EVENTS:
        if re.search(pat, text):
            event_type, mag = name, m
            break

    if posicao != 0:
        mag *= 0.85                 # heuristica acerta o lado, nao a intensidade
    if set(toks) & HEDGES:          # rumor/especulacao: materialidade cortada
        mag *= 0.45
    if hits == 0:
        mag *= 0.3

    return {"s": round(s, 4), "magnitude": round(mag, 4), "event_type": event_type,
            "raw": json.dumps({"hits": hits, "sum": round(total, 3)})}


# -------------------------------------------------------------------- llm ----
# O schema pede FATOS E IMPLICACAO, nunca previsao de preco. "ja_precificado"
# e o campo que o lexico nao tem como preencher e que mais muda o resultado:
# numa amostra real de 5 materias, o lexico deu peso 1.12 ao conjunto e o
# julgamento estruturado deu 0.18 -- 84% a menos -- porque 4 delas eram
# dividendo rotineiro, etapa procedimental ou retrospectiva.
LLM_SYSTEM = """Voce extrai fatos de noticias economicas para um sistema de pesquisa.
Voce NAO preve precos. Voce NAO usa conhecimento sobre o que aconteceu depois
da materia. Se a data nao estiver no texto, nao a infira."""

LLM_SCHEMA_PROMPT = """Leia a noticia e avalie a implicacao PARA A EMPRESA indicada.

ANTES DE DAR A NOTA, identifique qual e a POSICAO DA EMPRESA no fato. Esta e a
parte que mais se erra: e facil pontuar o TOM do texto em vez do EFEITO sobre a
empresa. Exemplo real de erro: "ANP avanca para reduzir concentracao no mercado
de gas apesar de resistencia da Petrobras" foi pontuada +0,35 para a PETR4 --
o texto tem tom construtivo ("avanca", "programa do governo"), mas a oracao
"apesar da resistencia da Petrobras" diz que a empresa e a parte PERDEDORA.
A nota correta e negativa.

Responda SOMENTE um JSON:
{"papel_no_fato": "<beneficiada|prejudicada|neutra|apenas_citada>",
 "s": <-1..1 direcao da implicacao para a empresa>,
 "magnitude": <0..1 materialidade frente ao tamanho da empresa>,
 "event_type": "<earnings|guidance|mna|rating|dividend|equity_offer|regulatory|
                 operational|management|distress|subsidio|retrospectiva|outro>",
 "ja_precificado": <true se for rotina esperada, etapa procedimental de algo ja
                    anunciado, repercussao de fato antigo, ou retrospectiva>,
 "is_rumor": <true se for boato, fonte anonima ou especulacao>,
 "quote": "<o trecho do texto que justifica>",
 "por_que": "<uma frase curta>"}

Regras:
- "magnitude" e relativa ao TAMANHO da empresa: R$1 bi e grande para uma
  small cap e irrelevante para uma de R$600 bi.
- Retrospectiva ("acao subiu 5% em setembro") = ja_precificado true, magnitude
  proxima de zero: o movimento ja ocorreu.
- Nao invente numeros que nao estejam no texto.
- "papel_no_fato" e OBRIGATORIO e deve vir ANTES da nota: decida a posicao,
  depois pontue. Se a empresa aparece como alvo de acao de terceiro (orgao
  regulador, Ministerio Publico, concorrente) ou como parte que resiste,
  contesta ou perde, ela e "prejudicada" -- mesmo que o texto descreva a acao
  do terceiro em tom neutro ou positivo.
- "apenas_citada" quando a empresa serve de contexto e o fato nao muda o
  resultado dela; nesse caso use s proximo de 0 e magnitude baixa.
- Coerencia obrigatoria: "prejudicada" exige s < 0; "beneficiada" exige s > 0.
  Se nao conseguir sustentar isso com um trecho do texto, use "neutra"."""


def _llm_para_score(obj: dict) -> dict:
    """Converte a resposta do LLM para o mesmo schema de score_lexicon."""
    s = max(-1.0, min(1.0, float(obj.get("s", 0.0))))
    mag = max(0.0, min(1.0, float(obj.get("magnitude", 0.0))))
    if obj.get("ja_precificado"):
        mag *= 0.25          # ja no preco: pesa pouco, mas nao zero
    if obj.get("is_rumor"):
        mag *= 0.45
    return {"s": round(s, 4), "magnitude": round(mag, 4),
            "event_type": obj.get("event_type", "outro"),
            "raw": json.dumps(obj, ensure_ascii=False)}


def score_llm(title: str, body: str | None = None, ticker: str = "") -> dict:
    """Extracao estruturada por LLM. Exige OBS_LLM_API_KEY e OBS_LLM_URL.

    CONTAMINACAO -- a armadilha que invalida backtest historico:
        Um modelo treinado ate hoje SABE o que aconteceu com o papel. Se ele
        conseguir inferir a data da materia, ele vaza o futuro e o seu
        resultado historico nao vale nada. Por isso o prompt pede so fatos do
        texto, proibe inferir data e nunca pede desfecho -- e por isso a
        validacao final tem de ser em janela POSTERIOR ao cutoff do modelo.
    """
    import urllib.request

    # OBS_LLM_KEY e o nome usado por obs/llm_client.py e pelo handoff.
    # OBS_LLM_API_KEY fica aceito por compatibilidade com a versao anterior:
    # ter dois nomes para a mesma variavel ja fez o scorer falhar em silencio.
    key = os.environ.get("OBS_LLM_KEY") or os.environ.get("OBS_LLM_API_KEY")
    url = os.environ.get("OBS_LLM_URL")
    model = os.environ.get("OBS_LLM_MODEL", "")
    if not key or not url:
        raise RuntimeError(
            "Defina OBS_LLM_KEY e OBS_LLM_URL (e OBS_LLM_MODEL) para usar "
            "--scorer llm. Sem isso, use --scorer lexicon.")

    texto = f"Empresa: {ticker}\nTitulo: {title}"
    if body:
        texto += f"\nTexto: {body[:4000]}"

    payload = json.dumps({
        "model": model,
        "max_tokens": 400,
        "system": LLM_SYSTEM,
        "messages": [{"role": "user", "content": LLM_SCHEMA_PROMPT + "\n\n" + texto}],
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
    except Exception as exc:                                   # noqa: BLE001
        raise RuntimeError(f"chamada ao LLM falhou: {exc}") from exc

    # aceita os dois formatos comuns de resposta
    txt = ""
    if isinstance(resp.get("content"), list) and resp["content"]:
        txt = resp["content"][0].get("text", "")
    elif resp.get("choices"):
        txt = resp["choices"][0].get("message", {}).get("content", "")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError(f"resposta do LLM sem JSON: {txt[:200]}")
    return _llm_para_score(json.loads(m.group(0)))


# --------------------------------------------------------------- ensemble ---
def score_ensemble(title: str, body: str | None = None, ticker: str = "") -> dict:
    """Roda os dois e combina -- mas NAO por media, e aqui esta o porque.

    Os dois leem o MESMO texto e, na amostra real, nunca apontaram para lados
    opostos: concordam no sinal e divergem no peso (mediana: o LLM pesa 89%
    menos). Media de dois leitores que concordam nao adiciona informacao --
    sinais correlacionados nao somam em quadratura.

    O que cada um faz melhor:
      LLM     -- peso. So ele sabe que JCP de banco e rotina esperada e que
                 leilao de sobras e etapa procedimental de algo ja anunciado.
      lexico  -- cobertura e custo. Roda offline em toda materia; o LLM custa
                 por chamada e nao escala para milhares de artigos por dia.

    Entao: o LLM manda no peso, o lexico cobre onde o LLM falha ou nao rodou.

    O TERCEIRO CAMPO e o que nao existia antes: `desacordo` = quanto o lexico
    grita mais alto que o LLM. Isso mede "parece noticia mas nao e" -- e um
    candidato a feature, principalmente para a cabeca de VOLATILIDADE, e nao
    foi medido ainda.
    """
    lex = score_lexicon(title, body)
    try:
        llm = score_llm(title, body, ticker)
    except (RuntimeError, NotImplementedError) as exc:
        lex["raw"] = json.dumps({"fallback": "lexicon", "motivo": str(exc)[:120]})
        lex["desacordo"] = 0.0
        return lex

    peso_lex = abs(lex["s"]) * lex["magnitude"]
    peso_llm = abs(llm["s"]) * llm["magnitude"]
    out = dict(llm)
    if peso_llm <= 1e-6 and peso_lex > 0.05:
        # o LLM nao viu nada e o lexico viu: mantem o lexico, com peso cortado
        out = {**lex, "magnitude": round(lex["magnitude"] * 0.4, 4)}
    out["desacordo"] = round(peso_lex - peso_llm, 4)
    out["raw"] = json.dumps({"lexico": lex, "llm": llm,
                             "peso_lex": round(peso_lex, 4),
                             "peso_llm": round(peso_llm, 4)}, ensure_ascii=False)
    return out


SCORERS = {"lexicon": score_lexicon, "llm": score_llm, "ensemble": score_ensemble}


# Idiomas que o lexico de fato cobre. POS/NEG/PHRASES tem palavra em portugues
# e em ingles -- mais nada.
#
# POR QUE ISTO E UMA PORTA E NAO UM DETALHE
# Sem ela, manchete em idioma nao coberto entra com peso > 0 e nota ~0, puxando
# o sinal para o meio. Pior: pode INVERTER. MEDIDO com a mesma noticia de
# desastre da Vale:
#     portugues  s = -0.700   (certo)
#     ingles     s =  0.000   ("record" cancela "loss")
#     alemao     s =  0.000   (nenhuma palavra no lexico)
#     frances    s = +0.600   ERRADO -- "perte record" casa com o POS "record"
# Um idioma vizinho e pior que um idioma distante, porque gera falso positivo
# em vez de silencio. O scorer `llm` nao precisa desta porta: ele le o idioma.
IDIOMAS_LEXICO = {"portuguese", "english", "pt", "en", "pt-br", "en-us", "en-gb"}


def _idioma_coberto(lang: str | None, scorer: str) -> bool:
    if scorer != "lexicon":
        return True
    lg = (lang or "").strip().lower()
    # lang vazio = origem que nao declarou. Deixa passar: a maioria e PT/EN e
    # barrar tudo que nao se identifica custaria mais do que o erro evitado.
    return not lg or lg in IDIOMAS_LEXICO


def run(scorer: str = "lexicon", limit: int = 5000, min_relevance: float = 0.35) -> int:
    """Pontua pares (artigo, ticker) ainda sem score para este scorer."""
    fn = SCORERS[scorer]
    con = connect()
    rows = con.execute("""
        SELECT m.article_id, m.ticker, m.relevance, a.title, a.body, a.lang
        FROM mentions m JOIN articles a ON a.id = m.article_id
        WHERE m.ticker != '__none__' AND m.relevance >= ?
          AND NOT EXISTS (SELECT 1 FROM scores s
                          WHERE s.article_id=m.article_id AND s.ticker=m.ticker AND s.scorer=?)
        ORDER BY a.published_ts DESC LIMIT ?""", (min_relevance, scorer, limit)).fetchall()

    n = pulados = 0
    with con:
        for r in rows:
            if not _idioma_coberto(r["lang"], scorer):
                pulados += 1
                continue
            out = fn(r["title"], r["body"], r["ticker"]) \
                if scorer in ("llm", "ensemble") else fn(r["title"], r["body"])
            nov = novelty(con, r["article_id"])
            con.execute(
                "INSERT OR REPLACE INTO scores"
                "(article_id,ticker,scorer,s,magnitude,event_type,novelty,raw)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (r["article_id"], r["ticker"], scorer, out["s"], out["magnitude"],
                 out["event_type"], nov, out.get("raw")))
            n += 1
    con.close()
    if pulados:
        print(f"  [score] {pulados} pulados por idioma fora do lexico "
              f"(use --scorer llm para esses)")
    return n
