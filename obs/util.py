"""Utilitarios: HTTP, normalizacao de texto, tempo."""
from __future__ import annotations
import datetime as dt
import re
import time
import unicodedata

import requests

UA = "observatorio-acoes/0.1 (pesquisa academica)"
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = UA


def http_get(url: str, *, timeout: int = 25, tries: int = 3, **kw) -> requests.Response | None:
    """GET com backoff. Devolve None em vez de levantar: ingestao nao deve morrer
    por causa de uma fonte fora do ar."""
    for i in range(tries):
        try:
            r = _SESSION.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                # Backoff largo: o GDELT pede 5s entre chamadas, e um backoff
                # de 1-2s so queima a tentativa seguinte sem sair do throttle.
                time.sleep(6 * (i + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(2 ** i)
    return None


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """Normaliza para matching: minuscula, sem acento, pontuacao -> espaco."""
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9%\+\-\.\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> list[str]:
    return norm(s).split()


def now_ts() -> int:
    return int(time.time())


def parse_gdelt_ts(s: str) -> int:
    """'20260101T123000Z' -> epoch."""
    return int(dt.datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).timestamp())


def iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def date_str(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
