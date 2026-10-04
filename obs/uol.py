"""Fonte de precos UOL: catalogo de papeis, id interno e cotacoes.

O QUE ESTA FONTE ACRESCENTA, e o que ela NAO acrescenta
    Acrescenta DESCOBERTA, BID/ASK e SEGUNDA OPINIAO.
    1. DESCOBERTA e o que mais importa. O Yahoo nao tem endpoint de listagem:
       para pedir um papel e preciso JA saber o ticker, e por isso a watchlist
       travou em 10. A UOL tem catalogo paginado, ~1.800 tickers com id
       interno, que e o insumo para chegar aos 150-300 papeis de
       docs/universo.md.
    2. BID/ASK -- spread cotado. Nem Yahoo nem brapi dao, e
       docs/canal-noticias.md pede "liquidez e spread estimado" como feature
       de contexto desde o inicio.
    3. SEGUNDA OPINIAO na mesma (ticker, date), que e o que permite conferir
       ajuste por proventos sem depender de desdobramento conhecido
       (prices.divergencia).

    NAO acrescenta OHLCV: o Yahoo ja traz open/high/low/volume no mesmo
    endpoint do fechamento. Versao anterior deste modulo afirmava que nao --
    estava ERRADO, e o erro inflava o valor desta fonte.

    NAO acrescenta historico: o teto da UOL e 5 anos de diario, e o banco ja
    tem 10 anos pela fonte atual (docs/precos-fontes.md). Quem vier aqui
    atras de backfill longo vai piorar a serie.

    POR ISSO ELA ENTRA COMO COMPLEMENTO, NAO COMO SUBSTITUTA. `coletar()` grava
    com `complementar=True`: barra que falta entra inteira, barra que existe
    mantem fechamento e origem e so recebe as colunas vazias. Sem isso, a chave
    (ticker, date) + `INSERT OR REPLACE` trocaria 10 anos de serie ajustada por
    5 anos de serie de ajuste desconhecido, em silencio.

TRES ARMADILHAS DE MAPEAMENTO. Errar qualquer uma grava serie errada EM
SILENCIO -- por isso cada uma tem teste que trava o comportamento em
scripts/test_uol.py, e a ingestao quebra alto se a API mudar.

    1. INTERDAY: `close` NAO e o fechamento da barra. E o fechamento da SESSAO
       ANTERIOR. O fechamento da barra esta em `price`.
       Conferido: a barra 20261002 do ITUB4 traz close=44.15, que e exatamente
       o `price` da barra 20261001. Mapear close->close desloca a serie
       INTEIRA em um dia, e nada no dado denuncia isso.
       Aqui: price -> close, e o `close` da API vira `fechamento_anterior`,
       util so para derivar variacao.

    2. INTRADAY: so `price` e `date` sao por barra. `high`, `low` e `open` sao
       da SESSAO e vem constantes nas ~399 barras (45.27 / 43.10 / 45.25 no
       caso do ITUB4). `volume` e ACUMULADO no dia.
       Logo NAO da para montar OHLC verdadeiro de 1 minuto. Ingerimos como
       serie de PRECO, e o volume da barra e a diferenca entre acumulados
       consecutivos. Candle de 5/15 min, se precisar, e agregado a partir
       daqui -- nunca lido como se a API desse.
       `bid`/`ask`: HIPOTESE de que sao por barra. O esquema diz que vem
       sempre, a sondagem nao disse se variam. Gravamos como vieram e
       `constantes()` responde a pergunta na primeira coleta real: se bid/ask
       sairem constantes nas ~399 barras, sao da SESSAO como high/low/open e
       nao servem como spread intradiario.

    3. AJUSTE POR PROVENTOS: desconhecido. A serie atual do projeto PARECE
       ajustada (nenhum salto > 35% em 10 anos, incluindo papel com
       desdobramento). Se a UOL nao ajustar, as duas series nao sao
       misturaveis: daria salto onde nao houve evento. `conferir_ajuste()`
       roda o teste quando houver rede, e ate la a origem por barra permite
       separar as duas.

ETIQUETA
    User-Agent identificavel, requisicoes SERIALIZADAS com pausa, e cache do
    id no banco -- o id nao muda a cada coleta e reextrai-lo por cotacao seria
    pagar scraping de pagina para cada barra. ~1.800 papeis em paralelo
    agressivo leva bloqueio.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse

from .db import connect
from .util import http_get, now_ts

NOME = "uol"

BASE_LISTA = "https://economia.uol.com.br/cotacoes/bolsas/acoes/bvsp-bovespa/"
BASE_API = "https://api.cotacoes.uol.com/asset/"
CAMPOS = ("price,high,low,open,volume,close,bid,ask,change,pctChange,date")

# A listagem exige User-Agent de browser; com o UA padrao a pagina nao volta.
UA_BROWSER = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
              "observatorio-academico/0.1 (pesquisa)")
CABECALHO = {"User-Agent": UA_BROWSER}

PAUSA_S = 1.2            # entre requisicoes, serializadas
VAZIAS_PARA_PARAR = 3    # ver `catalogo`
DIAS_RESONDAR = 30       # nao resondar papel sem dado antes disso
MIN_BARRAS_ATIVO = 60    # criterio de ATIVO da especificacao
MAX_ATRASO_PREGOES = 10


# ------------------------------------------------------------ categorias ----
# Classificacao ANTES de qualquer requisicao: nao gasta rede com o que nem
# queremos. A categoria e GUARDADA, nunca descartada -- BDR fica de fora por
# padrao mas da para reincluir por opcao.
# ACAO: sempre QUATRO LETRAS + numero. PETR4, ITUB4, VALE3.
RE_ACAO = re.compile(r"^[A-Z]{4}(3|4|5|6|11)$")
# BDR: o prefixo NAO e so letra. O nao patrocinado usa letra + alfanumericos --
# a1fl34, a1gi34, a1ka34, a1lb34 enchem a pagina 2 da listagem. Com
# `[A-Z]{4}` eles escapavam para `outro` e entrariam na coleta como se
# fossem desconhecidos. Pego por scripts/test_uol.py.
RE_BDR = re.compile(r"^[A-Z][A-Z0-9]{3}(34|35|32|33|39)$")
RE_FRACAO = re.compile(r"^[A-Z][A-Z0-9]{3}\d{1,2}F$")

ACAO, BDR, ETF_FII, OUTRO = "acao", "bdr", "etf_fii", "outro"


def classifica(ticker: str) -> str:
    """acao | bdr | etf_fii | outro, pelo padrao do codigo.

    Ordem IMPORTA: BDR nao patrocinado e 4 letras + 34/35, e `[A-Z]{4}11`
    tambem casaria com ETF. Testar BDR antes evita que a1fl34 vire acao.
    A pagina 2 da listagem e inteira de BDR (a1fl34, a1gi34, a1ka34...).
    """
    t = (ticker or "").strip().upper()
    if not t:
        return OUTRO
    if RE_BDR.match(t):
        return BDR
    if RE_FRACAO.match(t):
        return OUTRO                      # mercado fracionario
    if t.endswith("11"):
        # 11 e ambiguo: UNT de acao, ETF e FII usam o mesmo sufixo. Sem o
        # cadastro da B3 nao da para separar com certeza, entao vai para
        # categoria propria em vez de poluir `acao`.
        return ETF_FII
    if RE_ACAO.match(t):
        return ACAO
    return OUTRO


# -------------------------------------------------------------- catalogo ----
RE_LINK = re.compile(
    r"/cotacoes/bolsas/acoes/bvsp-bovespa/([a-z0-9]{4,8})-sa/", re.I)


def _pagina(p: int) -> str:
    return BASE_LISTA if p <= 1 else f"{BASE_LISTA}?p={p}"


def tickers_da_pagina(html: str) -> list[str]:
    """Tickers distintos citados numa pagina da listagem, em ordem."""
    vistos, out = set(), []
    for m in RE_LINK.finditer(html or ""):
        t = m.group(1).upper()
        if t not in vistos:
            vistos.add(t)
            out.append(t)
    return out


def catalogo(paginas_max: int = 60, verbose: bool = True) -> list[dict]:
    """Varre a listagem paginada e devolve [{ticker, categoria, pagina}].

    PAGINA VAZIA NAO E FIM DA LISTA. Medido na sondagem: ?p=32 voltou com 0
    tickers enquanto 34 a 39 vieram cheias. Parar na primeira vazia perderia
    ~250 papeis. So para depois de VAZIAS_PARA_PARAR vazias seguidas.
    """
    out, vistos = [], set()
    vazias = 0
    for p in range(1, paginas_max + 1):
        r = http_get(_pagina(p), headers=CABECALHO, timeout=30)
        html = r.text if r is not None else ""
        achados = tickers_da_pagina(html)
        # VAZIA = NENHUM ticker na pagina, nao "nenhum ticker novo".
        # A distincao importa: pagina que so repete o que ja vimos ainda e
        # pagina valida, e conta-la como vazia encurtaria a varredura. O
        # criterio de parada e o da sondagem -- ?p=32 veio com 0 tickers
        # enquanto 34 a 39 vieram cheias.
        if not achados:
            vazias += 1
            if verbose:
                print(f"  [uol] pagina {p}: VAZIA "
                      f"({vazias}/{VAZIAS_PARA_PARAR} seguidas)")
            if vazias >= VAZIAS_PARA_PARAR:
                break
            time.sleep(PAUSA_S)
            continue
        vazias = 0
        novos = [t for t in achados if t not in vistos]
        for t in novos:
            vistos.add(t)
            out.append({"ticker": t, "categoria": classifica(t), "pagina": p})
        if verbose:
            print(f"  [uol] pagina {p}: {len(achados)} tickers, "
                  f"{len(novos)} novos (total {len(out)})")
        time.sleep(PAUSA_S)
    return out


# ------------------------------------------------------------- data-id ------
# O id mora no atributo data-id da div do grafico, junto com data-title:
#   <div class="financial-market-full stockAcao stockPage" ... data-title="..."
#        data-id="884" ...>
# A regex NAO exige a ordem dos atributos: HTML gerado troca a ordem sem aviso.
RE_DIV = re.compile(r"<div[^>]*class=\"[^\"]*financial-market-full[^\"]*\"[^>]*>",
                    re.I)
RE_ATTR_ID = re.compile(r"data-id=\"(\d+)\"", re.I)
RE_ATTR_TITULO = re.compile(r"data-title=\"([^\"]*)\"", re.I)


def extrai_id(html: str) -> tuple[str | None, str | None]:
    """(data_id, data_title) da pagina do papel."""
    for m in RE_DIV.finditer(html or ""):
        div = m.group(0)
        mid = RE_ATTR_ID.search(div)
        if mid:
            tit = RE_ATTR_TITULO.search(div)
            return mid.group(1), (tit.group(1) if tit else None)
    return None, None


def busca_id(ticker: str) -> tuple[str | None, str | None]:
    """Vai a pagina do papel e extrai o id. UMA requisicao, cacheada no banco."""
    url = f"{BASE_LISTA}{ticker.lower()}-sa/"
    r = http_get(url, headers=CABECALHO, timeout=30)
    if r is None:
        return None, None
    return extrai_id(r.text)


# ------------------------------------------------------------- cotacoes -----
PERIODOS = {
    # caminho na API -> o que devolve, medido
    "years": "interday/list/years/",      # ~1248 barras diarias = 5 anos
    "months": "interday/list/months/",    # ~65 barras diarias = ~3 meses
    "intraday": "intraday/list/",         # ~399 barras de 1 min da ULTIMA sessao
}
# interday/list/ sem periodo, /days/, /weeks/ e intraday/list/days/ devolvem
# HTTP 500. Nao insista -- ja foi sondado.


def _url(periodo: str, data_id: str) -> str:
    cam = PERIODOS[periodo]
    q = urllib.parse.urlencode({"format": "JSON", "fields": CAMPOS,
                                "item": str(data_id)})
    return f"{BASE_API}{cam}?{q}&"


def _data(s) -> str:
    """'YYYYMMDDHHMMSS' -> 'YYYY-MM-DD'."""
    s = str(s)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _ts(s) -> int:
    """'YYYYMMDDHHMMSS' -> epoch UTC. A UOL carimba em horario de Brasilia."""
    s = str(s)
    d = dt.datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]),
                    int(s[8:10] or 0), int(s[10:12] or 0), int(s[12:14] or 0),
                    tzinfo=dt.timezone(dt.timedelta(hours=-3)))
    return int(d.timestamp())


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def mapeia_interday(docs: list[dict]) -> list[dict]:
    """docs crus -> barras diarias, com o mapeamento CERTO.

    ARMADILHA 1: `price` e o fechamento DA BARRA; `close` e o fechamento da
    SESSAO ANTERIOR. Mapear close->close desloca a serie inteira em um dia.
    """
    out = []
    for d in docs or []:
        if not d.get("date") or d.get("price") is None:
            continue
        out.append({
            "date": _data(d["date"]),
            "close": _num(d["price"]),            # <- price, NAO close
            "open": _num(d.get("open")),
            "high": _num(d.get("high")),
            "low": _num(d.get("low")),
            "volume": _num(d.get("volume")),
            "bid": _num(d.get("bid")),
            "ask": _num(d.get("ask")),
            "fechamento_anterior": _num(d.get("close")),   # so para variacao
        })
    out.sort(key=lambda b: b["date"])             # docs vem DECRESCENTE
    return out


def mapeia_intraday(docs: list[dict]) -> list[dict]:
    """docs crus -> serie de preco de 1 min, com volume DIFERENCIADO.

    ARMADILHA 2: so `price` e `date` sao por barra. `high`/`low`/`open` sao da
    SESSAO e vem constantes; `volume` e ACUMULADO no dia. Devolvemos preco e
    volume da barra, e NAO devolvemos OHLC -- porque a API nao da.

    bid/ask passam como vieram, SEM afirmar que sao por barra: o esquema diz
    que vem sempre, a sondagem nao disse se variam. `constantes()` decide isso
    na primeira coleta real. Se forem constantes, sao da sessao -- e ai o
    campo no banco e um valor de fim de sessao repetido, nao spread por
    minuto.
    """
    brutas = []
    for d in docs or []:
        if not d.get("date") or d.get("price") is None:
            continue
        brutas.append({"ts": _ts(d["date"]), "close": _num(d["price"]),
                       "bid": _num(d.get("bid")), "ask": _num(d.get("ask")),
                       "acumulado": _num(d.get("volume"))})
    brutas.sort(key=lambda b: b["ts"])
    out = []
    anterior = None
    for b in brutas:
        vol = None
        if b["acumulado"] is not None:
            vol = b["acumulado"] if anterior is None else b["acumulado"] - anterior
            # acumulado so cresce dentro do dia; queda = virada de sessao
            if vol < 0:
                vol = b["acumulado"]
            anterior = b["acumulado"]
        out.append({"ts": b["ts"], "close": b["close"], "volume": vol,
                    "bid": b["bid"], "ask": b["ask"]})
    return out


def constantes(barras: list[dict], campos=("bid", "ask", "volume")) -> dict:
    """Quais campos NAO variam na serie -- o teste da armadilha 2, generico.

    high/low/open ja sabemos que sao da sessao porque a sondagem mediu. Para
    bid/ask nao sabemos, e a diferenca importa: valor por barra e spread
    intradiario (feature de liquidez), valor da sessao repetido 399 vezes e
    uma coluna que parece dado e nao e.

    Devolve {campo: {"constante": bool, "distintos": n, "valor": x|None}}.
    Serie com menos de 2 barras nao responde nada, e e dito como tal
    (constante=None), em vez de ser contada como constante.
    """
    out = {}
    for c in campos:
        vals = [b.get(c) for b in barras if b.get(c) is not None]
        distintos = len(set(vals))
        out[c] = {"constante": (distintos == 1) if len(vals) > 1 else None,
                  "distintos": distintos, "amostras": len(vals),
                  "valor": vals[0] if distintos == 1 and vals else None}
    return out


def _docs(periodo: str, data_id: str) -> list[dict] | None:
    r = http_get(_url(periodo, data_id), headers=CABECALHO, timeout=45)
    if r is None:
        return None
    try:
        corpo = r.json()
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(corpo, dict):
        return None
    return corpo.get("docs") or []


def diario(data_id: str, periodo: str = "years") -> list[dict]:
    """Barras diarias OHLCV. `periodo`: 'years' (5 anos) ou 'months' (~3 meses)."""
    docs = _docs(periodo, data_id)
    return mapeia_interday(docs) if docs is not None else []


def intradiario(data_id: str) -> list[dict]:
    """Serie de 1 minuto da ultima sessao. Nao tem OHLC; ver armadilha 2."""
    docs = _docs("intraday", data_id)
    return mapeia_intraday(docs) if docs is not None else []


# -------------------------------------------------------------- sondagem ----
def avalia(barras: list[dict], hoje: dt.date | None = None) -> tuple[str, str]:
    """(status, motivo) pela regra da especificacao."""
    if not barras:
        return "sem_dado", "a API nao devolveu barra nenhuma"
    if len(barras) < MIN_BARRAS_ATIVO:
        return "sem_dado", f"so {len(barras)} barras (minimo {MIN_BARRAS_ATIVO})"
    hoje = hoje or dt.date.today()
    ultima = dt.date.fromisoformat(barras[-1]["date"])
    # pregoes ~ dias uteis; aproximacao suficiente para um corte de 10
    uteis = sum(1 for i in range((hoje - ultima).days)
                if (ultima + dt.timedelta(days=i + 1)).weekday() < 5)
    if uteis > MAX_ATRASO_PREGOES:
        return "descontinuado", f"ultima barra em {barras[-1]['date']} ({uteis} pregoes)"
    return "ativo", ""


# ------------------------------------------------------------- persistencia --
def grava_catalogo(itens: list[dict]) -> int:
    con = connect()
    agora = now_ts()
    n = 0
    with con:
        for it in itens:
            con.execute(
                "INSERT INTO ativos(ticker,fonte,categoria,status,visto_ts) "
                "VALUES (?,?,?,'nao_sondado',?) "
                "ON CONFLICT(ticker,fonte) DO UPDATE SET categoria=excluded.categoria,"
                " visto_ts=excluded.visto_ts",
                (it["ticker"], NOME, it["categoria"], agora))
            n += 1
    con.close()
    return n


def grava_id(ticker: str, data_id: str | None, nome: str | None) -> None:
    con = connect()
    with con:
        # `fonte` no WHERE porque `ativos` agora guarda uma linha por
        # (ticker, fonte): sem ele, isto escreveria o data-id da UOL na linha
        # do Yahoo do mesmo papel.
        con.execute("UPDATE ativos SET id_externo=?, nome=? "
                    "WHERE ticker=? AND fonte=?",
                    (data_id, nome, ticker, NOME))
    con.close()


def grava_sondagem(ticker: str, status: str, motivo: str,
                   barras: int, ultima: str | None) -> None:
    con = connect()
    with con:
        con.execute(
            "UPDATE ativos SET status=?, motivo=?, barras=?, ultima_barra=?, "
            "sondado_ts=? WHERE ticker=? AND fonte=?",
            (status, motivo or None, barras, ultima, now_ts(), ticker, NOME))
    con.close()


def pendentes(categorias=(ACAO,), limite: int | None = None,
              resondar: bool = False) -> list[dict]:
    """Papeis a sondar: sem id, ou sem sondagem, ou sondados ha > 30 dias."""
    con = connect()
    corte = now_ts() - DIAS_RESONDAR * 86400
    marc = ",".join("?" * len(categorias))
    q = (f"SELECT ticker, id_externo, status, sondado_ts FROM ativos "
         f"WHERE fonte=? AND categoria IN ({marc})")
    args = [NOME, *categorias]
    if not resondar:
        q += " AND (status='nao_sondado' OR sondado_ts IS NULL OR "
        q += " (status!='ativo' AND sondado_ts < ?))"
        args.append(corte)
    q += " ORDER BY ticker"
    if limite:
        q += f" LIMIT {int(limite)}"
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


# ------------------------------------------------------- ajuste (armadilha 3)
def conferir_ajuste(barras: list[dict], limiar: float = 0.35) -> list[dict]:
    """Saltos compativeis com desdobramento nao ajustado.

    Se a serie da UOL NAO for ajustada, um desdobramento aparece como queda de
    50%, 75% ou 90% num pregao. A serie atual do projeto nao tem nenhum salto
    assim em 10 anos, incluindo papel com desdobramento conhecido -- entao
    misturar as duas sem conferir produziria salto onde nao houve evento.
    """
    out = []
    for i in range(1, len(barras)):
        a, b = barras[i - 1]["close"], barras[i]["close"]
        if a and b and abs(b / a - 1) > limiar:
            out.append({"date": barras[i]["date"], "de": a, "para": b,
                        "variacao": b / a - 1, "razao": a / b})
    return out


# ---------------------------------------------------------- orquestracao ----
def descobrir(paginas_max: int = 60, verbose: bool = True) -> dict:
    """Passo 1: varre a listagem e grava o catalogo (sem id, sem cotacao)."""
    itens = catalogo(paginas_max, verbose=verbose)
    n = grava_catalogo(itens)
    por_cat: dict[str, int] = {}
    for it in itens:
        por_cat[it["categoria"]] = por_cat.get(it["categoria"], 0) + 1
    if verbose:
        print(f"\n-> {n} tickers no catalogo")
        for c, q in sorted(por_cat.items(), key=lambda kv: -kv[1]):
            print(f"   {c:<10}{q:>6}")
    return {"total": n, "por_categoria": por_cat}


def sondar(categorias=(ACAO,), limite: int | None = None,
           resondar: bool = False, verbose: bool = True) -> dict:
    """Passo 2: busca o data-id e valida se o papel tem serie utilizavel.

    Serializado com pausa, de proposito. ~1.800 papeis em paralelo agressivo
    leva bloqueio, e o catalogo nao e urgente.
    """
    alvos = pendentes(categorias, limite, resondar)
    if verbose:
        print(f"{len(alvos)} papel(is) a sondar")
    resumo = {"ativo": 0, "sem_dado": 0, "descontinuado": 0, "sem_id": 0}
    sem_dado_nominal = []
    for i, a in enumerate(alvos, 1):
        tkr = a["ticker"]
        data_id = a["id_externo"]
        if not data_id:
            data_id, nome = busca_id(tkr)
            time.sleep(PAUSA_S)
            if not data_id:
                grava_sondagem(tkr, "sem_dado", "data-id nao encontrado na pagina",
                               0, None)
                resumo["sem_id"] += 1
                sem_dado_nominal.append((tkr, "sem data-id"))
                continue
            grava_id(tkr, data_id, nome)
        barras = diario(data_id, "years")
        time.sleep(PAUSA_S)
        status, motivo = avalia(barras)
        grava_sondagem(tkr, status, motivo, len(barras),
                       barras[-1]["date"] if barras else None)
        resumo[status] = resumo.get(status, 0) + 1
        if status != "ativo":
            sem_dado_nominal.append((tkr, motivo))
        if verbose and (i % 25 == 0 or i == len(alvos)):
            print(f"  [uol] {i}/{len(alvos)}  {resumo}")
    if verbose and sem_dado_nominal:
        print(f"\nSEM DADO ou DESCONTINUADO ({len(sem_dado_nominal)}) -- "
              f"confira se algum papel bom caiu aqui:")
        for t, m in sem_dado_nominal:
            print(f"   {t:<10}{m}")
    return {"resumo": resumo, "sem_dado": sem_dado_nominal}


def coletar(tickers: list[str] | None = None, periodo: str = "years",
            limite: int | None = None, verbose: bool = True,
            complementar: bool = True) -> dict:
    """Passo 3: baixa as cotacoes dos ATIVOS e grava com origem=uol.

    complementar=True (PADRAO, e o que o projeto quer): a UOL ENTRA SEM APAGAR.
    Barra que falta entra inteira; barra que o Yahoo ou o brapi ja gravaram
    mantem o fechamento e a origem deles, e so recebe as colunas de OHLCV que
    estavam vazias. Sem isto, (ticker,date) + `INSERT OR REPLACE` trocaria 10
    anos de serie ajustada por 5 anos de serie de ajuste desconhecido, em
    silencio -- o oposto de complementar.

    complementar=False existe para quem quiser deliberadamente fazer da UOL a
    fonte canonica de um papel. Nao e o default e nao deveria ser usado sem
    antes olhar `prices.divergencia`.
    """
    from . import prices
    con = connect()
    if tickers:
        marc = ",".join("?" * len(tickers))
        rows = con.execute(
            f"SELECT ticker, id_externo FROM ativos WHERE fonte=? AND "
            f"ticker IN ({marc}) AND id_externo IS NOT NULL",
            [NOME, *[t.upper() for t in tickers]]).fetchall()
    else:
        q = ("SELECT ticker, id_externo FROM ativos WHERE fonte=? AND "
             "status='ativo' AND id_externo IS NOT NULL ORDER BY ticker")
        if limite:
            q += f" LIMIT {int(limite)}"
        rows = con.execute(q, (NOME,)).fetchall()
    con.close()
    if verbose:
        print(f"{len(rows)} papel(is) a coletar ({periodo})")
    total = 0
    saltos = {}
    divs = []
    for i, r in enumerate(rows, 1):
        barras = diario(r["id_externo"], periodo)
        time.sleep(PAUSA_S)
        if not barras:
            continue
        # ARMADILHA 3: se a UOL nao ajustar por proventos, um desdobramento
        # aparece como queda de 50/75/90% num pregao. Registra e avisa; nao
        # recusa, porque a origem por barra permite separar depois.
        s = conferir_ajuste(barras)
        if s:
            saltos[r["ticker"]] = s
        # SEGUNDA OPINIAO: onde as duas fontes tem a mesma barra, comparar os
        # fechamentos responde a armadilha 3 sem depender de desdobramento
        # conhecido. Tem de rodar ANTES da gravacao, porque no modo
        # complementar o fechamento antigo fica e a comparacao se perderia.
        if complementar:
            divs.extend(prices.divergencia({r["ticker"]: barras}, NOME))
        total += prices.grava_diario({r["ticker"]: barras}, NOME,
                                     complementar=complementar)
        if verbose and (i % 25 == 0 or i == len(rows)):
            print(f"  [uol] {i}/{len(rows)}  {total} barras gravadas")
    if verbose and saltos:
        print(f"\nSALTOS > 35% EM UM PREGAO ({len(saltos)} papel(is)) -- "
              f"possivel serie NAO ajustada por proventos:")
        for t, lst in list(saltos.items())[:15]:
            for s in lst[:2]:
                print(f"   {t:<8}{s['date']}  {s['de']:.2f} -> {s['para']:.2f}"
                      f"  ({100*s['variacao']:+.1f}%, razao {s['razao']:.2f}:1)")
    if verbose and divs:
        papeis = sorted({d["ticker"] for d in divs})
        print(f"\nDISCORDANCIA COM O QUE JA ESTAVA NO BANCO: {len(divs)} "
              f"barra(s) em {len(papeis)} papel(is), diferenca >= 1%.")
        print("O que ja estava FICA -- nada foi sobrescrito. Discordancia que")
        print("CRESCE para tras indica regra de ajuste por proventos diferente")
        print("entre as fontes; nesse caso as duas series nao sao misturaveis.")
        for d in divs[:10]:
            print(f"   {d['ticker']:<8}{d['date']}  "
                  f"{d['origem_antiga']} {d['close_antigo']:.2f}  vs  "
                  f"{d['origem_nova']} {d['close_novo']:.2f}   "
                  f"({100*d['diferenca']:.1f}%)")
        if len(divs) > 10:
            print(f"   ... e {len(divs)-10} outras")
    return {"papeis": len(rows), "barras": total, "saltos": saltos,
            "divergencias": divs, "complementar": complementar}


def coletar_intraday(tickers: list[str], verbose: bool = True) -> int:
    """Serie de 1 min da ultima sessao, para os papeis pedidos.

    Grava em `intraday` com intervalo '1m' e origem 'uol'. Nao monta OHLC:
    a API nao da (armadilha 2). Grava bid/ask, que nenhuma outra fonte do
    projeto da, e avisa se eles sairem constantes -- porque ai sao da sessao
    e nao servem como spread por minuto.
    """
    from . import intraday as intra
    con = connect()
    intra.init(con)
    marc = ",".join("?" * len(tickers))
    rows = con.execute(
        f"SELECT ticker, id_externo FROM ativos WHERE fonte=? AND "
        f"ticker IN ({marc}) AND id_externo IS NOT NULL",
        [NOME, *[t.upper() for t in tickers]]).fetchall()
    n = 0
    for r in rows:
        barras = intradiario(r["id_externo"])
        time.sleep(PAUSA_S)
        with con:
            for b in barras:
                cur = con.execute(
                    "INSERT OR REPLACE INTO intraday"
                    "(simbolo,intervalo,ts,close,volume,origem,bid,ask)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (r["ticker"], "1m", b["ts"], b["close"], b["volume"],
                     NOME, b.get("bid"), b.get("ask")))
                n += cur.rowcount
        if verbose:
            print(f"  [uol] {r['ticker']}: {len(barras)} barras de 1 min")
            # responde, na primeira coleta real, se bid/ask sao por barra ou
            # da sessao -- a pergunta que a sondagem deixou aberta.
            for campo, info in constantes(barras).items():
                if info["constante"] is True:
                    print(f"     AVISO {campo}: CONSTANTE em "
                          f"{info['amostras']} barras (valor {info['valor']}). "
                          f"E da SESSAO, nao da barra.")
    con.close()
    return n


def estado() -> dict:
    """Contagem por categoria e por status, para o relatorio de aceite."""
    con = connect()
    out = {"por_categoria": {}, "por_status": {}, "sem_dado": []}
    for r in con.execute("SELECT categoria, COUNT(*) n FROM ativos "
                         "WHERE fonte=? GROUP BY 1 ORDER BY n DESC", (NOME,)):
        out["por_categoria"][r["categoria"]] = r["n"]
    for r in con.execute("SELECT status, COUNT(*) n FROM ativos "
                         "WHERE fonte=? GROUP BY 1 ORDER BY n DESC", (NOME,)):
        out["por_status"][r["status"]] = r["n"]
    out["sem_dado"] = [dict(r) for r in con.execute(
        "SELECT ticker, categoria, motivo, barras, ultima_barra FROM ativos "
        "WHERE fonte=? AND status IN ('sem_dado','descontinuado') "
        "ORDER BY ticker", (NOME,))]
    out["com_barras"] = con.execute(
        "SELECT COUNT(DISTINCT ticker) FROM prices WHERE origem=?",
        (NOME,)).fetchone()[0]
    con.close()
    return out
