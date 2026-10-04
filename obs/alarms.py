"""Motor de alarmes.

Desenho deliberado: NAO dispara por P(alta) absoluto. Se a taxa-base de alta
anormal do papel e 33%, um visor em 38% nao e noticia -- e ruido. O gatilho e
VANTAGEM sobre a taxa-base (`edge`), com quatro portas:

  1. edge     >= min_edge
  2. n_eff    >= min_n_eff          (evidencia suficiente)
  3. novidade                        (ao menos 1 primeira reportagem)
  4. calibrado                       (sem calibracao, nao ha probabilidade)
  + cooldown por papel, para nao metralhar a mesma historia
"""
from __future__ import annotations

from . import config
from .db import connect
from .util import iso, now_ts


def _rule_for(ticker: str, cfg: dict) -> dict | None:
    defaults = dict(cfg.get("defaults", {}))
    specific = None
    wildcard = None
    for r in cfg.get("rules", []):
        if r.get("ticker") == ticker:
            specific = r
        elif r.get("ticker") == "*":
            wildcard = r
    rule = specific or wildcard
    if rule is None:
        return None
    merged = defaults
    merged.update({k: v for k, v in rule.items() if k != "ticker"})
    merged["ticker"] = ticker
    return merged


def _in_cooldown(con, ticker: str, direction: str, minutes: int) -> bool:
    row = con.execute(
        "SELECT MAX(ts) t FROM alarm_events WHERE ticker=? AND direction=?",
        (ticker, direction)).fetchone()
    return bool(row and row["t"] and now_ts() - row["t"] < minutes * 60)


def _has_novelty(con, ticker: str, scorer: str, window_h: int = 36,
                 thr: float = 0.95) -> bool:
    row = con.execute("""
        SELECT COUNT(*) c FROM scores sc JOIN articles a ON a.id=sc.article_id
        WHERE sc.ticker=? AND sc.scorer=? AND sc.novelty >= ?
          AND a.published_ts > ?""",
        (ticker, scorer, thr, now_ts() - window_h * 3600)).fetchone()
    return bool(row and row["c"] > 0)


def evaluate(signals: list[dict], scorer: str = "lexicon") -> list[dict]:
    cfg = config.alarms()
    con = connect()
    fired = []

    for sig in signals:
        tkr = sig["ticker"]
        rule = _rule_for(tkr, cfg)
        if rule is None:
            continue

        if rule.get("require_calibrated", True) and not sig.get("calibrated"):
            continue
        if sig["n_eff"] < float(rule.get("min_n_eff", 2.0)):
            continue
        if rule.get("require_novelty", True) and not _has_novelty(con, tkr, scorer):
            continue

        want = rule.get("direction", "both")
        checks = []
        if want in ("up", "both") and sig.get("p_up") is not None:
            checks.append(("up", sig["p_up"], sig["base_up"]))
        if want in ("down", "both") and sig.get("p_down") is not None:
            checks.append(("down", sig["p_down"], sig["base_down"]))

        for direction, p, base in checks:
            edge = p - base
            if edge < float(rule.get("min_edge", 0.12)):
                continue
            if _in_cooldown(con, tkr, direction, int(rule.get("cooldown_min", 90))):
                continue

            label = "ALTA" if direction == "up" else "QUEDA"
            top = sig["items"][0]["title"][:110] if sig.get("items") else "(sem manchete)"
            # A diferenca entre duas probabilidades e em PONTOS percentuais.
            # Escrever "+25%" sugere aumento relativo e ja confundiu na leitura.
            msg = (f"[{label}] {tkr}  P={p:.0%} vs base {base:.0%} "
                   f"(vantagem {100*edge:+.0f} p.p.)  n_eff={sig['n_eff']:.1f} "
                   f"z={sig['z']:+.2f}  | {top}")
            with con:
                con.execute("""INSERT INTO alarm_events
                    (ts,ticker,direction,p,base,edge,n_eff,message,delivered)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (now_ts(), tkr, direction, p, base, edge, sig["n_eff"], msg, None))
            fired.append({"ticker": tkr, "direction": direction, "p": p, "base": base,
                          "edge": edge, "message": msg, "ts": now_ts(),
                          "channels": rule.get("channels", ["console"])})
    con.close()
    return fired
