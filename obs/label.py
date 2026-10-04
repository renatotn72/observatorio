"""Rotulagem: retorno ANORMAL (CAR) -> classe alta/neutro/queda.

Por que anormal e nao bruto: se voce rotular com retorno bruto, o modelo
aprende a prever o IBOVESPA, nao o efeito da noticia. E por que em multiplos
de sigma e nao em % fixo: +1% na WEGE3 e na MGLU3 nao sao o mesmo evento.
"""
from __future__ import annotations
import statistics as st

from . import config
from .db import connect
from .prices import returns_by_date

K_SIGMA = 0.5        # |CAR| > 0.5*sigma => evento direcional
MIN_SIGMA_OBS = 8    # minimo de retornos para estimar sigma


def abnormal_returns(con) -> dict[str, dict[str, float]]:
    """Retorno anormal por (ticker, data).

    benchmark '__crosssec__': r_i - media_transversal(r) no mesmo dia.
    Caso contrario: r_i - r_benchmark (modelo de mercado com beta=1; para beta
    estimado voce precisa de historico longo, logo de BRAPI_TOKEN)."""
    rets = returns_by_date(con)
    bench = config.watchlist().get("benchmark", "__crosssec__")
    universe = [t for t in config.tickers() if t in rets]

    ab: dict[str, dict[str, float]] = {t: {} for t in universe}
    if bench == "__crosssec__":
        all_dates = sorted({d for t in universe for d in rets[t]})
        for d in all_dates:
            same_day = [rets[t][d] for t in universe if d in rets[t]]
            if len(same_day) < 3:
                continue
            mkt = sum(same_day) / len(same_day)
            for t in universe:
                if d in rets[t]:
                    ab[t][d] = rets[t][d] - mkt
    else:
        bret = rets.get(bench, {})
        for t in universe:
            for d, r in rets[t].items():
                if d in bret:
                    ab[t][d] = r - bret[d]
    return ab


def build(horizon_days: int = 1) -> int:
    """Para cada sinal gravado, olha o retorno anormal FUTURO e rotula.

    O sinal em asof_ts so pode ser casado com retorno de pregao POSTERIOR --
    e a unica defesa contra look-ahead."""
    con = connect()
    ab = abnormal_returns(con)
    horizon = f"{horizon_days}d"

    sig = con.execute("SELECT ticker, asof_ts FROM signals").fetchall()
    n = 0
    with con:
        for s in sig:
            tkr = s["ticker"]
            if tkr not in ab or not ab[tkr]:
                continue
            dates = sorted(ab[tkr])
            from .util import date_str
            d0 = date_str(s["asof_ts"])

            future = [d for d in dates if d > d0]
            if len(future) < horizon_days:
                continue
            car = sum(ab[tkr][d] for d in future[:horizon_days])

            hist = [ab[tkr][d] for d in dates if d <= d0]
            if len(hist) < MIN_SIGMA_OBS:
                continue
            sigma = st.pstdev(hist) * (horizon_days ** 0.5)
            if sigma <= 0:
                continue

            cls = 1 if car > K_SIGMA * sigma else (-1 if car < -K_SIGMA * sigma else 0)
            con.execute(
                "INSERT OR REPLACE INTO labels(ticker,asof_ts,horizon,car,sigma,cls)"
                " VALUES (?,?,?,?,?,?)", (tkr, s["asof_ts"], horizon, car, sigma, cls))
            n += 1
    con.close()
    return n


def base_rates(con, horizon: str = "1d", ticker: str | None = None) -> dict:
    """Taxa-base: com que frequencia este papel sobe/cai anormalmente, SEM
    olhar noticia. E o numero que o visor tem de bater para significar algo."""
    q = "SELECT cls, COUNT(*) c FROM labels WHERE horizon=?"
    args: list = [horizon]
    if ticker:
        q += " AND ticker=?"; args.append(ticker)
    q += " GROUP BY cls"
    rows = con.execute(q, args).fetchall()
    cnt = {r["cls"]: r["c"] for r in rows}
    tot = sum(cnt.values())
    if tot == 0:
        return {"up": 1 / 3, "flat": 1 / 3, "down": 1 / 3, "n": 0}
    return {"up": cnt.get(1, 0) / tot, "flat": cnt.get(0, 0) / tot,
            "down": cnt.get(-1, 0) / tot, "n": tot}
