"""Barras intradiarias: o horizonte de MINUTOS e HORAS.

POR QUE ISTO EXISTE
O teste diario mostrou o IC do modelo estrutural caindo de 0,157
(contemporaneo) para 0,021 (D+1) -- colapso de 7x. Se a informacao some em um
dia, e porque a reacao acontece DENTRO do dia. A pergunta passa a ser onde
dentro do dia, e para responder e preciso barra intradiaria.

O QUE O YAHOO DA DE GRACA (medido em 2026-10-02, PETR4.SA)
    interval=1m    5 dias de historico
    interval=5m    1 mes
    interval=15m   1 mes
    interval=1h    2 anos        <- o unico com amostra utilizavel hoje
Os drivers tem mais barras que as acoes (USDBRL 8.618 contra PETR4 3.473)
porque cambio negocia quase 24h e a B3 abre ~7h por dia. Alinhar exige cortar
pelas horas de pregao, senao o 'retorno da hora anterior' do dolar pode vir da
madrugada e o da acao de ontem.

A JANELA CURTA E O PONTO
1m so retem 5 dias. Isso nao e limitacao de agora, e permanente: para medir
reacao de minutos e preciso COLETAR TODO DIA e acumular. Hora da para testar
ja; minuto so depois de semanas de coleta.
"""
from __future__ import annotations
import datetime as dt

from . import tempo
from .db import connect
from .util import http_get

YF = "https://query1.finance.yahoo.com/v8/finance/chart/"
YF_HEAD = {"User-Agent": "Mozilla/5.0 (compatible; observatorio-academico)"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS intraday (
  simbolo TEXT NOT NULL, intervalo TEXT NOT NULL, ts INTEGER NOT NULL,
  close REAL NOT NULL,
  -- volume DA BARRA, ja diferenciado quando a fonte entrega acumulado do dia
  -- (e o caso da UOL; ver obs/uol.py). origem = procedencia do ponto.
  volume REAL, origem TEXT,
  PRIMARY KEY (simbolo, intervalo, ts)
);
"""
# Pregao da B3 em horario de Brasilia. Fora disto a barra da acao nao existe,
# mas a do dolar existe -- e e por isso que o corte importa.
B3_ABRE_H = tempo.B3_ABRE_H
B3_FECHA_H = tempo.B3_FECHA_H


def init(con=None):
    own = con is None
    con = con or connect()
    with con:
        con.executescript(SCHEMA)
    if own:
        con.close()


def fetch(simbolo: str, intervalo: str = "1h", rng: str = "2y") -> list[tuple[int, float]]:
    r = http_get(YF + simbolo, params={"range": rng, "interval": intervalo},
                 headers=YF_HEAD, tries=2)
    if r is None:
        return []
    try:
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError, ValueError):
        return []
    return [(int(t), float(c)) for t, c in zip(ts, q) if c]


def sync(simbolos: dict[str, str], intervalo: str = "1h",
         rng: str = "2y", verbose: bool = True) -> int:
    """{nome: simbolo_yahoo} -> grava barras. Devolve quantas linhas."""
    init()
    con = connect()
    total = 0
    for nome, sym in simbolos.items():
        ser = fetch(sym, intervalo, rng)
        if not ser:
            if verbose:
                print(f"  [intraday] {nome}: falhou")
            continue
        with con:
            con.executemany(
                "INSERT OR REPLACE INTO intraday VALUES (?,?,?,?)",
                [(nome, intervalo, t, c) for t, c in ser])
        total += len(ser)
        if verbose:
            print(f"  [intraday] {nome:<9} {len(ser):>6} barras de {intervalo}")
    con.close()
    return total


def series(con, intervalo: str = "1h", so_pregao: bool = True
           ) -> dict[str, dict[int, float]]:
    """{simbolo: {ts: close}}, opcionalmente so dentro do pregao da B3."""
    out: dict[str, dict[int, float]] = {}
    for r in con.execute(
            "SELECT simbolo, ts, close FROM intraday WHERE intervalo=? ORDER BY ts",
            (intervalo,)):
        if so_pregao and not tempo.no_pregao(r["ts"]):
            # Antes: dt.datetime.fromtimestamp(ts).hour -- hora da MAQUINA.
            # Funcionava por acidente (a maquina esta em Sao Paulo) e quebraria
            # em qualquer outro fuso, sem erro, so com barras erradas.
            continue
        out.setdefault(r["simbolo"], {})[r["ts"]] = r["close"]
    return out


def retornos(ser: dict[int, float]) -> dict[int, float]:
    """Retorno de barra para barra. Pula buraco de mais de 4h (fim de pregao).

    Sem essa guarda, o 'retorno' da primeira barra do dia seria o gap de
    abertura inteiro disfarcado de movimento de uma hora -- e o gap tem outra
    natureza, ja medida a parte neste projeto.
    """
    ts = sorted(ser)
    out = {}
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > 4 * 3600:
            continue
        a, b = ser[ts[i - 1]], ser[ts[i]]
        if a:
            out[ts[i]] = b / a - 1.0
    return out


def residual_transversal(rets: dict[str, dict[int, float]]
                         ) -> dict[str, dict[int, float]]:
    """Retorno da acao menos a media transversal da MESMA barra."""
    carimbos = sorted({t for s in rets.values() for t in s})
    out: dict[str, dict[int, float]] = {s: {} for s in rets}
    for t in carimbos:
        dia = [(s, rets[s][t]) for s in rets if t in rets[s]]
        if len(dia) < 3:
            continue
        media = sum(v for _s, v in dia) / len(dia)
        for s, v in dia:
            out[s][t] = v - media
    return out
