"""Ingestao de noticias: GDELT 2.0 DOC API + feeds RSS. Nenhuma chave de API.

Grava SEMPRE published_ts e ingested_ts separados -- a diferenca entre os dois
e o atraso da fonte, e ignorar isso e a forma mais comum de vazar futuro
(look-ahead) num backtest de noticias.
"""
from __future__ import annotations
import concurrent.futures as cf
import email.utils as eut
import datetime as dt
import re
import time
import xml.etree.ElementTree as ET

from . import config, drivers, routing
from .db import connect
from .util import http_get, now_ts, parse_gdelt_ts

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
# O proprio GDELT responde 429 com "limit requests to one every 5 seconds".
# Com menos que isso, metade dos tickers volta vazia e voce conclui que nao ha
# noticia -- quando na verdade levou throttle. 5.5s da folga.
GDELT_DELAY_S = 5.5


def _frase_valida(a: str) -> bool:
    """O GDELT recusa a consulta INTEIRA quando uma frase tem palavra curta.

    MEDIDO: o alias "vale s.a." da VALE3 derruba a consulta toda com
    `The specified phrase is too short.` -- os tokens "s" e "a" sao curtos
    demais. E a falha e silenciosa no lugar errado: a resposta vem em texto
    puro, nao em JSON, e o papel volta sem NENHUMA noticia. Era por isso que o
    canal GDELT ficava vazio.

    O corte e em token de UMA letra, nao em palavra curta. A primeira versao
    desta funcao exigia 3+ caracteres por token e jogou fora "banco do brasil"
    por causa do "do" -- a BBAS3 passou a procurar so por "BBAS3", que e pior
    do que o defeito original. Com o corte em 2, "s.a." sai e "do"/"b3" ficam.

    ESTE FILTRO NAO BASTA, e de proposito. MEDIDO em 2026-10-02: o GDELT recusa
    tambem a frase "Vale", de 4 caracteres, que passa por aqui. Nao da para
    fixar o limite exato sem ficar sondando a API (que responde throttle antes
    de responder a pergunta), entao quem resolve de verdade e a retentativa em
    _busca(): ela ve a recusa e reenvia sem a frase mais curta. Aqui so ficam os
    casos que NUNCA valem uma requisicao.
    """
    toks = [t for t in re.split(r"[^0-9A-Za-zÀ-ÿ]+", a) if t]
    if not toks:
        return False
    if any(len(t) < 2 for t in toks):
        return False
    return len("".join(toks)) >= 4


def _frases(aliases: list[str]) -> list[str]:
    vistos, out = set(), []
    for a in aliases:
        a = (a or "").strip()
        if not a or a.lower() in vistos or not _frase_valida(a):
            continue
        vistos.add(a.lower())
        out.append(a)
    return out[:8]


def _gdelt_query(aliases: list[str]) -> str:
    fr = _frases(aliases)
    return "(" + " OR ".join(f'"{a}"' for a in fr) + ")" if fr else ""


class Orcamento:
    """Teto de tempo para uma rodada, com disjuntor de throttle.

    POR QUE EXISTE -- MEDIDO em 2026-10-02:
    `refresh_news` morria com TimeoutExpired em 1800s e NENHUMA noticia entrava.
    A causa nao eram os feeds (os 24 somam 9,5s), era o GDELT: em throttle, uma
    unica consulta custa 5,5s de espera + 3 tentativas de 25s + backoff de 6 e
    12s, perto de 100s. Sao 10 consultas por papel mais 40 roteadas = 50
    chamadas, logo ate 5.000s -- quase 3x o teto.

    Duas defesas:
      - TETO de tempo: ao estourar, para e devolve o que ja coletou. Noticia
        parcial e melhor que morrer sem nada, que era o comportamento antigo.
      - DISJUNTOR: GDELT em throttle nao volta em segundos. Depois de
        MAX_FALHAS consultas seguidas sem resposta, desiste do GDELT nesta
        rodada em vez de queimar 100s por papel ate o fim.
    """
    MAX_FALHAS = 3

    def __init__(self, segundos: float):
        self.fim = time.monotonic() + segundos
        self.falhas = 0
        self.desistiu = False

    def restante(self) -> float:
        return self.fim - time.monotonic()

    def ok(self) -> bool:
        return not self.desistiu and self.restante() > 0

    def registra(self, sucesso: bool) -> None:
        if sucesso:
            self.falhas = 0
            return
        self.falhas += 1
        if self.falhas >= self.MAX_FALHAS:
            self.desistiu = True
            print(f"  [gdelt] {self.falhas} falhas seguidas -- desistindo do "
                  "GDELT nesta rodada (throttle nao passa em segundos)")

    def motivo(self) -> str:
        if self.desistiu:
            return "disjuntor de throttle"
        return "teto de tempo" if self.restante() <= 0 else ""


def _busca(aliases: list[str], extra: dict, maxrecords: int,
           rotulo: str = "") -> list[dict] | None:
    """Consulta o GDELT e devolve a lista de artigos (None = falhou).

    POR QUE TEM RETENTATIVA AQUI
    O GDELT recusa a consulta INTEIRA quando acha uma frase curta demais, e nao
    documenta o limite exato. Em vez de adivinhar o numero, a funcao detecta a
    recusa e reenvia sem a frase mais curta -- isso vale qualquer que seja a
    regra. Sem isso o papel volta com zero artigos e parece que nao houve
    noticia; era o caso da VALE3, cujo alias "vale s.a." derrubava tudo.
    """
    fr = _frases(aliases)
    while fr:
        q = "(" + " OR ".join(f'"{a}"' for a in fr) + ")"
        # tries=1 DE PROPOSITO. O padrao do http_get e 3 tentativas com backoff
        # de 6s e 12s -- desenhado para falha transitoria. Throttle do GDELT nao
        # e transitorio: MEDIDO, ele persistiu por horas. Entao cada consulta
        # throttled custava ~24s so de backoff inutil, e 4 delas antes do
        # disjuntor agir davam 100s jogados fora por rodada. Quem decide
        # reinsistir agora e o Orcamento, um nivel acima -- e ele decide parar.
        r = http_get(GDELT, params={
            "query": q, "mode": "artlist", "maxrecords": maxrecords,
            "format": "json", "sort": "datedesc", **extra}, tries=1)
        if r is None:
            print(f"  [gdelt] {rotulo}: sem resposta")
            return None
        try:
            return r.json().get("articles", [])
        except ValueError:
            msg = r.text[:90].strip()
            if "too short" not in msg.lower() or len(fr) == 1:
                print(f"  [gdelt] {rotulo}: resposta nao-JSON: {msg}")
                return None
            curta = min(fr, key=lambda s: len(s))
            fr = [a for a in fr if a != curta]
            print(f"  [gdelt] {rotulo}: frase {curta!r} recusada por curta; "
                  f"reenviando com {len(fr)} termos")
            time.sleep(GDELT_DELAY_S)
    return None


LOTE_TICKERS = 4          # papeis por consulta
ALIASES_POR_TICKER = 3    # frases mais fortes de cada um, para a consulta caber


def fetch_gdelt(timespan: str = "1d", maxrecords: int = 250,
                orc: "Orcamento | None" = None,
                lote: int = LOTE_TICKERS) -> list[dict]:
    """Noticia por nome de empresa, EM LOTES de papeis.

    POR QUE DA PARA JUNTAR: a consulta serve so para ACHAR materia; quem diz a
    qual papel ela pertence e `entity.link_all()`, lendo o texto. Entao uma
    consulta com os aliases de 4 empresas acha o mesmo que 4 consultas, e a
    atribuicao sai igual.

    POR QUE IMPORTA: o GDELT exige 1 requisicao a cada 5,5s, e essa espera e o
    custo dominante da rodada -- nao a rede. Com 10 papeis, 10 consultas sao
    55s de pausa obrigatoria; em lotes de 4, sao 3 consultas e ~17s. MEDIDO:
    4 papeis (12 frases, 207 chars) numa consulta devolveram 45 artigos, sem
    recusa do GDELT.

    `maxrecords` sobe para 250 (o teto do GDELT) justamente porque agora cada
    resposta cobre varias empresas.
    """
    itens = [(t, m.get("aliases", []) + [m.get("name", "")])
             for t, m in config.tickers().items()]
    itens = [(t, a) for t, a in itens if _frases(a)]
    out, seen = [], set()
    for i in range(0, len(itens), max(1, lote)):
        grupo = itens[i:i + max(1, lote)]
        rotulo = "+".join(t for t, _ in grupo)
        aliases = []
        for _t, al in grupo:
            aliases += _frases(al)[:ALIASES_POR_TICKER]
        if orc is not None and not orc.ok():
            print(f"  [gdelt] parando em {rotulo}: {orc.motivo()}")
            break
        time.sleep(GDELT_DELAY_S)
        arts = _busca(aliases, {"timespan": timespan}, maxrecords, rotulo)
        if orc is not None:
            orc.registra(arts is not None)
        if arts is None:
            continue
        for a in arts:
            url = a.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                pub = parse_gdelt_ts(a["seendate"])
            except (KeyError, ValueError):
                continue
            out.append({
                "url": url, "title": a.get("title", "").strip(),
                "body": None, "domain": a.get("domain", ""),
                "lang": a.get("language", ""), "published_ts": pub,
                "source": "gdelt",
            })
        print(f"  [gdelt] {rotulo}: {len(arts)} artigos")
    return out


def fetch_gdelt_janela(inicio: dt.datetime, fim: dt.datetime,
                       maxrecords: int = 250,
                       orc: "Orcamento | None" = None) -> list[dict]:
    """Igual a fetch_gdelt, mas numa janela FECHADA de tempo.

    `timespan` so alcanca os ultimos meses; startdatetime/enddatetime alcanca
    2017 em diante, e e o que permite reconstruir historico (ver obs/historico).
    O GDELT limita maxrecords a 250 por resposta -- por isso o chamador caminha
    em janelas curtas em vez de pedir um ano de uma vez: pedir demais nao da
    erro, da truncamento silencioso, e voce conclui que nao houve noticia.
    """
    fmt = "%Y%m%d%H%M%S"
    out, seen = [], set()
    for tkr, meta in config.tickers().items():
        aliases = meta.get("aliases", []) + [meta.get("name", "")]
        if not _frases(aliases):
            continue
        if orc is not None and not orc.ok():
            break
        time.sleep(GDELT_DELAY_S)
        arts = _busca(aliases, {"startdatetime": inicio.strftime(fmt),
                                "enddatetime": fim.strftime(fmt)},
                      maxrecords, tkr)
        if orc is not None:
            orc.registra(arts is not None)
        if arts is None:
            continue
        if len(arts) >= maxrecords:
            print(f"  [gdelt] {tkr}: janela TRUNCADA em {maxrecords} -- reduza o passo")
        for a in arts:
            url = a.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                pub = parse_gdelt_ts(a["seendate"])
            except (KeyError, ValueError):
                continue
            out.append({"url": url, "title": a.get("title", "").strip(),
                        "body": None, "domain": a.get("domain", ""),
                        "lang": a.get("language", ""), "published_ts": pub,
                        "source": "gdelt-hist"})
    return out


def _rss_date(s: str | None) -> int | None:
    """RFC 2822 -> epoch. Datetime INGENUO conta como UTC, nunca como local.

    MEDIDO em 2026-10-02, e era o defeito mais caro desta lista:
    o feed do Valor (pox.globo.com) carimba `-0000`, que em RFC 2822 significa
    "fuso desconhecido". O `parsedate_to_datetime` devolve datetime INGENUO
    nesse caso, e `.timestamp()` entao interpreta como hora LOCAL -- nesta
    maquina, -03. Resultado: `22:13 -0000` virava `01:13 UTC do dia seguinte`,
    TRES HORAS adiantado, em todo artigo do veiculo que mais gera mencao.
    Noticia com carimbo no futuro desalinha o estudo de evento por minuto e
    estraga o decaimento de recencia, sem nunca dar erro.
    """
    if not s:
        return None
    try:
        d = eut.parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp())
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = dt.datetime.strptime(s.strip(), fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return int(d.timestamp())
        except ValueError:
            continue
    return None


# Como o RSS escreve o idioma -> nome que o GDELT usa, para o banco ter UM
# vocabulario so. O que nao estiver aqui fica como veio, e a porta de idioma
# do scorer trata como nao-coberto (ver score.py:IDIOMAS_LEXICO).
_IDIOMAS = {"pt": "Portuguese", "en": "English", "de": "German", "fr": "French",
            "es": "Spanish", "it": "Italian", "nl": "Dutch"}


def _idioma_do_feed(root) -> str:
    """Le o <language> declarado pelo feed.

    ANTES ISTO ERA A CONSTANTE "Portuguese", escrita no codigo. Com so feeds
    brasileiros passava despercebido; ao ligar Bloomberg, Handelsblatt e Les
    Echos vira defeito grave, porque manchete alema entra carimbada de
    portugues e escapa de qualquer filtro de idioma. MEDIDO: a mesma noticia de
    desastre pontua -0.70 em portugues e +0.60 em frances, porque "record" (o
    POS do ingles) se escreve igual em frances -- o sinal nao so dilui, inverte.
    """
    for caminho in ("language", "channel/language",
                    "{http://www.w3.org/2005/Atom}lang"):
        el = root.find(caminho)
        if el is not None and (el.text or "").strip():
            codigo = el.text.strip().lower()
            return _IDIOMAS.get(codigo.split("-")[0], codigo)
    attr = root.get("{http://www.w3.org/XML/1998/namespace}lang")
    if attr:
        return _IDIOMAS.get(attr.split("-")[0].lower(), attr)
    return ""


# Feeds sao hosts INDEPENDENTES: ao contrario do GDELT, nao ha limite de taxa
# compartilhado entre eles, entao buscar em paralelo nao e trapaca com ninguem.
# MOTIVO DE EXISTIR: a lista passou de 5 para 24 feeds e a busca sequencial
# estourou o teto de 1800s do worker -- `refresh_news` morria com
# TimeoutExpired e NENHUMA noticia entrava. Um feed lento custava ate 25s x 3
# tentativas sozinho, e 24 deles em fila somam mais que a janela inteira.
RSS_PARALELO = 8
RSS_TIMEOUT = 12       # feed que nao responde em 12s nao vale a espera
RSS_TRIES = 2


def _busca_feed(url: str):
    r = http_get(url, timeout=RSS_TIMEOUT, tries=RSS_TRIES)
    return url, r


def fetch_rss() -> list[dict]:
    """Parser RSS/Atom em stdlib -- sem feedparser."""
    out = []
    urls = config.sources().get("rss", [])
    with cf.ThreadPoolExecutor(max_workers=RSS_PARALELO) as pool:
        respostas = dict(pool.map(_busca_feed, urls))
    for url in urls:
        r = respostas.get(url)
        if r is None:
            print(f"  [rss] {url}: falhou")
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            print(f"  [rss] {url}: xml invalido")
            continue
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        domain = url.split("/")[2]
        idioma = _idioma_do_feed(root)
        n = 0
        for it in items:
            def tag(*names):
                for nm in names:
                    el = it.find(nm)
                    if el is not None:
                        return (el.text or "").strip() or (el.get("href") or "").strip()
                return ""
            link = tag("link", "{http://www.w3.org/2005/Atom}link")
            title = tag("title", "{http://www.w3.org/2005/Atom}title")
            desc = tag("description", "{http://www.w3.org/2005/Atom}summary",
                       "{http://purl.org/rss/1.0/modules/content/}encoded")
            pub = _rss_date(tag("pubDate", "{http://www.w3.org/2005/Atom}updated",
                                "{http://purl.org/dc/elements/1.1/}date"))
            if not link or not title:
                continue
            out.append({
                "url": link, "title": title, "body": desc or None,
                "domain": domain, "lang": idioma,
                "published_ts": pub or now_ts(), "source": "rss",
            })
            n += 1
        print(f"  [rss] {domain}: {n} itens")
    return out


def _valida_carimbos(rows: list[dict]) -> list[dict]:
    """Aplica offset MEDIDO por dominio, depois troca o que sobrar de implausivel.

    A ordem importa: corrigir o fuso ANTES de validar evita que a guarda de
    "carimbo no futuro" apague a hora real de um feed so porque ele declara o
    fuso errado -- o que trocaria um erro de 3h por um erro de latencia.
    """
    from . import tempo
    from .db import connect
    agora = tempo.agora_ts()
    try:
        con = connect()
        offsets = tempo.offsets_conhecidos(con)
        con.close()
    except Exception:                                        # noqa: BLE001
        offsets = {}
    if offsets:
        corr = {}
        for r in rows:
            off = offsets.get(r.get("domain") or "")
            if off and r.get("published_ts"):
                r["published_ts"] += off
                corr[r["domain"]] = corr.get(r["domain"], 0) + 1
        for dom, n in corr.items():
            print(f"  [fuso] {n} artigo(s) de {dom} corrigidos em "
                  f"{offsets[dom]/3600:+.0f}h (offset medido, nao declarado)")
    ruins: dict[str, int] = {}
    for r in rows:
        motivo = tempo.suspeito(r.get("published_ts") or 0, agora)
        if motivo:
            ruins[f"{r.get('domain','?')}: {motivo.split(' (')[0]}"] = \
                ruins.get(f"{r.get('domain','?')}: {motivo.split(' (')[0]}", 0) + 1
            r["published_ts"] = agora
    for k, n in sorted(ruins.items(), key=lambda x: -x[1]):
        print(f"  [carimbo] {n} artigo(s) com data {k} -- usando o instante "
              f"da coleta. Verifique o fuso declarado pelo feed.")
    return rows


def store(rows: list[dict]) -> int:
    """INSERT OR IGNORE por url. Devolve quantos sao novos.

    VALIDA O CARIMBO antes de gravar. Carimbo no futuro e a assinatura exata
    do erro de fuso -- foi assim que 329 artigos do Valor entraram 3h
    adiantados e so foram notados dias depois, ao olhar o grafico. A guarda
    nao descarta: grava com o instante da COLETA e avisa, porque perder a
    materia seria pior que ter a hora aproximada.
    """
    rows = _valida_carimbos(rows)
    con = connect()
    ts = now_ts()
    new = 0
    with con:
        for r in rows:
            cur = con.execute(
                "INSERT OR IGNORE INTO articles"
                "(url,title,body,domain,lang,published_ts,ingested_ts,source)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (r["url"], r["title"], r["body"], r["domain"], r["lang"],
                 r["published_ts"], ts, r["source"]))
            new += cur.rowcount
    con.close()
    return new


def fetch_roteado(timespan: str = "2d", maxrecords: int = 50,
                  exposicoes: dict | None = None,
                  orc: "Orcamento | None" = None) -> list[dict]:
    """Consultas DERIVADAS DA CADEIA DE AFETACAO, nao do nome da empresa.

    E o roteamento: se a PETR4 e 49% Brent, ela escuta petroleo, OPEP e
    estoques -- em portugues E em ingles, e os termos em ingles alcancam a
    imprensa estrangeira pelo proprio GDELT, que e quem cobre os drivers
    antes da imprensa brasileira.

    Cada artigo volta carimbado com o driver, o `share` e o sinal do beta,
    para que o agregador possa ponderar: noticia de petroleo nao vale o mesmo
    para PETR4 (share 0,49) e para MGLU3 (share 0,09, sinal invertido).

    UMA CONSULTA POR DRIVER, NAO POR (PAPEL, DRIVER). A consulta depende so do
    driver -- `routing.gdelt_query` monta os termos a partir do topico, e o
    papel nao entra nela. MEDIDO em 2026-10-02: 38 consultas por rodada, das
    quais apenas 10 DISTINTAS; BRENT era pedido 8 vezes identicamente, DXY 8,
    USDBRL 7. As 28 repetidas eram requisicoes HTTP iguais a 5,5s cada --
    154 segundos jogados fora, por rodada, para receber a mesma resposta.
    Agora pergunta uma vez e distribui para todos os papeis que escutam, cada
    um com seu proprio peso e sinal de beta.
    """
    if exposicoes is None:
        exposicoes = _exposicoes()
    # driver -> [(ticker, peso, sinal)], e a consulta de cada driver
    ouvintes: dict[str, list[tuple]] = {}
    consulta_de: dict[str, str] = {}
    for tkr in config.tickers():
        for c in routing.consultas(tkr, exposicoes.get(tkr)):
            if c["tipo"] != "driver":
                continue                      # o nome da empresa ja vem por fetch_gdelt
            q = routing.gdelt_query(c)
            if not q:
                continue
            drv = c["driver"]
            ouvintes.setdefault(drv, []).append((tkr, c["peso"], c["sinal_beta"]))
            consulta_de[drv] = q

    out, vistos = [], set()
    for drv, q in consulta_de.items():
        if orc is not None and not orc.ok():
            print(f"  [rota] parando em {drv}: {orc.motivo()}")
            return out
        time.sleep(GDELT_DELAY_S)
        r = http_get(GDELT, params={
            "query": q, "mode": "artlist", "maxrecords": maxrecords,
            "format": "json", "sort": "datedesc", "timespan": timespan}, tries=1)
        # O disjuntor conta RESPOSTA UTIL, nao resposta HTTP. MEDIDO: a
        # mensagem de throttle do GDELT vem como 200 em texto puro, entao
        # `r is not None` era True e ZERAVA o contador de falhas. Na pratica a
        # sequencia throttle/falhou/throttle alternava e o disjuntor nunca
        # disparava -- a rodada ia ate o fim pagando timeout em cada driver.
        arts = None
        if r is not None:
            try:
                arts = r.json().get("articles", [])
            except ValueError:
                print(f"  [rota] {drv}: throttle")
        else:
            print(f"  [rota] {drv}: falhou")
        if orc is not None:
            orc.registra(arts is not None)
        if arts is None:
            continue
        n = 0
        for a in arts:
            url = a.get("url")
            if not url:
                continue
            try:
                pub = parse_gdelt_ts(a["seendate"])
            except (KeyError, ValueError):
                continue
            for tkr, peso, sinal in ouvintes[drv]:
                chave = (url, tkr)
                if chave in vistos:
                    continue
                vistos.add(chave)
                out.append({
                    "url": url, "title": a.get("title", "").strip(), "body": None,
                    "domain": a.get("domain", ""), "lang": a.get("language", ""),
                    "published_ts": pub, "source": "gdelt-rota",
                    "_ticker": tkr, "_driver": drv,
                    "_peso": peso, "_sinal": sinal})
                n += 1
            print(f"  [rota] {tkr}/{c['driver']}: {n} artigos")
    return out


def fetch_setorial(timespan: str = "2d", maxrecords: int = 50,
                   orc: "Orcamento | None" = None) -> list[dict]:
    """Noticia que atinge o SETOR, mesmo sem citar a empresa.

    O ligador de entidades exige que o texto nomeie a companhia -- entao
    "nova regra de capital para bancos" nao virava sinal para ITUB4, BBDC4 nem
    BBAS3, embora atinja os tres. Esta camada preenche isso: pergunta uma vez
    por setor e distribui para todos os papeis que pertencem a ele.

    Carimba a mencao com `driver = "setor:<nome>"`, reaproveitando a mesma
    maquinaria de peso que o roteamento por driver ja usa em aggregate.py.
    """
    out, vistos = [], set()
    for c in routing.consultas_setor():
        q = routing.gdelt_query(c)
        if not q:
            continue
        if orc is not None and not orc.ok():
            print(f"  [setor] parando em {c['setor']}: {orc.motivo()}")
            return out
        time.sleep(GDELT_DELAY_S)
        r = http_get(GDELT, params={
            "query": q, "mode": "artlist", "maxrecords": maxrecords,
            "format": "json", "sort": "datedesc", "timespan": timespan}, tries=1)
        arts = None
        if r is not None:
            try:
                arts = r.json().get("articles", [])
            except ValueError:
                print(f"  [setor] {c['setor']}: throttle")
        else:
            print(f"  [setor] {c['setor']}: falhou")
        if orc is not None:
            orc.registra(arts is not None)
        if arts is None:
            continue
        n = 0
        for a in arts:
            url = a.get("url")
            if not url:
                continue
            try:
                pub = parse_gdelt_ts(a["seendate"])
            except (KeyError, ValueError):
                continue
            for tkr in c["tickers"]:
                chave = (url, tkr)
                if chave in vistos:
                    continue
                vistos.add(chave)
                out.append({
                    "url": url, "title": a.get("title", "").strip(), "body": None,
                    "domain": a.get("domain", ""), "lang": a.get("language", ""),
                    "published_ts": pub, "source": "gdelt-setor",
                    "_ticker": tkr, "_driver": c["driver"],
                    "_peso": c["peso"], "_sinal": c["sinal_beta"]})
                n += 1
        print(f"  [setor] {c['setor']}: {len(arts)} artigos -> "
              f"{len(c['tickers'])} papeis")
    return out


def fetch_temas(timespan: str = "2d", maxrecords: int = 50,
                orc: "Orcamento | None" = None) -> list[dict]:
    """Noticia pelo MECANISMO: cadeia de producao, credito, politica, tributo.

    Quarta camada, depois de empresa, driver e setor. Ver obs/temas.py para o
    porque e para a matriz de sinais. Diferenca em relacao as outras: o sinal
    e EXPLICITO e pode ser oposto entre papeis -- "Copom sobe a Selic" entra
    como +1 nos bancos e -1 no varejo, na MESMA rodada, a partir da MESMA
    materia.

    So consulta tema com `ativo=True` em obs/temas.TEMAS. Todos nascem
    desligados: sinal escrito a mao e hipotese, nao medicao.
    """
    from . import temas as _tm
    out, vistos = [], set()
    for c in _tm.consultas_tema():
        q = routing.gdelt_query(c)
        if not q:
            continue
        if orc is not None and not orc.ok():
            print(f"  [tema] parando em {c['tema']}: {orc.motivo()}")
            return out
        time.sleep(GDELT_DELAY_S)
        r = http_get(GDELT, params={
            "query": q, "mode": "artlist", "maxrecords": maxrecords,
            "format": "json", "sort": "datedesc", "timespan": timespan}, tries=1)
        arts = None
        if r is not None:
            try:
                arts = r.json().get("articles", [])
            except ValueError:
                print(f"  [tema] {c['tema']}: throttle")
        else:
            print(f"  [tema] {c['tema']}: falhou")
        if orc is not None:
            orc.registra(arts is not None)
        if arts is None:
            continue
        for a in arts:
            url = a.get("url")
            if not url:
                continue
            try:
                pub = parse_gdelt_ts(a["seendate"])
            except (KeyError, ValueError):
                continue
            for tkr, sinal in c["alvos"]:
                chave = (url, tkr)
                if chave in vistos:
                    continue
                vistos.add(chave)
                out.append({
                    "url": url, "title": a.get("title", "").strip(), "body": None,
                    "domain": a.get("domain", ""), "lang": a.get("language", ""),
                    "published_ts": pub, "source": "gdelt-tema",
                    "_ticker": tkr, "_driver": c["driver"],
                    "_peso": _tm.PESO_TEMA, "_sinal": sinal})
        print(f"  [tema] {c['tema']}: {len(arts)} artigos -> "
              f"{len(c['alvos'])} papeis")
    return out


def _exposicoes() -> dict:
    """Cadeia de afetacao atual, para decidir o que cada papel escuta."""
    from .db import connect
    import statistics as st

    con = connect()
    rows = con.execute("SELECT ticker,date,close FROM prices ORDER BY ticker,date").fetchall()
    con.close()
    by = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append((r["date"], r["close"]))
    ret = {t: {v[i][0]: v[i][1] / v[i - 1][1] - 1 for i in range(1, len(v)) if v[i - 1][1]}
           for t, v in by.items()}
    if not ret:
        return {}
    con = connect()
    dret = drivers.driver_returns(con)
    con.close()
    if not dret:
        return {}
    comuns = sorted(d for d in {d for r in ret.values() for d in r}
                    if all(d in dret[k] for k in dret))
    if not comuns:
        return {}
    return drivers.fit_exposures(ret, comuns[-1], persist=False)


def store_rotas(rows: list[dict]) -> int:
    """Grava artigos roteados JA com a mencao carimbada pelo driver."""
    from .db import connect
    con = connect()
    ts = now_ts()
    n = 0
    with con:
        for r in rows:
            cur = con.execute(
                "INSERT OR IGNORE INTO articles"
                "(url,title,body,domain,lang,published_ts,ingested_ts,source)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (r["url"], r["title"], r["body"], r["domain"], r["lang"],
                 r["published_ts"], ts, r["source"]))
            n += cur.rowcount
            aid = con.execute("SELECT id FROM articles WHERE url=?",
                              (r["url"],)).fetchone()
            if aid is None:
                continue
            # relevancia do roteamento: o proprio share, nao o filtro de texto
            con.execute(
                "INSERT OR IGNORE INTO mentions"
                "(article_id,ticker,relevance,matched_alias,driver,peso_driver,sinal_driver)"
                " VALUES (?,?,?,?,?,?,?)",
                (aid["id"], r["_ticker"], min(1.0, 0.4 + r["_peso"]),
                 f"driver:{r['_driver']}", r["_driver"], r["_peso"], r["_sinal"]))
    con.close()
    return n


# Teto padrao de uma rodada. Folgado em relacao ao caminho feliz (~5 min) e
# MUITO abaixo do limite de 1800s do worker, para que a rodada termine sozinha
# em vez de ser morta por TimeoutExpired -- morrer por timeout perde tudo que
# ja tinha sido coletado, porque o store so roda no fim.
TETO_RODADA_S = 900.0


def run(timespan: str = "1d", rotear: bool = True, setorial: bool = True,
        teto_s: float = TETO_RODADA_S, so_gdelt: bool = False) -> int:
    orc = Orcamento(teto_s)
    # RSS PRIMEIRO, de proposito: e rapido (9,5s medidos nos 24 feeds, e ~2s
    # em paralelo) e nao depende do GDELT. Se o GDELT estiver em throttle, a
    # rodada ainda entrega as noticias dos feeds em vez de voltar vazia.
    rows = []
    if not so_gdelt:
        print("Ingestao RSS...")
        rows = fetch_rss()
    print("Ingestao GDELT...")
    rows += fetch_gdelt(timespan=timespan, orc=orc)
    n = store(rows)
    print(f"-> {len(rows)} coletados, {n} novos no banco")
    if rotear:
        print("Ingestao ROTEADA (assuntos da cadeia de afetacao)...")
        rot = fetch_roteado(timespan=timespan, orc=orc)
        nr = store_rotas(rot)
        print(f"-> {len(rot)} roteados, {nr} novos")
        n += nr
    if setorial:
        print("Ingestao SETORIAL (noticia que atinge o setor, sem citar a empresa)...")
        st = fetch_setorial(timespan=timespan, orc=orc)
        ns = store_rotas(st)          # mesma gravacao: mencao ja carimbada
        print(f"-> {len(st)} setoriais, {ns} novos")
        n += ns
    tm = fetch_temas(timespan=timespan, orc=orc)
    if tm:
        nt = store_rotas(tm)
        print(f"-> {len(tm)} por tema, {nt} novos")
        n += nt
    if not orc.ok():
        print(f"-> rodada encerrada por {orc.motivo()}; o que entrou esta salvo")
    return n


# ---------------------------------------------------- backfill por RSS ---
# MEDIDO em 2026-10-02: feeds WordPress aceitam ?paged=N e varios paginam
# FUNDO. O Brazil Journal foi de 01/out na pagina 1 a 05/mar na pagina 100 --
# sete meses de noticia financeira brasileira, sem GDELT e sem chave.
#
# POR QUE ISSO IMPORTA: o backfill do GDELT e a unica via de historico que o
# projeto tinha, e ele fica bloqueado por throttle durante horas. Esta via e
# independente: hosts diferentes, sem limite compartilhado, e pode rodar em
# paralelo. A contrapartida e cobertura -- so alcanca os veiculos que paginam.
RSS_BACKFILL_PARALELO = 4


def _paginas_do_feed(url: str, max_paginas: int, parar_sem_novos: int = 3):
    """Caminha ?paged=N ate o feed parar de entregar coisa nova.

    Para quando `parar_sem_novos` paginas seguidas nao trazem URL inedita --
    feed que ignora o parametro devolve sempre a pagina 1, e sem essa guarda
    o laco baixaria a mesma coisa N vezes achando que esta avancando.
    """
    sep = "&" if "?" in url else "?"
    vistos, out, secas = set(), [], 0
    for pg in range(1, max_paginas + 1):
        r = http_get(f"{url}{sep}paged={pg}", timeout=RSS_TIMEOUT, tries=1)
        if r is None:
            break
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            break
        itens = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry")
        if not itens:
            break
        novos = 0
        for it in itens:
            # `or` NAO serve aqui: Element sem filhos e FALSY no ElementTree,
            # entao `it.find("link") or it.find(atom)` descartava o <link>
            # valido e caia no atom (None). Com isso `novos` ficava sempre 0,
            # a guarda de pagina seca disparava e o backfill parava na pagina 3
            # de todos os feeds -- inclusive dos que paginam ate 7 meses.
            el = it.find("link")
            if el is None:
                el = it.find("{http://www.w3.org/2005/Atom}link")
            u = ""
            if el is not None:
                u = (el.text or "").strip() or (el.get("href") or "").strip()
            if u and u not in vistos:
                vistos.add(u)
                novos += 1
        out.append((pg, root, itens))
        secas = secas + 1 if novos == 0 else 0
        if secas >= parar_sem_novos:
            break
    return out


def backfill_rss(max_paginas: int = 120, verbose: bool = True) -> int:
    """Baixa historico pelos feeds que paginam. Nao depende do GDELT."""
    urls = config.sources().get("rss", [])
    total = 0
    with cf.ThreadPoolExecutor(max_workers=RSS_BACKFILL_PARALELO) as pool:
        resultados = list(pool.map(
            lambda u: (u, _paginas_do_feed(u, max_paginas)), urls))
    for url, paginas in resultados:
        dominio = url.split("/")[2]
        linhas = []
        for _pg, root, itens in paginas:
            idioma = _idioma_do_feed(root)
            for it in itens:
                def tag(*nomes):
                    for nm in nomes:
                        el = it.find(nm)
                        if el is not None:
                            return (el.text or "").strip() or (el.get("href") or "").strip()
                    return ""
                link = tag("link", "{http://www.w3.org/2005/Atom}link")
                titulo = tag("title", "{http://www.w3.org/2005/Atom}title")
                if not link or not titulo:
                    continue
                pub = _rss_date(tag("pubDate", "{http://www.w3.org/2005/Atom}updated",
                                    "{http://purl.org/dc/elements/1.1/}date"))
                linhas.append({
                    "url": link, "title": titulo,
                    "body": tag("description", "{http://www.w3.org/2005/Atom}summary") or None,
                    "domain": dominio, "lang": idioma,
                    "published_ts": pub or now_ts(), "source": "rss-hist"})
        novos = store(linhas)
        total += novos
        if verbose and linhas:
            datas = [x["published_ts"] for x in linhas]
            import datetime as _d
            print(f"  [hist] {dominio:<28} {len(paginas):>3} pags, "
                  f"{len(linhas):>5} itens, {novos:>4} novos, "
                  f"desde {_d.date.fromtimestamp(min(datas))}")
    return total
