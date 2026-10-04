"""Peso de veiculo aprendido dos dados -- a substituicao do SimilarWeb.

POR QUE NAO TRAFEGO
    O ranking do SimilarWeb mede audiencia. O que importa aqui e outra coisa:
    o veiculo CHEGA PRIMEIRO? Um portal gigante que republica a materia da
    agencia tres horas depois tem trafego alto e valor preditivo zero.

DUAS METRICAS, NENHUMA PRECISA DE RETORNO
    furo (scoop rate) -- em que fracao dos clusters em que o veiculo aparece
        ele foi o PRIMEIRO a publicar. Mede lideranca editorial.
    dianteira (lead time) -- quantos minutos, na mediana, ele publica antes da
        mediana do cluster. Mede o tamanho da vantagem.

    Ambas saem so do fluxo de noticias. Isso importa: o peso por retorno
    realizado exige meses de historico casado com preco; estes dois comecam a
    funcionar na primeira semana.

ENCOLHIMENTO
    Um dominio com 2 artigos e 1 furo tem furo=50%, o que nao significa nada.
    O peso encolhe para a media global conforme a evidencia, pelo mesmo
    principio usado no visor de probabilidade.
"""
from __future__ import annotations
import json
import statistics as st

from .config import CONFIG_DIR
from .db import connect

PRIOR_N = 8.0        # artigos equivalentes de prior; abaixo disso o peso e quase a media
W_MIN, W_MAX = 0.15, 1.0


def cluster_stats(min_cluster: int = 2, window_days: int = 120) -> dict[str, dict]:
    """Por dominio: quantas vezes apareceu, quantas foi primeiro, dianteira mediana.

    So conta clusters com >= `min_cluster` artigos: num cluster de um artigo so
    todo mundo e 'primeiro', o que premiaria quem ninguem mais cobre.
    """
    con = connect()
    rows = con.execute("""
        SELECT a.cluster_id cid, a.domain, a.published_ts ts
        FROM articles a
        WHERE a.cluster_id IS NOT NULL AND a.domain IS NOT NULL
          AND a.published_ts > (SELECT COALESCE(MAX(published_ts),0) FROM articles) - ?
        ORDER BY a.cluster_id, a.published_ts""", (window_days * 86400,)).fetchall()
    con.close()

    clusters: dict[int, list[tuple[str, int]]] = {}
    for r in rows:
        clusters.setdefault(r["cid"], []).append((r["domain"], r["ts"]))

    agg: dict[str, dict] = {}
    for _cid, items in clusters.items():
        if len(items) < min_cluster:
            continue
        items.sort(key=lambda t: t[1])
        first_ts = items[0][1]
        med_ts = st.median(t for _d, t in items)
        seen = set()
        for dom, ts in items:
            if dom in seen:            # um dominio conta uma vez por cluster
                continue
            seen.add(dom)
            a = agg.setdefault(dom, {"n": 0, "furos": 0, "leads": []})
            a["n"] += 1
            if ts == first_ts:
                a["furos"] += 1
            a["leads"].append((med_ts - ts) / 60.0)    # minutos antes da mediana
    return agg


def fit(min_cluster: int = 2, window_days: int = 120) -> dict:
    agg = cluster_stats(min_cluster, window_days)
    if not agg:
        return {"ok": False, "motivo": "nenhum cluster com 2+ artigos ainda",
                "pesos": {}}

    total_n = sum(a["n"] for a in agg.values())
    total_furos = sum(a["furos"] for a in agg.values())
    furo_global = total_furos / total_n if total_n else 0.0

    pesos, detalhe = {}, {}
    for dom, a in sorted(agg.items()):
        # encolhimento do furo para a media global por evidencia
        furo = (a["furos"] + PRIOR_N * furo_global) / (a["n"] + PRIOR_N)
        lead = st.median(a["leads"]) if a["leads"] else 0.0
        # peso = furo relativo a media, limitado; dianteira entra como bonus suave
        rel = furo / furo_global if furo_global > 0 else 1.0
        bonus = 1.0 + max(-0.3, min(0.3, lead / 180.0))    # +-30% em +-3h
        w = max(W_MIN, min(W_MAX, 0.45 * rel * bonus))
        pesos[dom] = round(w, 4)
        detalhe[dom] = {"n": a["n"], "furos": a["furos"],
                        "furo_bruto": round(a["furos"] / a["n"], 3),
                        "furo_encolhido": round(furo, 3),
                        "dianteira_min": round(lead, 1), "peso": pesos[dom]}
    return {"ok": True, "furo_global": round(furo_global, 3),
            "clusters_usados": total_n, "pesos": pesos, "detalhe": detalhe}


def persist(res: dict, path: str = "sources_learned.json") -> str:
    """Grava separado do sources.yml escrito a mao, para dar para comparar."""
    p = CONFIG_DIR / path
    p.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)


def load_weights(path: str = "sources_learned.json") -> dict[str, float]:
    p = CONFIG_DIR / path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("pesos", {})
    except (ValueError, OSError):
        return {}
