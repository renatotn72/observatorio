"""Cadeia de afetacao: cambio, commodities e indices -> exposicao por acao.

A IDEIA
    Cada acao e uma carteira implicita de fatores macro. A VALE3 e, em boa
    medida, minerio + dolar; a MGLU3 e consumo domestico + juros; a PETR4 e
    petroleo + dolar + risco regulatorio. Estimar esse vetor permite que uma
    noticia sobre MINERIO vire sinal para VALE3, CSNA3 e GGBR4 ao mesmo tempo,
    sem que nenhuma delas seja citada no texto.

    E o que multiplica a contagem de eventos: hoje um papel so reage a materia
    que escreve o nome dele.

A ARMADILHA (motivo de isto ser regressao MULTIPLA, nao betas separados)
    Brent, cobre, ouro, DXY e USDBRL sao fortemente correlacionados -- quase
    todos carregam o fator dolar. Betas univariados somados contam o dolar
    varias vezes, e a "cadeia de afetacao" vira caricatura: todo papel parece
    exposto a tudo. A regressao multipla com ridge reparte a variancia comum.

DISCIPLINA DE JANELA
    Toda barra diaria usada aqui fecha ATE 00:59 BRT (commodities/NY) ou
    19:59 BRT (cambio). O pregao da B3 vai das 10:00 as 18:00. Logo o driver
    do dia T so pode ser casado com o alvo do dia T+1 -- nunca do proprio T,
    que foi o erro que inflou o IC do Brent de 0.02 para 0.19 na primeira
    medicao deste projeto.
"""
from __future__ import annotations
import concurrent.futures as cf
import json

import numpy as np

from .db import connect
from .util import date_str, http_get

YF = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; observatorio-academico)"}

# nome -> (simbolo Yahoo, categoria)
DRIVERS: dict[str, tuple[str, str]] = {
    # cambio -- fecha 19:59 BRT
    "USDBRL":  ("USDBRL%3DX", "cambio"),
    "DXY":     ("DX-Y.NYB",   "cambio"),
    "EURUSD":  ("EURUSD%3DX", "cambio"),
    "USDCNY":  ("USDCNY%3DX", "cambio"),
    # metais
    "OURO":    ("GC%3DF",     "metal"),
    "COBRE":   ("HG%3DF",     "metal"),
    "MINERIO": ("TIO%3DF",    "metal"),
    # energia
    "BRENT":   ("BZ%3DF",     "energia"),
    "GAS":     ("NG%3DF",     "energia"),
    # agro
    "SOJA":    ("ZS%3DF",     "agro"),
    "ACUCAR":  ("SB%3DF",     "agro"),
    "CAFE":    ("KC%3DF",     "agro"),
    # NAO reintroduza "WOOD" aqui: e um ETF de ACOES de madeira/papel, nao um
    # futuro de celulose. Como ETF de equity ele carrega beta global de bolsa e
    # aparecia no top-4 de Ambev, Bradesco e Gerdau -- contaminando toda cadeia
    # de afetacao com um fator que nao e commodity. Celulose nao tem futuro
    # liquido de graca; fica sem driver proprio ate haver fonte melhor.
    # risco global
    "SPX":     ("%5EGSPC",    "indice"),
    "HSI":     ("%5EHSI",     "indice"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS driver_prices (
  driver TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL,
  PRIMARY KEY (driver, date)
);
CREATE TABLE IF NOT EXISTS exposures (
  ticker TEXT NOT NULL, asof TEXT NOT NULL, driver TEXT NOT NULL,
  beta REAL NOT NULL, share REAL NOT NULL, r2 REAL NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (ticker, asof, driver)
);
CREATE INDEX IF NOT EXISTS ix_exp_tk ON exposures(ticker, asof);
"""

RIDGE = 1.0          # em unidades padronizadas; amortece a colinearidade
MIN_OBS = 120        # pregoes minimos para estimar a cadeia


def init() -> None:
    con = connect()
    with con:
        con.executescript(SCHEMA)
    con.close()


# ------------------------------------------------------------------ dados ---
def fetch_series(symbol: str, rng: str = "2y") -> dict[str, float]:
    r = http_get(YF + symbol, params={"range": rng, "interval": "1d"}, headers=HEAD)
    if r is None:
        return {}
    try:
        res = r.json()["chart"]["result"][0]
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    out = {}
    q = res["indicators"]["quote"][0]
    for i, t in enumerate(res["timestamp"]):
        c = q["close"][i]
        if c:
            out[date_str(t)] = float(c)
    return out


SYNC_PARALELO = 6


def sync(rng: str = "2y") -> int:
    """Baixa os drivers em paralelo e SO DEPOIS escreve.

    DUAS CORRECOES, as duas medidas em 2026-10-02:

    1. BUSCA EM PARALELO. Sao 14 endpoints independentes do Yahoo, sem limite
       de taxa compartilhado (ao contrario do GDELT). Em serie davam 2,8s.

    2. NAO SEGURAR A TRANSACAO DURANTE A REDE. A versao anterior abria
       `with con:` e so fechava depois das 14 chamadas HTTP, mantendo o lock de
       escrita do SQLite por toda a duracao da rede. Isso era inofensivo
       enquanto os jobs rodavam em fila; com o worker paralelo passa a ser
       defeito, porque bloqueia o `store` da ingestao sem nenhuma razao. Agora
       a rede acontece fora da transacao e a escrita e um `executemany` curto.
    """
    init()
    alvos = list(DRIVERS.items())
    with cf.ThreadPoolExecutor(max_workers=SYNC_PARALELO) as pool:
        series = list(pool.map(lambda kv: (kv[0], fetch_series(kv[1][0], rng)),
                               alvos))
    linhas, n = [], 0
    for name, ser in series:
        if not ser:
            print(f"  [driver] {name}: falhou")
            continue
        linhas += [(name, d, c) for d, c in ser.items()]
        n += len(ser)
        print(f"  [driver] {name:<9} {len(ser):>4} pregoes")
    con = connect()
    with con:
        con.executemany("INSERT OR REPLACE INTO driver_prices VALUES (?,?,?)",
                        linhas)
    con.close()
    return n


def driver_returns(con, only_registered: bool = True) -> dict[str, dict[str, float]]:
    """So devolve drivers que ainda constam do registro DRIVERS.

    Sem este filtro, um driver removido do codigo continua vivo porque as
    linhas antigas permanecem em `driver_prices` -- foi exatamente assim que
    o ETF WOOD seguiu contaminando as cadeias depois de eu o 'remover'.
    """
    rows = con.execute("SELECT driver,date,close FROM driver_prices ORDER BY driver,date")
    by: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by.setdefault(r["driver"], []).append((r["date"], r["close"]))
    out = {}
    for k, ser in by.items():
        if only_registered and k not in DRIVERS:
            continue
        d = {}
        for i in range(1, len(ser)):
            if ser[i - 1][1]:
                d[ser[i][0]] = ser[i][1] / ser[i - 1][1] - 1.0
        out[k] = d
    return out


def purge_unregistered() -> int:
    """Apaga do banco os drivers que sairam do registro."""
    con = connect()
    with con:
        cur = con.execute(
            "DELETE FROM driver_prices WHERE driver NOT IN (%s)"
            % ",".join("?" * len(DRIVERS)), tuple(DRIVERS))
        con.execute("DELETE FROM exposures WHERE driver NOT IN (%s)"
                    % ",".join("?" * len(DRIVERS)), tuple(DRIVERS))
    n = cur.rowcount
    con.close()
    return n


# ------------------------------------------------------------- exposicao ---
def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = RIDGE):
    """OLS com ridge em espaco padronizado. Devolve (beta_padronizado, r2)."""
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    ys = y - y.mean()
    p = Xs.shape[1]
    b = np.linalg.solve(Xs.T @ Xs + lam * np.eye(p), Xs.T @ ys)
    pred = Xs @ b
    ss_res = float(((ys - pred) ** 2).sum())
    ss_tot = float((ys ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return b, r2, sd


def fit_exposures(stock_returns: dict[str, dict[str, float]], asof: str,
                  window: int = 250, persist: bool = True) -> dict[str, dict]:
    """Cadeia de afetacao de cada acao em `asof`, usando SO dados anteriores.

    O vetor devolvido traz, por driver:
      beta  -- sensibilidade em unidades padronizadas
      share -- participacao na variancia explicada, que e o "indice de afetacao"
               legivel: quanto daquele papel e petroleo, quanto e dolar.
    """
    con = connect()
    dret = driver_returns(con)
    names = sorted(dret)

    out: dict[str, dict] = {}
    rows_to_save = []
    for tkr, sret in stock_returns.items():
        dates = sorted(d for d in sret if d < asof)      # ESTRITAMENTE anterior
        dates = [d for d in dates if all(d in dret[k] for k in names)][-window:]
        if len(dates) < MIN_OBS:
            continue
        X = np.array([[dret[k][d] for k in names] for d in dates])
        y = np.array([sret[d] for d in dates])
        b, r2, sd = ridge_fit(X, y)

        contrib = np.abs(b)                              # ja padronizado
        tot = contrib.sum()
        shares = contrib / tot if tot > 0 else contrib
        vec = {names[i]: {"beta": float(b[i]), "share": float(shares[i])}
               for i in range(len(names))}
        out[tkr] = {"r2": r2, "n": len(dates), "drivers": vec, "sd": sd.tolist()}
        if persist:
            for i, k in enumerate(names):
                rows_to_save.append((tkr, asof, k, float(b[i]), float(shares[i]),
                                     r2, len(dates)))

    if persist and rows_to_save:
        with con:
            con.executemany(
                "INSERT OR REPLACE INTO exposures VALUES (?,?,?,?,?,?,?)", rows_to_save)
    con.close()
    return out


def affect_index(exposure: dict, top: int = 5) -> list[tuple[str, float, float]]:
    """Cadeia de afetacao legivel: [(driver, share, beta)] ordenada."""
    items = [(k, v["share"], v["beta"]) for k, v in exposure["drivers"].items()]
    items.sort(key=lambda t: -t[1])
    return items[:top]


def driver_signal(exposures: dict[str, dict], dret: dict[str, dict[str, float]],
                  date: str) -> dict[str, float]:
    """Sinal do dia: previsao do residuo transversal a partir dos drivers.

    `date` e o dia T do DRIVER; o alvo e o pregao T+1 da B3.
    """
    raw = {}
    for tkr, exp in exposures.items():
        names = sorted(exp["drivers"])
        sd = exp.get("sd") or [1.0] * len(names)
        s = 0.0
        for i, k in enumerate(names):
            if date in dret.get(k, {}):
                s += exp["drivers"][k]["beta"] * (dret[k][date] / (sd[i] or 1.0))
        raw[tkr] = s
    if not raw:
        return {}
    m = sum(raw.values()) / len(raw)          # demeia: sinal e transversal
    return {k: v - m for k, v in raw.items()}
