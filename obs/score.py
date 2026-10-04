"""Scorers: texto -> evento estruturado.

Todo scorer devolve o MESMO schema, para serem trocaveis e comparaveis:
    {s: -1..+1 direcao, magnitude: 0..1, event_type: str}

QUEM LE A NOTICIA, DESDE 2026-10-04: o LLM. `SCORER_PADRAO = "llm"`.
A troca nao e de gosto; os defeitos do lexico estao MEDIDOS neste arquivo:

  - "ANP avanca para reduzir concentracao no mercado de gas APESAR DE
    RESISTENCIA DA PETROBRAS" -> s = +0,350 para PETR4. Contagem de palavras
    nao tem como perguntar qual e a POSICAO da empresa no fato.
  - a mesma noticia de desastre da Vale: -0,70 em portugues, 0,00 em ingles
    ("record" cancelava "loss"), +0,60 em frances ("perte record"). O lado
    depende do idioma do jornal.
  - "juros sobre o capital proprio" valia 0 e "JCP" valia +0,45: a mesma
    noticia pontuava diferente conforme o jornal abreviasse.
  - 44% dos eventos caem em `unclassified` (obs/evento.py).
  - `ja_precificado` nao e preenchivel por lexico nenhum. Em 5 materias reais,
    o lexico deu peso 1,12 ao conjunto e o julgamento estruturado deu 0,18 --
    84% a menos -- porque 4 eram dividendo rotineiro, etapa procedimental ou
    retrospectiva.

Cada correcao acima foi uma regra nova empilhada sobre contagem de palavras
(PHRASES, NEGATORS, HEDGES, ADVERSO/FAVORAVEL, IDIOMAS_LEXICO). O limite e
estrutural: o lexico le TOM, e o alvo exige EFEITO SOBRE A EMPRESA.

O QUE *NAO* MUDOU, E E O PONTO QUE SUSTENTA O PROJETO
O LLM continua SENSOR, nunca oraculo (docs/decision-log.md). Ele le o texto e
preenche schema de fatos; nao recebe pergunta de preco, nao recebe data e nao
e consultado sobre desfecho. Trocar o leitor melhora a LEITURA; nao cria
previsao de direcao, que segue reprovada em 6 de 6 testes (docs/metricas.md).

`lexicon` permanece, com dois papeis dos quais nao se abre mao:
  1. PISO AUDITAVEL. Deterministico, offline, reproduzivel em 2016 e em 2036.
     E a referencia contra a qual o ganho do LLM e medido -- sem piso, "melhor"
     e opiniao.
  2. REDE. Sem proxy, sem autorizacao ou sem rede, o pipeline nao para: cai
     para o lexico DIZENDO que caiu (ver `resolver`), e a coluna
     `signals.scorer` grava quem leu.

CONTAMINACAO -- a armadilha que decide onde o LLM pode e nao pode entrar
Um modelo com cutoff SABE o que aconteceu com o papel. Lendo manchete de 2019
ele pode estar lembrando do desfecho em vez de lendo o texto. Por isso:
  - ao vivo (noticia de hoje, desfecho ainda nao existe): LLM, sem ressalva;
  - no backfill de 10 anos: o padrao continua `lexicon` (obs/historico.py), e
    pontuar historico com LLM exige --scorer llm explicito e vem com aviso;
  - a validacao do canal de texto so vale em janela POSTERIOR ao cutoff.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time

from . import evento, llm_client
from .db import connect
from .dedupe import novelty
from .util import norm, sem_html

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
    # sem_html antes do corte: 73% dos corpos comecam com <img src="...">, e a
    # tag empurra texto real para fora da janela. MEDIDO: a mediana de texto
    # util nestes 600 chars sobe de 352 para 384 caracteres (+9%).
    # Ver obs/util.py:sem_html.
    text = norm(f"{title} {sem_html(body)[:600]}")
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
 "orientacao": [<"passado" se relata fato consumado, "presente" se o fato esta
                 em curso, "futuro" se e guidance, projecao, risco prospectivo
                 ou processo ainda a decidir. PODE TER MAIS DE UMA: decisao ja
                 proferida mais recurso pendente = ["passado","futuro"]>],
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
  Se nao conseguir sustentar isso com um trecho do texto, use "neutra".
- "orientacao" e CONJUNTO, nao escolha unica. A pergunta nao e "quando saiu a
  materia", e "a que tempo o CONTEUDO se refere". Exemplo real: recurso
  protocolado na segunda contestando decisao de quarta tem os dois tempos --
  a decisao e o protocolo sao consumados (passado) e o recurso ainda pode
  mudar o resultado (futuro). Responda ["passado","futuro"].
- Retrospectiva de preco e "passado". Guidance e "futuro". Data de divulgacao
  ainda por vir e "futuro"."""


# --------------------------------------------------- infraestrutura do LLM ---
# VERSAO DO PROMPT. Entra na chave do cache: mudar o prompt invalida as
# leituras antigas em vez de servir resposta velha sob regra nova.
PROMPT_VERSAO = "2026-10-04.1"
LIMITE_CORPO = 4000          # caracteres do corpo enviados ao modelo
TENTATIVAS = 3               # a chamada e idempotente (temperatura 0)
ESPERA_S = (1.5, 4.0)        # recuo entre tentativas

# Teto de chamadas por rodada. Existe porque a fila de pontuacao nao tem
# tamanho conhecido: um `backfill-rss --paginas 150` enfileira milhares de
# pares (artigo, ticker) e, sem teto, a primeira rodada gastaria a corpus
# inteira em chamadas antes de alguem ver o custo. O que sobrar fica pendente
# e entra na proxima rodada -- `run` so pontua par SEM score.
MAX_CHAMADAS_PADRAO = int(os.environ.get("OBS_LLM_MAX_CHAMADAS", "400"))

# Quantas falhas seguidas no inicio da rodada abortam tudo. Sem isso, proxy
# derrubado = 400 chamadas perdidas e 400 linhas de erro no log.
FALHAS_SEGUIDAS_ABORTA = 5

# Contadores da ultima rodada. Modulo-level de proposito: `run` os imprime e
# `score-estado` os le. Nao entram em nenhum calculo.
CONTADORES = {"chamadas": 0, "cache": 0, "cluster": 0, "falhas": 0, "teto": 0}


def _zera_contadores() -> None:
    for k in CONTADORES:
        CONTADORES[k] = 0


def _chave_cache(ticker: str, title: str, body: str | None, modelo: str) -> str:
    # O MESMO texto que vai ao modelo, ja limpo. Chavear pelo corpo cru faria
    # duas copias com markup diferente e texto identico pagarem duas leituras.
    bruto = "|".join([PROMPT_VERSAO, modelo, (ticker or "").upper(),
                      title or "", sem_html(body)[:LIMITE_CORPO]])
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _cache_le(chave: str) -> dict | None:
    try:
        con = connect()
        r = con.execute("SELECT resposta FROM llm_cache WHERE chave=?",
                        (chave,)).fetchone()
        con.close()
    except Exception:                                        # noqa: BLE001
        return None            # banco antigo sem a tabela: segue sem cache
    if not r:
        return None
    try:
        return json.loads(r["resposta"])
    except Exception:                                        # noqa: BLE001
        return None


def _cache_grava(chave: str, modelo: str, obj: dict) -> None:
    try:
        con = connect()
        with con:
            con.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?)",
                        (chave, modelo, json.dumps(obj, ensure_ascii=False),
                         int(time.time())))
        con.close()
    except Exception:                                        # noqa: BLE001
        pass                   # cache e conveniencia; falha nele nao para nada


def _llm_para_score(obj: dict) -> dict:
    """Converte a resposta do LLM para o mesmo schema de score_lexicon."""
    s = max(-1.0, min(1.0, float(obj.get("s", 0.0))))
    mag_bruta = max(0.0, min(1.0, float(obj.get("magnitude", 0.0))))
    papel = (obj.get("papel_no_fato") or "").strip().lower() or None

    # COERENCIA VERIFICADA, NAO PEDIDA. O prompt exige "prejudicada => s < 0",
    # mas instrucao nao e garantia -- e este e justamente o erro que motivou a
    # troca de leitor (o caso ANP/Petrobras). Entao o codigo confere e, quando
    # o modelo se contradiz, obedece ao campo que o prompt manda decidir
    # PRIMEIRO (a posicao no fato) e inverte a nota, registrando a
    # contradicao. `incoerencia` e contavel: se for frequente, o prompt esta
    # errado, e isso aparece num GROUP BY em vez de passar em silencio.
    incoerencia = None
    if papel == "prejudicada" and s > 0:
        incoerencia, s = "prejudicada com s>0", -s
    elif papel == "beneficiada" and s < 0:
        incoerencia, s = "beneficiada com s<0", -s

    mag = mag_bruta
    if obj.get("ja_precificado"):
        mag *= 0.25          # ja no preco: pesa pouco, mas nao zero
    if obj.get("is_rumor"):
        mag *= 0.45
    if papel == "apenas_citada":
        mag *= 0.30          # a empresa e contexto, nao parte do fato

    # ORIENTACAO: conjunto, validado contra os tres valores aceitos. Modelo
    # que responde "ontem" ou "Q3" nao entra na coluna -- cai para a regra.
    orient = obj.get("orientacao")
    if isinstance(orient, str):
        orient = [orient]
    if isinstance(orient, (list, tuple)):
        validos = {evento.PASSADO, evento.PRESENTE, evento.FUTURO}
        orient = sorted({str(x).strip().lower() for x in orient}
                        & validos) or None
    else:
        orient = None

    raw = dict(obj)
    raw["magnitude_bruta"] = round(mag_bruta, 4)
    if incoerencia:
        raw["incoerencia"] = incoerencia
    return {"s": round(s, 4), "magnitude": round(mag, 4),
            "event_type": obj.get("event_type", "outro"),
            "orientacao_llm": orient,
            "papel_no_fato": papel,
            "ja_precificado": 1 if obj.get("ja_precificado") else 0,
            "is_rumor": 1 if obj.get("is_rumor") else 0,
            "quote": (obj.get("quote") or "")[:500] or None,
            "raw": json.dumps(raw, ensure_ascii=False)}


def score_llm(title: str, body: str | None = None, ticker: str = "",
              usar_cache: bool = True) -> dict:
    """Extracao estruturada por LLM: o leitor primario da notica.

    Passa por `obs/llm_client.py`, e isso NAO e detalhe de estilo. A versao
    anterior montava a propria chamada urllib e exigia so OBS_LLM_KEY e
    OBS_LLM_URL -- ou seja, mandava o texto para fora sem consultar
    OBS_ALLOW_EXTERNAL_LLM, a porta de autorizacao que o resto do projeto
    respeita (docs/relatorios.md: "nenhum texto sai da maquina por padrao").
    O cliente unico tambem fixa temperatura 0, sem o que duas rodadas sobre a
    mesma materia dao notas diferentes e nenhuma medicao e reproduzivel.

    Levanta RuntimeError quando nao ha leitura: o chamador decide se cai para
    o lexico (`ensemble`) ou deixa o par pendente (`llm`).
    """
    modelo = os.environ.get("OBS_LLM_MODEL", "")
    chave = _chave_cache(ticker, title, body, modelo)
    if usar_cache:
        em_cache = _cache_le(chave)
        if em_cache is not None:
            CONTADORES["cache"] += 1
            return _llm_para_score(em_cache)

    ok, motivo = llm_client.enabled()
    if not ok:
        raise RuntimeError(
            f"LLM nao autorizado ou nao configurado: {motivo}. "
            "Defina OBS_ALLOW_EXTERNAL_LLM=1, OBS_LLM_URL, OBS_LLM_KEY e "
            "OBS_LLM_MODEL (scripts/iniciar.sh faz isso com o proxy local), "
            "ou pontue com --scorer lexicon.")

    texto = f"Empresa: {ticker}\nTitulo: {title}"
    corpo = sem_html(body)          # markup gasta janela e nao carrega fato
    if corpo:
        texto += f"\nTexto: {corpo[:LIMITE_CORPO]}"

    erro = ""
    for tentativa in range(TENTATIVAS):
        r = llm_client.chat_json(LLM_SYSTEM, LLM_SCHEMA_PROMPT + "\n\n" + texto,
                                 max_tokens=400)
        CONTADORES["chamadas"] += 1
        if r.get("ok") and isinstance(r.get("data"), dict):
            obj = r["data"]
            _cache_grava(chave, modelo, obj)
            return _llm_para_score(obj)
        erro = str(r.get("error") or "resposta sem JSON de objeto")
        if tentativa < TENTATIVAS - 1:
            time.sleep(ESPERA_S[min(tentativa, len(ESPERA_S) - 1)])
    raise RuntimeError(f"chamada ao LLM falhou apos {TENTATIVAS} tentativas: {erro}")


# --------------------------------------------------------------- ensemble ---
def score_ensemble(title: str, body: str | None = None, ticker: str = "") -> dict:
    """Roda os dois e combina -- mas NAO por media, e aqui esta o porque.

    Os dois leem o MESMO texto e, na amostra real, nunca apontaram para lados
    opostos: concordam no sinal e divergem no peso (mediana: o LLM pesa 89%
    menos). Media de dois leitores que concordam nao adiciona informacao --
    sinais correlacionados nao somam em quadratura.

    O que cada um faz melhor:
      LLM     -- leitura. So ele sabe que JCP de banco e rotina esperada, que
                 leilao de sobras e etapa procedimental de algo ja anunciado,
                 e que "apesar da resistencia da Petrobras" poe a empresa do
                 lado perdedor.
      lexico  -- disponibilidade e custo. Roda offline em toda materia; o LLM
                 custa por chamada e depende de proxy de pe.

    Entao: o LLM manda, o lexico cobre onde o LLM falhou ou nao rodou.

    O TERCEIRO CAMPO e o que nao existia antes: `desacordo` = quanto o lexico
    grita mais alto que o LLM. Isso mede "parece noticia mas nao e" -- e um
    candidato a feature, principalmente para a cabeca de VOLATILIDADE, e nao
    foi medido ainda.
    """
    # COM o ticker. Sem ele, a perna do lexico perde a heuristica de posicao
    # no fato e fica mais fraca aqui do que rodando sozinha.
    lex = score_lexicon(title, body, ticker)
    try:
        llm = score_llm(title, body, ticker)
    except (RuntimeError, NotImplementedError) as exc:
        lex["raw"] = json.dumps({"fallback": "lexicon", "motivo": str(exc)[:160]},
                                ensure_ascii=False)
        lex["desacordo"] = 0.0
        return lex

    peso_lex = abs(lex["s"]) * lex["magnitude"]
    peso_llm = abs(llm["s"]) * llm["magnitude"]
    out = dict(llm)
    if peso_llm <= 1e-6 and peso_lex > 0.05:
        # o LLM nao viu nada e o lexico viu: mantem o lexico, com peso cortado
        out = {**lex, "magnitude": round(lex["magnitude"] * 0.4, 4),
               "papel_no_fato": llm.get("papel_no_fato"),
               "ja_precificado": llm.get("ja_precificado"),
               "is_rumor": llm.get("is_rumor"), "quote": llm.get("quote")}
    out["desacordo"] = round(peso_lex - peso_llm, 4)
    out["raw"] = json.dumps({"lexico": lex, "llm": llm,
                             "peso_lex": round(peso_lex, 4),
                             "peso_llm": round(peso_llm, 4)}, ensure_ascii=False)
    return out


SCORERS = {"lexicon": score_lexicon, "llm": score_llm, "ensemble": score_ensemble}
# Scorers que dependem de rede/proxy. Os outros rodam sempre.
PRECISAM_LLM = {"llm", "ensemble"}
# O LEITOR PADRAO. Era "lexicon" ate 2026-10-04; ver o docstring do modulo.
# Env var em vez de constante editada: a Central de Operacoes e o cron sobem o
# mesmo codigo, e trocar leitor nao deveria exigir patch.
SCORER_PADRAO = (os.environ.get("OBS_SCORER") or "llm").strip().lower()


def resolver(scorer: str | None = None, verbose: bool = True) -> tuple[str, str]:
    """Qual scorer vai rodar de fato, e por que.

    DEGRADA, MAS NUNCA EM SILENCIO. Um painel que esvazia porque o proxy caiu
    e pior que um painel que diz "lendo com o lexico porque o proxy caiu": o
    primeiro parece "nao houve noticia", que e a conclusao errada mais comum
    deste projeto (docs/como-usar.md, secao 6).
    """
    pedido = (scorer or SCORER_PADRAO).strip().lower()
    if pedido not in SCORERS:
        raise ValueError(f"scorer desconhecido: {pedido!r}; "
                         f"use um de {sorted(SCORERS)}")
    if pedido not in PRECISAM_LLM:
        return pedido, "escolhido"
    ok, motivo = llm_client.enabled()
    if ok:
        return pedido, "escolhido"
    if verbose:
        print(f"  [score] '{pedido}' indisponivel ({motivo}); "
              f"lendo com 'lexicon' -- o piso auditavel, nao o produto")
    return "lexicon", f"'{pedido}' indisponivel: {motivo}"


def estado() -> dict:
    """Quem le a noticia agora, com que cobertura. Alimenta /api/status."""
    efetivo, motivo = resolver(verbose=False)
    ok, motivo_llm = llm_client.enabled()
    out = {"padrao": SCORER_PADRAO, "efetivo": efetivo, "motivo": motivo,
           "llm_autorizado": ok, "llm_motivo": motivo_llm,
           "modelo": os.environ.get("OBS_LLM_MODEL") or None,
           "prompt_versao": PROMPT_VERSAO, "cobertura": {}, "cache": 0,
           "ultima_rodada": dict(CONTADORES)}
    try:
        con = connect()
        for r in con.execute("SELECT scorer, COUNT(*) n FROM scores "
                             "GROUP BY scorer ORDER BY n DESC").fetchall():
            out["cobertura"][r["scorer"]] = r["n"]
        out["pendentes"] = con.execute(
            """SELECT COUNT(*) FROM mentions m
               WHERE m.ticker != '__none__' AND m.relevance >= 0.35
                 AND NOT EXISTS (SELECT 1 FROM scores s
                                 WHERE s.article_id=m.article_id
                                   AND s.ticker=m.ticker AND s.scorer=?)""",
            (efetivo,)).fetchone()[0]
        try:
            out["cache"] = con.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
        except Exception:                                    # noqa: BLE001
            out["cache"] = 0
        con.close()
    except Exception as exc:                                 # noqa: BLE001
        out["erro"] = str(exc)[:200]
    return out


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


def _reuso_de_cluster(con, article_id: int, ticker: str, scorer: str,
                      cluster_id: int | None) -> dict | None:
    """Leitura ja feita de OUTRA materia do mesmo cluster e mesmo papel.

    Nao e so economia: e o principio do projeto aplicado ao custo. A 20a
    republicacao do mesmo fato nao e um fato novo -- "copia nao e voto"
    (docs/psicologia.md). Mandar as 20 copias ao modelo paga 20 leituras para
    receber a mesma leitura.

    E NAO ha desconto de magnitude aqui: a repeticao ja e descontada uma vez,
    em `novelty`, no peso da agregacao. Descontar de novo contaria duas vezes.
    """
    if cluster_id is None:
        return None
    r = con.execute(
        """SELECT sc.s, sc.magnitude, sc.event_type, sc.papel_no_fato,
                  sc.ja_precificado, sc.is_rumor, sc.quote, sc.raw, sc.article_id
           FROM scores sc JOIN articles a ON a.id = sc.article_id
           WHERE sc.scorer=? AND sc.ticker=? AND a.cluster_id=?
             AND sc.article_id != ? LIMIT 1""",
        (scorer, ticker, cluster_id, article_id)).fetchone()
    if not r:
        return None
    try:
        raw = json.loads(r["raw"] or "{}")
    except Exception:                                        # noqa: BLE001
        raw = {}
    if not isinstance(raw, dict):
        raw = {"original": raw}
    raw["reuso_cluster"] = {"cluster_id": cluster_id, "lido_em": r["article_id"]}
    return {"s": r["s"], "magnitude": r["magnitude"], "event_type": r["event_type"],
            "papel_no_fato": r["papel_no_fato"], "ja_precificado": r["ja_precificado"],
            "is_rumor": r["is_rumor"], "quote": r["quote"],
            "raw": json.dumps(raw, ensure_ascii=False)}


def run(scorer: str | None = None, limit: int = 5000, min_relevance: float = 0.35,
        max_chamadas: int | None = None, verbose: bool = True) -> int:
    """Pontua pares (artigo, ticker) ainda sem score para este scorer.

    `scorer=None` resolve pelo padrao do projeto (`resolver`). Par que falha
    fica PENDENTE, nao recebe nota de outro leitor: misturar leitores na mesma
    coluna `scorer` destruiria a comparacao que justifica a troca. Quem quer
    piso garantido pede `ensemble`, que cai para o lexico por materia e marca
    o fallback no `raw`.
    """
    scorer, _motivo = resolver(scorer, verbose=verbose)
    fn = SCORERS[scorer]
    usa_llm = scorer in PRECISAM_LLM
    teto = (max_chamadas if max_chamadas is not None else MAX_CHAMADAS_PADRAO) \
        if usa_llm else None
    _zera_contadores()

    con = connect()
    rows = con.execute("""
        SELECT m.article_id, m.ticker, m.relevance, a.title, a.body, a.lang,
               a.cluster_id
        FROM mentions m JOIN articles a ON a.id = m.article_id
        WHERE m.ticker != '__none__' AND m.relevance >= ?
          AND NOT EXISTS (SELECT 1 FROM scores s
                          WHERE s.article_id=m.article_id AND s.ticker=m.ticker AND s.scorer=?)
        ORDER BY a.published_ts DESC LIMIT ?""", (min_relevance, scorer, limit)).fetchall()

    n = pulados = falhas = 0
    seguidas = 0
    erro_ultimo = ""
    for r in rows:
        if not _idioma_coberto(r["lang"], scorer):
            pulados += 1
            continue
        out = None
        if usa_llm:
            out = _reuso_de_cluster(con, r["article_id"], r["ticker"], scorer,
                                    r["cluster_id"])
            if out is not None:
                CONTADORES["cluster"] += 1
        if out is None:
            if usa_llm and teto is not None and CONTADORES["chamadas"] >= teto:
                CONTADORES["teto"] += 1
                continue                 # fica pendente para a proxima rodada
            try:
                # TICKER SEMPRE. O lexico tambem o usa (`_posicao_no_fato`), e
                # por meses esta chamada o omitia: a correcao do caso
                # ANP/Petrobras existia no codigo e nunca rodava em producao.
                out = fn(r["title"], r["body"], r["ticker"])
            except Exception as exc:                         # noqa: BLE001
                falhas += 1
                seguidas += 1
                erro_ultimo = str(exc)[:200]
                if seguidas >= FALHAS_SEGUIDAS_ABORTA:
                    print(f"  [score] ABORTADO: {seguidas} falhas seguidas. "
                          f"Ultimo erro: {erro_ultimo}")
                    break
                continue
        seguidas = 0
        nov = novelty(con, r["article_id"])

        # CLASSIFICACAO EM DUAS DIMENSOES (obs/evento.py). Recalculada do
        # texto DESTE artigo, nunca copiada do vizinho de cluster: a copia
        # reaproveita a LEITURA (s, magnitude), que e caro, mas tipo e
        # orientacao saem de regex sobre o proprio titulo e custam nada --
        # e o titulo da republicacao nao e identico ao do original.
        #
        # QUEM DECIDE O QUE, e por que:
        #   tipo_evento -> REGRA. A ordem dela e o conserto documentado
        #     ("judicial vence operacional"), e "TRF", "liminar" ou "projeto
        #     de lei" sao inequivocos: nao precisam de modelo.
        #   orientacao  -> LLM quando ele leu; regra como piso. Tempo verbal
        #     mora em oracao subordinada ("recurso protocolado na segunda
        #     contestando decisao de quarta" tem dois tempos e nenhuma
        #     palavra-chave os separa), e isso exige leitura.
        # Divergencia entre os dois fica gravada no `raw`, contavel por
        # GROUP BY -- se for frequente, uma das duas esta errada.
        cls = evento.de_texto(r["title"], r["body"], out.get("event_type"))
        orient_llm = out.get("orientacao_llm")
        orientacao = orient_llm or cls["orientacao"]
        if orient_llm and orient_llm != cls["orientacao"]:
            try:
                _raw = json.loads(out.get("raw") or "{}")
                if isinstance(_raw, dict):
                    _raw["orientacao_regra"] = cls["orientacao"]
                    out["raw"] = json.dumps(_raw, ensure_ascii=False)
            except Exception:                                # noqa: BLE001
                pass
        # COMMIT POR LINHA, nao um no fim da rodada. Com o lexico dava na
        # mesma; com o LLM, cada linha ja foi PAGA -- abortar no meio e perder
        # a transacao jogaria fora leitura comprada. O cache cobre a releitura,
        # mas commit por linha e o que garante que a nota ja esta no banco.
        with con:
            # TODAS as colunas, de proposito. INSERT OR REPLACE APAGA a linha e
            # insere outra, entao coluna omitida volta para NULL -- e era assim
            # que `limpar --aplicar` zerava `tipo_evento` e `orientacao` de
            # todo o acervo sem ninguem ver. Acrescentar coluna a `scores`
            # obriga a acrescentar aqui.
            con.execute(
                "INSERT OR REPLACE INTO scores"
                "(article_id,ticker,scorer,s,magnitude,event_type,novelty,"
                " tipo_evento,orientacao,"
                " papel_no_fato,ja_precificado,is_rumor,quote,raw)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["article_id"], r["ticker"], scorer, out["s"], out["magnitude"],
                 out["event_type"], nov,
                 cls["tipo_evento"], ",".join(orientacao),
                 out.get("papel_no_fato"),
                 out.get("ja_precificado"), out.get("is_rumor"),
                 out.get("quote"), out.get("raw")))
        n += 1
    con.close()

    CONTADORES["falhas"] = falhas
    if verbose:
        if pulados:
            print(f"  [score] {pulados} pulados por idioma fora do lexico "
                  f"(use --scorer llm para esses)")
        if usa_llm:
            print(f"  [score] leitor={scorer} chamadas={CONTADORES['chamadas']} "
                  f"cache={CONTADORES['cache']} reuso_cluster={CONTADORES['cluster']} "
                  f"falhas={falhas}")
            if CONTADORES["teto"]:
                print(f"  [score] {CONTADORES['teto']} pares deixados para a "
                      f"proxima rodada (teto de {teto} chamadas; "
                      f"OBS_LLM_MAX_CHAMADAS muda isso)")
        if falhas:
            print(f"  [score] {falhas} par(es) SEM nota -- ficam pendentes. "
                  f"Ultimo erro: {erro_ultimo}")
    return n
