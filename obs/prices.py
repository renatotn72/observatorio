"""Precos diarios: uma interface, varias fontes.

CADA FONTE DEVOLVE O MESMO FORMATO -- lista de barras
    {"date": "YYYY-MM-DD", "close": float,
     "open": float|None, "high": float|None, "low": float|None,
     "volume": float|None}
e a gravacao carimba a ORIGEM em cada barra. Sem a origem, misturar fontes com
regras de ajuste diferentes produz salto onde nao houve evento e ninguem
consegue dizer de onde veio o ponto torto.

ALCANCE REAL DE CADA UMA, medido no banco (docs/precos-fontes.md):
    yahoo  diario 10 anos | 1h 2 anos | 15m e 5m 1 mes | 1m 5 dias
    brapi  sem token ~1mo; com BRAPI_TOKEN, historico longo e indices
    uol    diario 5 anos (teto fixo) | 1m so a ultima sessao
           MAS: ~1.800 tickers contra os 10 da watchlist, e OHLCV com VOLUME,
           que e o filtro de liquidez que falta para ampliar o universo.

Ou seja: a UOL nao e fonte de backfill -- e mais curta que o que ja temos em
toda granularidade. Ela vale por LARGURA e por VOLUME.
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


def fetch(tickers: list[str], range_: str = "1mo") -> dict[str, list[tuple[str, float]]]:
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


def fetch_yahoo(tickers: list[str], range_: str = "2y") -> dict[str, list[tuple[str, float]]]:
    """Fonte alternativa de precos. Existe porque o tier gratuito do brapi tem
    cota por janela e nao cobre uma watchlist de 10+ papeis; o Yahoo responde
    sem chave e com 2 anos de historico, que e o que a calibracao exige.
    Simbolo da B3 no Yahoo = ticker + '.SA'.

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


def grava_diario(series: dict[str, list[dict]], origem: str) -> int:
    """Grava barras diarias carimbando a origem. Idempotente por (ticker,date).

    `INSERT OR REPLACE` apaga a linha e insere outra, entao TODAS as colunas
    entram -- omitir uma zeraria o que ja estava la. Acrescentar coluna a
    `prices` obriga a acrescentar aqui.
    """
    con = connect()
    n = 0
    with con:
        for sym, rows in series.items():
            for b in rows:
                cur = con.execute(
                    "INSERT OR REPLACE INTO prices"
                    "(ticker,date,close,open,high,low,volume,origem)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (sym, b["date"], b["close"], b.get("open"), b.get("high"),
                     b.get("low"), b.get("volume"), origem))
                n += cur.rowcount
    con.close()
    return n


# Registro de fontes. `diario(tickers, range_)` e a unica forma que o resto do
# sistema conhece; trocar de fonte nao toca em mais nada.
FONTES = {
    "brapi": {"diario": fetch, "rotulo": "brapi.dev"},
    "yahoo": {"diario": fetch_yahoo, "rotulo": "Yahoo Finance"},
}


def sync(range_: str = "1mo", fonte: str = "auto") -> int:
    tkrs = list(config.tickers())
    bench = config.watchlist().get("benchmark", "__crosssec__")
    if bench != "__crosssec__":
        tkrs = tkrs + [bench]

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
