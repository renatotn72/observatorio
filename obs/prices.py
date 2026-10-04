"""Precos diarios: uma interface, varias fontes, e nenhuma apagando a outra.

CADA FONTE DEVOLVE O MESMO FORMATO -- lista de barras
    {"date": "YYYY-MM-DD", "close": float,
     "open": float|None, "high": float|None, "low": float|None,
     "volume": float|None}
e a gravacao carimba a ORIGEM em cada barra. Sem a origem, misturar fontes com
regras de ajuste diferentes produz salto onde nao houve evento e ninguem
consegue dizer de onde veio o ponto torto.

COMPLEMENTAR NAO E SUBSTITUIR -- e por isso que `grava_diario` tem dois modos.
A chave de `prices` e (ticker, date) e a gravacao e `INSERT OR REPLACE`. Logo,
no modo padrao, coletar de uma fonte nova REESCREVE as barras da antiga. Para
uma fonte que entra como complemento isso e o contrario do que se quer: a
serie longa e ajustada que ja esta no banco seria trocada por outra, mais curta
e de ajuste desconhecido, em silencio. No modo `complementar=True` quem chegou
primeiro FICA: o fechamento e a `origem` nao se tocam, so as colunas VAZIAS de
OHLCV sao preenchidas, e `origem_ohlc` registra quem as preencheu. Barra que
nao existia entra inteira. Assim uma fonte tapa buraco e enriquece sem
sobrescrever nada, e cada metade da barra continua rastreavel.

ALCANCE REAL DE CADA UMA, medido no banco (docs/precos-fontes.md):
    yahoo  diario 10 anos | 1h 2 anos | 15m e 5m 1 mes | 1m 5 dias
           OHLCV completo por barra -- open/high/low/volume vem no mesmo
           endpoint do fechamento.
    brapi  sem token ~1mo; com BRAPI_TOKEN, historico longo e indices.
           OHLCV por barra, e fechamento AJUSTADO (adjustedClose).
    uol    diario 5 anos (teto fixo, sem paginacao para tras) | 1m so a
           ultima sessao. OHLCV por barra no interday.

O QUE A UOL ACRESCENTA, SENDO MAIS CURTA QUE O QUE JA TEMOS
    1. DESCOBERTA. O Yahoo nao tem endpoint de listagem: para pedir um papel
       e preciso JA saber o ticker. A UOL tem catalogo paginado, ~1.800
       tickers com id interno, que e o que falta para sair dos 10 papeis da
       watchlist para os 150-300 que docs/universo.md pede.
    2. BID/ASK. Spread cotado, que nenhuma das outras duas da e que
       docs/canal-noticias.md pede como feature de liquidez.
    3. SEGUNDA OPINIAO. Duas fontes na mesma (ticker, date) permitem
       conferir ajuste por proventos comparando fechamentos -- ver
       `divergencia()`.
    NAO acrescenta historico: e mais curta que o Yahoo em toda granularidade.
    Quem vier aqui atras de backfill longo vai piorar a serie.
"""
from __future__ import annotations
import concurrent.futures as cf
import os
import time

from . import config
from .db import connect
from .util import date_str, http_get

BRAPI = "https://brapi.dev/api/quote/"
# O brapi gratuito estrangula rajadas; sem pausa os lotes seguintes voltam vazios.
BRAPI_DELAY_S = 2.0


def fetch(tickers: list[str], range_: str = "1mo") -> dict[str, list[dict]]:
    params = {"range": range_, "interval": "1d"}
    token = os.environ.get("BRAPI_TOKEN")
    if token:
        params["token"] = token

    # ATENCAO ao diagnosticar: sem token o brapi nao limita o TAMANHO do lote,
    # limita a COTA de simbolos por janela. Esgotada a cota ele responde 401
    # "Token de autenticacao nao fornecido" -- mensagem enganosa, porque parece
    # falta de auth e na verdade e cota estourada. Na pratica: uma watchlist de
    # 10 papeis NAO cabe no gratuito; pegue um token (gratuito) em brapi.dev.
    batch = 10 if token else 3
    out: dict[str, list[tuple[str, float]]] = {}
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        if i:
            time.sleep(BRAPI_DELAY_S)
        r = http_get(BRAPI + ",".join(chunk), params=params)
        if r is None:
            print(f"  [prices] lote {chunk} falhou")
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        if data.get("error"):
            msg = data.get("message", "")
            if "oken" in msg and not token:
                print(f"  [prices] {chunk}: cota do tier gratuito esgotada "
                      f"(o 401 diz 'token nao fornecido', mas e cota). "
                      f"Defina BRAPI_TOKEN para cobrir a watchlist inteira.")
            else:
                print(f"  [prices] {chunk}: {msg}")
            continue
        for res in data.get("results", []):
            sym = res.get("symbol")
            hist = res.get("historicalDataPrice") or []
            series = [{"date": date_str(h["date"]),
                       "close": float(h.get("adjustedClose") or h["close"]),
                       "open": h.get("open"), "high": h.get("high"),
                       "low": h.get("low"), "volume": h.get("volume")}
                      for h in hist if h.get("close") or h.get("adjustedClose")]
            if series:
                out[sym] = series
    return out


YF = "https://query1.finance.yahoo.com/v8/finance/chart/"
YF_HEAD = {"User-Agent": "Mozilla/5.0 (compatible; observatorio-academico)"}
YF_PARALELO = 6


def fetch_yahoo(tickers: list[str], range_: str = "2y") -> dict[str, list[dict]]:
    """Fonte alternativa de precos. Existe porque o tier gratuito do brapi tem
    cota por janela e nao cobre uma watchlist de 10+ papeis; o Yahoo responde
    sem chave e com 2 anos de historico, que e o que a calibracao exige.
    Simbolo da B3 no Yahoo = ticker + '.SA'.

    O endpoint traz OHLCV COMPLETO no mesmo pacote do fechamento
    (indicators.quote[0].open/high/low/volume). Nao e preciso outra fonte para
    ter volume: o que falta no Yahoo e DESCOBERTA (nao existe endpoint de
    listagem; e preciso ja saber o ticker) e BID/ASK.

    EM PARALELO: sao endpoints independentes, sem limite de taxa compartilhado
    -- ao contrario do GDELT, onde paralelizar seria abusar de um servico que
    pede 1 requisicao a cada 5s. Em serie, uma watchlist de 300 papeis levaria
    minutos de relogio so esperando rede."""
    out = {}

    def _um(t):
        return t, http_get(YF + t + ".SA",
                           params={"range": range_, "interval": "1d"},
                           headers=YF_HEAD)

    with cf.ThreadPoolExecutor(max_workers=YF_PARALELO) as pool:
        respostas = list(pool.map(_um, tickers))
    for t, r in respostas:
        if r is None:
            continue
        try:
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        ser = []
        for i, ts in enumerate(res["timestamp"]):
            c = q["close"][i]
            if c:
                ser.append({"date": date_str(ts), "close": float(c),
                            "open": q.get("open", [None] * (i + 1))[i],
                            "high": q.get("high", [None] * (i + 1))[i],
                            "low": q.get("low", [None] * (i + 1))[i],
                            "volume": q.get("volume", [None] * (i + 1))[i]})
        if ser:
            out[t] = ser
    return out


OHLCV = ("open", "high", "low", "volume")


def _marca_origem(atual: str | None, nova: str) -> str:
    """Procedencia acumulada: 'yahoo' + 'uol' = 'yahoo+uol'.

    Quando uma fonte deu abertura/maxima/minima e a outra deu o volume, dizer
    so uma das duas e mentira. Nao repete nome ja presente, entao reexecutar a
    coleta nao faz o campo crescer.
    """
    if not atual:
        return nova
    return atual if nova in atual.split("+") else atual + "+" + nova


def _origem_ohlc(b: dict, origem: str) -> str | None:
    """Carimba a origem do OHLCV so se a barra trouxe algum deles."""
    return origem if any(b.get(k) is not None for k in OHLCV) else None


def grava_diario(series: dict[str, list[dict]], origem: str,
                 complementar: bool = False) -> int:
    """Grava barras diarias carimbando a origem. Idempotente por (ticker,date).

    complementar=False (padrao): `INSERT OR REPLACE`, a barra nova manda. E o
        que se quer quando a fonte e a MESMA de antes (atualizacao) ou quando
        se esta deliberadamente recoletando.
        Atencao: `INSERT OR REPLACE` apaga a linha e insere outra, entao TODAS
        as colunas entram -- omitir uma zeraria o que ja estava la.
        Acrescentar coluna a `prices` obriga a acrescentar aqui.

    complementar=True: quem chegou primeiro FICA. Barra inexistente entra
        inteira; barra existente mantem close e `origem` e so recebe os OHLCV
        que estavam NULL, com `origem_ohlc` registrando quem os deu. Nenhum
        numero ja gravado e trocado -- o que divergir entre as fontes nao e
        sobrescrito nem escondido, e aparece em `divergencia()`.
    """
    con = connect()
    n = 0
    with con:
        for sym, rows in series.items():
            ja = {}
            if complementar:
                ja = {r["date"]: r for r in con.execute(
                    "SELECT date,close,open,high,low,volume,origem,origem_ohlc"
                    " FROM prices WHERE ticker=?", (sym,))}
            for b in rows:
                velha = ja.get(b["date"])
                if velha is None:
                    cur = con.execute(
                        "INSERT OR REPLACE INTO prices"
                        "(ticker,date,close,open,high,low,volume,origem,origem_ohlc)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (sym, b["date"], b["close"], b.get("open"), b.get("high"),
                         b.get("low"), b.get("volume"), origem,
                         _origem_ohlc(b, origem)))
                    n += cur.rowcount
                    continue
                # barra existente, modo complementar: so o que esta vazio.
                falta = [k for k in OHLCV
                         if velha[k] is None and b.get(k) is not None]
                if not falta:
                    continue
                valores = {k: (velha[k] if velha[k] is not None else b.get(k))
                           for k in OHLCV}
                con.execute(
                    "UPDATE prices SET open=?,high=?,low=?,volume=?,origem_ohlc=?"
                    " WHERE ticker=? AND date=?",
                    (valores["open"], valores["high"], valores["low"],
                     valores["volume"],
                     _marca_origem(velha["origem_ohlc"], origem),
                     sym, b["date"]))
                n += 1
    con.close()
    return n


def divergencia(series: dict[str, list[dict]], origem: str,
                limiar: float = 0.01) -> list[dict]:
    """Onde a fonte nova discorda da que ja esta no banco, na MESMA barra.

    E o teste de AJUSTE POR PROVENTOS que nao precisa de evento conhecido: se
    uma fonte ajusta e a outra nao, os fechamentos batem depois do ultimo
    provento e se afastam antes dele, com a discordancia CRESCENDO para tras.
    Dois fechamentos iguais em cinco anos dizem que as duas usam a mesma
    regra; discordancia sistematica diz que nao sao misturaveis e que a serie
    tem de ficar separada por origem.

    Nao grava nada: so le e relata. Rode ANTES de `grava_diario`, porque no
    modo complementar o fechamento antigo fica e a comparacao se perde.
    `limiar` e a diferenca relativa minima para contar (1% ignora arredondamento
    de centavo e diferenca de horario de fechamento).
    """
    con = connect()
    out = []
    for sym, rows in series.items():
        ja = {r["date"]: (r["close"], r["origem"]) for r in con.execute(
            "SELECT date,close,origem FROM prices WHERE ticker=?", (sym,))}
        for b in rows:
            antigo = ja.get(b["date"])
            if not antigo or not antigo[0] or b.get("close") is None:
                continue
            d = abs(b["close"] - antigo[0]) / antigo[0]
            if d >= limiar:
                out.append({"ticker": sym, "date": b["date"],
                            "origem_antiga": antigo[1], "close_antigo": antigo[0],
                            "origem_nova": origem, "close_novo": b["close"],
                            "diferenca": d})
    con.close()
    out.sort(key=lambda x: (x["ticker"], x["date"]))
    return out


def fetch_uol(tickers: list[str], range_: str = "years") -> dict[str, list[dict]]:
    """A UOL atras da MESMA interface das outras: ticker entra, barras saem.

    Traduz ticker -> data_id pela tabela `ativos` (preenchida por
    `uol-descobrir` + `uol-sondar`). Papel sem id ainda sondado simplesmente
    nao sai no resultado -- e o mesmo contrato das outras fontes, que tambem
    omitem quem nao responde.

    `range_` aqui e o periodo da UOL: 'years' (5 anos) ou 'months' (~3 meses).
    Valor de outra fonte ('1mo', '2y') cai em 'months', porque pedir 5 anos
    para atualizar o dia e desperdicio de rede do outro lado.
    """
    from . import uol
    con = connect()
    marc = ",".join("?" * len(tickers))
    rows = con.execute(
        f"SELECT ticker, id_externo FROM ativos WHERE ticker IN ({marc}) "
        f"AND id_externo IS NOT NULL", [t.upper() for t in tickers]).fetchall()
    con.close()
    periodo = range_ if range_ in ("years", "months") else "months"
    out = {}
    for r in rows:
        barras = uol.diario(r["id_externo"], periodo)
        time.sleep(uol.PAUSA_S)
        if barras:
            out[r["ticker"]] = barras
    return out


# Registro de fontes. `diario(tickers, range_)` e a unica forma que o resto do
# sistema conhece; trocar de fonte nao toca em mais nada.
#   complementar: True  = fonte que ENTRA SEM APAGAR a serie que ja existe.
#                 False = fonte canonica, a barra dela manda.
# A UOL e complementar por decisao, nao por acaso: e mais curta e de ajuste
# desconhecido, entao deixa-la mandar trocaria 10 anos de serie ajustada por
# 5 anos de serie suspeita (ver o cabecalho do modulo).
FONTES = {
    "brapi": {"diario": fetch, "rotulo": "brapi.dev", "complementar": False},
    "yahoo": {"diario": fetch_yahoo, "rotulo": "Yahoo Finance",
              "complementar": False},
    "uol": {"diario": fetch_uol, "rotulo": "UOL Cotacoes",
            "complementar": True},
}


def sync(range_: str = "1mo", fonte: str = "auto") -> int:
    """Sincroniza o diario da watchlist.

    'auto' mantem o comportamento historico: brapi primeiro, Yahoo para quem
    o brapi nao devolveu -- os dois sem sobreposicao, entao nenhum apaga o
    outro. Uma fonte nomeada roda sozinha, respeitando o modo `complementar`
    do registro: a UOL preenche buraco e volume sem tocar no que ja existe.
    """
    tkrs = list(config.tickers())
    bench = config.watchlist().get("benchmark", "__crosssec__")
    if bench != "__crosssec__":
        tkrs = tkrs + [bench]

    if fonte not in ("auto", "brapi", "yahoo"):
        f = FONTES.get(fonte)
        if not f:
            print(f"  [prices] fonte desconhecida: {fonte}")
            return 0
        series = f["diario"](tkrs, range_)
        if f["complementar"]:
            div = divergencia(series, fonte)
            if div:
                print(f"  [prices] {len(div)} barra(s) em que {fonte} discorda "
                      f"do que ja esta no banco (>1%). O que ja estava FICA; "
                      f"veja `python3 -m obs.cli uol-divergencia`.")
        n = grava_diario(series, fonte, complementar=f["complementar"])
        print(f"-> {len(series)} papeis, {n} cotacoes gravadas ({fonte}"
              f"{', complementando' if f['complementar'] else ''})")
        return n

    n = 0
    series = {}
    if fonte in ("auto", "brapi"):
        series = fetch(tkrs, range_)
        if series:
            n += grava_diario(series, "brapi")
    faltando = [t for t in tkrs if t not in series]
    if faltando and fonte in ("auto", "yahoo"):
        print(f"  [prices] {len(faltando)} papeis sem brapi -> Yahoo")
        y = fetch_yahoo(faltando, "2y" if range_ in ("1mo", "2y") else range_)
        series.update(y)
        n += grava_diario(y, "yahoo")
    print(f"-> {len(series)} papeis, {n} cotacoes gravadas")
    return n


def returns_by_date(con) -> dict[str, dict[str, float]]:
    """{ticker: {date: retorno_simples_do_dia}}."""
    rows = con.execute("SELECT ticker,date,close FROM prices ORDER BY ticker,date").fetchall()
    by: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append((r["date"], r["close"]))
    rets: dict[str, dict[str, float]] = {}
    for tkr, ser in by.items():
        d = {}
        for i in range(1, len(ser)):
            prev, cur = ser[i - 1][1], ser[i][1]
            if prev:
                d[ser[i][0]] = cur / prev - 1.0
        rets[tkr] = d
    return rets
