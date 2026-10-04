"""Agrupamento de quase-duplicatas via SimHash -> gera NOVIDADE.

Esta e a ideia do TCC original ("quanto mais noticias quase identicas se
aglomeram, mais popular ela e") com a leitura corrigida: o cluster mede
POPULARIDADE/atencao, e a POSICAO no cluster mede NOVIDADE. Preco reage a
surpresa, logo a primeira reportagem vale mais que a 20a repercussao.
"""
from __future__ import annotations
import hashlib
import re

from .db import connect
from .util import strip_accents, tokens

# Para titulos curtos o SimHash e ruidoso (uma palavra trocada ja move ~14 bits
# de 63). Jaccard sobre conjunto de tokens de conteudo decide melhor; o SimHash
# fica guardado para quando a base crescer e valer a pena LSH por bandas.
JACCARD_MIN = 0.55
HAMMING_MAX = 12

STOP = {
    "a","o","as","os","de","do","da","dos","das","e","em","no","na","nos","nas",
    "um","uma","para","por","com","que","ao","aos","se","sobre","apos","ate",
    "the","of","to","in","on","for","and","a","an","is","at","by","with","from",
}


def content_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in STOP and len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Numero + ordem de grandeza ("R$ 3,8 bilhoes", "3,8 bi") vira uma impressao
# digital. Duas materias sobre o mesmo papel citando a mesma cifra incomum sao
# quase sempre o mesmo anuncio -- e o Jaccard sozinho nao as une, porque uma diz
# "aprova proventos" e a outra "pagara juros sobre o capital proprio".
MAG = {"mil": 1e3, "milhao": 1e6, "milhoes": 1e6, "mi": 1e6,
       "bilhao": 1e9, "bilhoes": 1e9, "bi": 1e9, "trilhao": 1e12, "tri": 1e12,
       "million": 1e6, "billion": 1e9}
_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(MAG) + r")\b")
JACCARD_WITH_FIGURE = 0.25     # com cifra em comum, exige-se bem menos texto igual


def figures(text: str) -> set[str]:
    """Cifras normalizadas, ex.: '3,8 bilhoes' e '3.8 bi' -> o mesmo valor.

    Usa minuscula-sem-acento, NAO `norm()`: norm() transforma pontuacao em
    espaco, entao "3,8 bi" vira "3 8 bi" e o regex captura apenas o "8" --
    o que uniria qualquer noticia com "8 bi" a qualquer outra com "3,8 bi".
    """
    low = strip_accents(text or "").lower()
    out = set()
    for num, mag in _NUM_RE.findall(low):
        try:
            v = float(num.replace(",", ".")) * MAG[mag]
        except ValueError:
            continue
        if v >= 1e6:                      # cifras pequenas nao identificam nada
            out.add(f"{v:.4g}")
    return out


def same_story(ta: set[str], tb: set[str], sa: int, sb: int,
               fa: set[str] | None = None, fb: set[str] | None = None) -> bool:
    j = jaccard(ta, tb)
    if j >= JACCARD_MIN or hamming(sa, sb) <= HAMMING_MAX:
        return True
    if fa and fb and (fa & fb) and j >= JACCARD_WITH_FIGURE:
        return True
    return False


# 63 bits, nao 64: o INTEGER do SQLite e signed int64, e um simhash de 64
# bits estoura o limite positivo.
def simhash(text: str, bits: int = 63) -> int:
    toks = tokens(text)
    shingles = [" ".join(toks[i:i + 3]) for i in range(max(1, len(toks) - 2))] or toks
    if not shingles:
        return 0
    v = [0] * bits
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def cluster(window_hours: int = 48, ate_ts: int | None = None,
            desde_ts: int | None = None) -> int:
    """Atribui cluster_id. Compara so dentro da janela: O(n^2) na janela, nao no banco.

    `ate_ts` desloca a janela para tras no tempo, o que e o que permite agrupar
    historico. Sem isso a janela e sempre ancorada no artigo MAIS RECENTE do
    banco -- ver cluster_historico() para o porque isso importa.
    """
    con = connect()
    if ate_ts is None:
        fim = con.execute(
            "SELECT COALESCE(MAX(published_ts),0) FROM articles").fetchone()[0]
    else:
        fim = ate_ts
    ini = desde_ts if desde_ts is not None else fim - window_hours * 3600
    rows = con.execute("""
        SELECT id, title, body, simhash, cluster_id, published_ts FROM articles
        WHERE published_ts > ? AND published_ts <= ?
        ORDER BY published_ts ASC""", (ini, fim)).fetchall()

    recs = []
    with con:
        for r in rows:
            sh = r["simhash"]
            if sh is None:
                sh = simhash(f"{r['title']} {(r['body'] or '')[:400]}")
                con.execute("UPDATE articles SET simhash=? WHERE id=?", (sh, r["id"]))
            recs.append({"id": r["id"], "sh": sh, "cid": r["cluster_id"],
                         "tk": content_tokens(r["title"]),
                         "fg": figures(r["title"])})

        next_cid = (con.execute("SELECT COALESCE(MAX(cluster_id),0) FROM articles").fetchone()[0]) + 1
        for i, a in enumerate(recs):
            if a["cid"] is not None:
                continue
            cid = None
            for b in recs[:i]:
                if b["cid"] is not None and same_story(a["tk"], b["tk"], a["sh"],
                                                       b["sh"], a["fg"], b["fg"]):
                    cid = b["cid"]; break
            if cid is None:
                cid = next_cid; next_cid += 1
            a["cid"] = cid
            con.execute("UPDATE articles SET cluster_id=? WHERE id=?", (cid, a["id"]))
    con.close()
    return len(recs)


def novelty(con, article_id: int) -> float:
    """1.0 se e a primeira do cluster; decai ~1/sqrt(rank) depois."""
    row = con.execute("SELECT cluster_id, published_ts FROM articles WHERE id=?",
                      (article_id,)).fetchone()
    if row is None or row["cluster_id"] is None:
        return 1.0
    rank = con.execute(
        "SELECT COUNT(*) FROM articles WHERE cluster_id=? AND published_ts < ?",
        (row["cluster_id"], row["published_ts"])).fetchone()[0]
    return 1.0 / (1.0 + rank) ** 0.5


def cluster_size(con, article_id: int) -> int:
    row = con.execute("SELECT cluster_id FROM articles WHERE id=?", (article_id,)).fetchone()
    if row is None or row["cluster_id"] is None:
        return 1
    return con.execute("SELECT COUNT(*) FROM articles WHERE cluster_id=?",
                       (row["cluster_id"],)).fetchone()[0]


def cluster_historico(window_hours: int = 48, passo_h: int = 24,
                      verbose: bool = True) -> int:
    """Agrupa o banco INTEIRO, caminhando em janelas sobrepostas.

    POR QUE PRECISA EXISTIR
    `cluster()` ancora a janela no artigo MAIS RECENTE. Isso basta para a
    operacao do dia, mas deixa todo o historico sem `cluster_id` -- e
    `novelty()` devolve 1.0 justamente quando `cluster_id` e NULL. Resultado:
    num backfill de um ano, TODA materia entraria como "primeira reportagem",
    com peso maximo, inclusive a 20a repeticao da mesma noticia. O sinal
    historico sairia inflado e a medicao em cima dele seria lixo.

    A sobreposicao (passo < janela) existe para que duplicata que cai perto da
    borda de uma janela ainda encontre a irma na janela seguinte.
    """
    con = connect()
    lim = con.execute(
        "SELECT MIN(published_ts), MAX(published_ts) FROM articles").fetchone()
    con.close()
    if not lim or lim[0] is None:
        return 0
    ini, fim = int(lim[0]), int(lim[1])
    total, t = 0, ini + window_hours * 3600
    n_jan = 0
    while t <= fim + passo_h * 3600:
        total += cluster(window_hours=window_hours, ate_ts=t)
        n_jan += 1
        t += passo_h * 3600
    if verbose:
        import datetime as _dt
        print(f"  {n_jan} janelas de {window_hours}h, passo {passo_h}h, "
              f"{_dt.date.fromtimestamp(ini)} a {_dt.date.fromtimestamp(fim)}")
    return total
