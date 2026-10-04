"""Ligacao noticia -> ticker, com filtro de relevancia economica.

Esta etapa e o gargalo de qualidade. A busca "Petrobras" no GDELT traz
materia sobre racismo ambiental: mencao a empresa nao e noticia de mercado.
`relevance` existe para separar os dois, e o agregador ignora relevance baixa.
"""
from __future__ import annotations
import re

from . import config
from .db import connect
from .util import norm

# Vocabulario que indica que o texto fala de MERCADO/EMPRESA, nao so cita o nome.
MARKET_VOCAB = {
    "acao", "acoes", "papel", "papeis", "bolsa", "b3", "ibovespa", "ticker",
    "lucro", "prejuizo", "receita", "ebitda", "margem", "balanco", "resultado",
    "trimestre", "guidance", "projecao", "dividendo", "dividendos", "jcp",
    "proventos", "recompra", "oferta", "follow", "ipo", "debenture",
    "aquisicao", "fusao", "incorporacao", "venda", "desinvestimento",
    "investimento", "capex", "contrato", "concessao", "leilao",
    "upgrade", "downgrade", "recomendacao", "preco-alvo", "target",
    "analista", "analistas", "corretora", "banco", "research",
    "acionista", "acionistas", "conselho", "assembleia", "ceo", "cfo",
    "presidente", "diretoria", "renuncia", "demissao",
    "producao", "reservas", "exportacao", "importacao", "demanda", "oferta",
    "multa", "cade", "cvm", "aneel", "anp", "anatel", "regulador", "liminar",
    "greve", "paralisacao", "acidente", "rompimento", "vazamento",
    "rating", "divida", "alavancagem", "caixa", "fluxo",
    # ingles
    "shares", "stock", "earnings", "revenue", "profit", "loss", "guidance",
    "dividend", "merger", "acquisition", "upgrade", "downgrade", "rating",
}

# Temas que quase sempre NAO movem o papel, mesmo citando a empresa.
NOISE_VOCAB = {
    "futebol", "patrocinio", "carnaval", "novela", "celebridade", "show",
    "campeonato", "atleta", "filme", "serie", "receita culinaria",
    "horoscopo", "sorteio", "concurso cultural",
}


# Aliases que coincidem com palavra comum do portugues. "VALE" casa com "vale a
# pena"; "B3" casa com qualquer coisa. Barrados como alias em minuscula -- o
# codigo do papel segue valendo, mas so com caixa alta (ver CODE_RE abaixo).
AMBIGUOUS = {"vale", "b3", "weg", "oi", "gol", "mover", "ambev brasil"}

# Codigo de papel da B3: 4 letras + 1-2 digitos. Casa SENSIVEL A CAIXA no texto
# cru, senao "vale3" dentro de uma url ou "petr4" em qualquer lixo gera mencao.
CODE_RE = re.compile(r"^[A-Z]{4}\d{1,2}$")


def _alias_patterns() -> dict[str, list[tuple[str, re.Pattern, bool]]]:
    """Compila um regex por alias. O 3o campo diz se e sensivel a caixa."""
    pats: dict[str, list[tuple[str, re.Pattern, bool]]] = {}
    for tkr, meta in config.tickers().items():
        lst = []
        for alias in list(meta.get("aliases", [])) + [meta.get("name", "")]:
            raw = (alias or "").strip()
            if CODE_RE.match(raw):                    # PETR4, VALE3, PBR...
                lst.append((raw, re.compile(rf"(?<![A-Za-z0-9]){raw}(?![A-Za-z0-9])"), True))
                continue
            a = norm(raw)
            if len(a) < 3 or a in AMBIGUOUS:
                continue
            lst.append((raw, re.compile(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])"), False))
        pats[tkr] = lst
    return pats


def relevance(text_norm: str, in_title: bool, n_tickers: int) -> float:
    """0..1. Combina: mencao no titulo, densidade de vocabulario de mercado,
    ruido tematico, e diluicao quando a materia fala de muitas empresas."""
    toks = set(text_norm.split())
    hits = len(toks & MARKET_VOCAB)
    noise = len(toks & NOISE_VOCAB)

    r = 0.20
    r += 0.35 if in_title else 0.0
    r += min(hits, 6) * 0.09          # saturacao em 6 termos
    r -= noise * 0.30
    if n_tickers > 3:                  # materia panoramica: sinal diluido
        r *= 0.55
    elif n_tickers == 3:
        r *= 0.75
    return max(0.0, min(1.0, r))


def link_all(limit: int = 5000) -> int:
    """Processa artigos ainda sem mencao gravada."""
    pats = _alias_patterns()
    con = connect()
    rows = con.execute("""
        SELECT a.id, a.title, a.body FROM articles a
        WHERE NOT EXISTS (SELECT 1 FROM mentions m WHERE m.article_id = a.id)
        ORDER BY a.published_ts DESC LIMIT ?""", (limit,)).fetchall()

    n = 0
    with con:
        for row in rows:
            tn = norm(row["title"])
            bn = norm(row["body"] or "")
            full = f"{tn} {bn}".strip()

            raw_title = row["title"] or ""
            raw_body = (row["body"] or "")[:2000]

            found = []
            for tkr, plist in pats.items():
                for alias, pat, cased in plist:
                    hay_t, hay_b = (raw_title, raw_body) if cased else (tn, bn)
                    if pat.search(hay_t):
                        found.append((tkr, alias, True)); break
                    if hay_b and pat.search(hay_b):
                        found.append((tkr, alias, False)); break

            if not found:
                # grava sentinela para nao reprocessar eternamente
                con.execute("INSERT OR IGNORE INTO mentions(article_id,ticker,relevance,matched_alias) VALUES (?,?,?,?)",
                            (row["id"], "__none__", 0.0, None))
                continue

            for tkr, alias, in_title in found:
                rel = relevance(full, in_title, len(found))
                con.execute("INSERT OR IGNORE INTO mentions(article_id,ticker,relevance,matched_alias) VALUES (?,?,?,?)",
                            (row["id"], tkr, rel, alias))
                n += 1
    con.close()
    return n
