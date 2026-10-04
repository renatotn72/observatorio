"""Utilitarios: HTTP, normalizacao de texto, tempo."""
from __future__ import annotations
import datetime as dt
import re
import time
import unicodedata
from html import unescape

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


# Blocos cujo CONTEUDO tambem sai, nao so as tags: script e style guardam
# codigo, e codigo tem palavra que o classificador leria como noticia.
_BLOCOS = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.S | re.I)
_TAGS = re.compile(r"<[^>]{0,2000}>")
_URLS = re.compile(r"https?://\S+")


def sem_html(s: str | None) -> str:
    """Texto legivel a partir do corpo cru do feed.

    MEDIDO em 2026-10-04 sobre os 684 corpos distintos do banco:
        73%  contem tag HTML; 73% COMECAM com tag (quase sempre <img src=...>)
        17   corpos (2%) mudam de orientacao temporal ao serem limpos
        +9%  de texto real na janela de 600 chars que `score_lexicon` le
             (mediana 352 -> 384 caracteres uteis)
        3/400 corpos tinham FALSO PASSADO por entidade numerica: `&#8230;`
             (reticencias) normaliza para "8230", e "em &#8230;" vira
             "em 8230", que casa com o padrao `em \d{4}` de obs/evento.py.

    O QUE ISTO *NAO* CONSERTA, para nao prometer demais: ano dentro de URL de
    imagem ("/bs/2025/") NAO criava PASSADO falso -- o padrao exige "em "
    imediatamente antes do ano. Verificado: `em \d{4}` casa 8 vezes no corpo
    sujo e 9 no limpo.

    O ganho principal e simples: markup nao e conteudo. Token como "glbimg",
    "auth" ou "jpg" entra no fluxo de tokens do lexico e na janela de contexto
    do LLM sem carregar fato nenhum, e a tag inicial empurra texto real para
    fora do truncamento.

    A LIMPEZA E NA LEITURA, nao no armazenamento. O corpo cru fica no banco de
    proposito: ele e o dado de origem, e refazer a ingestao de 10 mil artigos
    para reescrever texto seria trocar o original por uma versao processada
    sob a regra de hoje -- exatamente o que obs/limpeza.py existe para evitar.
    """
    if not s:
        return ""
    s = _BLOCOS.sub(" ", s)
    s = _TAGS.sub(" ", s)
    s = _URLS.sub(" ", s)          # URL remanescente em texto solto
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


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
