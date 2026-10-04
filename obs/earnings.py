"""Infraestrutura para consenso, surpresa trimestral e PEAD.

Nenhum score é apresentado como validado sem backtest temporal. Consenso deve ter
timestamp/asof anterior à divulgação; planilha sem data de consenso é rejeitada.
"""
from __future__ import annotations
import csv
import json
import math
import statistics as st
import time
from pathlib import Path
from .db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings_consensus (
 ticker TEXT NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL,
 consensus REAL NOT NULL, dispersion REAL, n_analysts INTEGER,
 asof_ts INTEGER NOT NULL, source TEXT NOT NULL, created_ts INTEGER NOT NULL,
 PRIMARY KEY (ticker,period,metric,asof_ts)
);
CREATE TABLE IF NOT EXISTS earnings_actual (
 ticker TEXT NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL,
 actual REAL NOT NULL, released_ts INTEGER NOT NULL, source TEXT,
 report_id INTEGER, created_ts INTEGER NOT NULL,
 PRIMARY KEY (ticker,period,metric,released_ts)
);
CREATE TABLE IF NOT EXISTS earnings_surprises (
 ticker TEXT NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL,
 consensus REAL, dispersion REAL, actual REAL NOT NULL, surprise REAL,
 asof_ts INTEGER NOT NULL, released_ts INTEGER NOT NULL, source TEXT,
 validated INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(ticker,period,metric,released_ts)
);
CREATE INDEX IF NOT EXISTS idx_earn_ticker ON earnings_surprises(ticker,released_ts DESC);
"""


def init(con=None):
    own = con is None; con = con or connect()
    with con: con.executescript(SCHEMA)
    if own: con.close()


def import_consensus_csv(path: str | Path) -> dict:
    """CSV obrigatório: ticker,period,metric,consensus,asof_date,source.
    Opcionais: dispersion,n_analysts. asof_date deve ser ISO ou epoch antes do release.
    """
    n = bad = 0
    con = connect(); init(con)
    with open(path, encoding="utf-8-sig", newline="") as f, con:
        for r in csv.DictReader(f):
            try:
                ticker, period, metric = r["ticker"].upper().strip(), r["period"].strip(), r["metric"].lower().strip()
                asof = r["asof_date"].strip()
                asof_ts = int(float(asof)) if asof.isdigit() else int(__import__("datetime").datetime.fromisoformat(asof).timestamp())
                val = float(r["consensus"])
                disp = float(r["dispersion"]) if r.get("dispersion") else None
                na = int(r["n_analysts"]) if r.get("n_analysts") else None
                source = r.get("source") or "csv"
                con.execute("""INSERT OR REPLACE INTO earnings_consensus
                   (ticker,period,metric,consensus,dispersion,n_analysts,asof_ts,source,created_ts)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                   (ticker,period,metric,val,disp,na,asof_ts,source,int(time.time())))
                n += 1
            except (KeyError, ValueError, TypeError):
                bad += 1
    con.close()
    return {"importados": n, "invalidos": bad}


def add_actual(ticker: str, period: str, metric: str, actual: float,
               released_ts: int, source: str = "manual", report_id: int | None = None):
    con = connect(); init(con)
    with con:
        con.execute("""INSERT OR REPLACE INTO earnings_actual
        (ticker,period,metric,actual,released_ts,source,report_id,created_ts)
        VALUES(?,?,?,?,?,?,?,?)""",
        (ticker.upper(),period,metric.lower(),float(actual),int(released_ts),source,report_id,int(time.time())))
    con.close()


def compute_surprises(ticker: str | None = None) -> dict:
    con = connect(); init(con)
    where, par = ("WHERE a.ticker=?", (ticker.upper(),)) if ticker else ("", ())
    rows = con.execute(f"""SELECT a.* FROM earnings_actual a {where}
                       ORDER BY a.ticker,a.period,a.metric,a.released_ts""", par).fetchall()
    n = unavailable = 0
    with con:
        for a in rows:
            c = con.execute("""SELECT * FROM earnings_consensus
                WHERE ticker=? AND period=? AND metric=? AND asof_ts < ?
                ORDER BY asof_ts DESC LIMIT 1""",
                (a["ticker"],a["period"],a["metric"],a["released_ts"])).fetchone()
            if not c:
                unavailable += 1; continue
            disp = c["dispersion"]
            surprise = ((a["actual"]-c["consensus"])/disp if disp and disp > 0 else None)
            con.execute("""INSERT OR REPLACE INTO earnings_surprises
                (ticker,period,metric,consensus,dispersion,actual,surprise,asof_ts,released_ts,source,validated)
                VALUES(?,?,?,?,?,?,?,?,?,?,0)""",
                (a["ticker"],a["period"],a["metric"],c["consensus"],disp,a["actual"],
                 surprise,c["asof_ts"],a["released_ts"],c["source"]))
            n += 1
    con.close()
    return {"surpresas": n, "sem_consenso_previo": unavailable}


def ticker_payload(ticker: str) -> dict:
    con = connect(); init(con)
    rows = con.execute("""SELECT * FROM earnings_surprises WHERE ticker=?
        ORDER BY released_ts DESC, metric LIMIT 30""", (ticker.upper(),)).fetchall()
    con.close()
    out = [dict(r) for r in rows]
    # Score descritivo: mediana das surpresas normalizadas no ultimo periodo.
    latest = {}
    for r in out:
        latest.setdefault(r["period"], []).append(r)
    resumo = None
    if latest:
        per = next(iter(latest)); vals = [x["surprise"] for x in latest[per] if x["surprise"] is not None]
        resumo = {"period": per, "surpresa_mediana": round(st.median(vals),3) if vals else None,
                  "metricas": len(vals), "validado": False,
                  "nota": "infraestrutura PEAD; exige backtest fora da amostra antes de sinal."}
    return {"surpresas": out, "resumo": resumo}
