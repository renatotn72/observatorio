"""Features de ATENCAO e propagacao -- a psicologia do TCC virando numero.

A OBJECAO QUE ORIGINOU ESTE MODULO (e ela esta certa)
    "Republicacao demonstra que um jornal acreditou que outras pessoas
     gostariam, ou seja, mede o interesse. A popularidade mede o grau de
     espalhamento da noticia."

Correto, e o sistema confundia duas coisas diferentes:

    NOVIDADE   responde "esta informacao e nova para o mercado?"
               -> serve a DIRECAO, porque preco reage a surpresa.
               Ja existia: dedupe.novelty, 1/(1+rank)^0.5.

    ATENCAO    responde "quanto interesse isso despertou?"
               -> serve a MAGNITUDE (agitacao), porque atencao traz
               participante, volume e amplitude -- sem dizer o lado.
               NAO existia. E este modulo.

As duas nao se contradizem: a 20a copia e informacao velha (novidade baixa) e
ao mesmo tempo evidencia de que vinte redacoes julgaram o assunto digno de
publicar (atencao alta). Uma entra na direcao, a outra na agitacao.

A DISTINCAO QUE FAZ O NUMERO PRESTAR
Dez copias do mesmo veiculo nao sao dez votos: sao um veiculo. Por isso
`fontes_efetivas` usa o numero de Hill (exp da entropia dos dominios) em vez
de contar linhas -- dez copias de um dominio dao ~1, dez dominios distintos
dao ~10. E `razao_repeticao` isola exatamente a parte que e copia.

NADA AQUI E SINAL ATE SER MEDIDO. O modulo produz features; quem decide se
elas valem e scripts/atencao_test.py, com a mesma regua do resto do projeto.
"""
from __future__ import annotations
import math
from collections import Counter

from .util import norm

# Lexico de EXCITACAO, nao de polaridade. Mede ameaca, perda, incerteza e
# urgencia -- o que a psicologia associa a reacao intensa, dos dois lados.
# Proposital: "recorde" e "disparou" sao positivos e excitantes; polaridade
# quem mede e score.py. Aqui o que conta e a intensidade.
MEDO = {
    "fraude": 1.0, "rombo": .95, "falencia": 1.0, "recuperacao judicial": 1.0,
    "colapso": .9, "despenca": .85, "derrete": .85, "tombo": .8, "panico": 1.0,
    "crise": .8, "risco": .55, "ameaca": .7, "alerta": .6, "investigacao": .75,
    "denuncia": .75, "escandalo": .9, "vazamento": .7, "rompimento": .85,
    "acidente": .8, "morte": .8, "greve": .65, "paralisacao": .65,
    "default": .9, "calote": .95, "inadimplencia": .7, "multa": .6,
    "corte": .5, "demissao": .6, "fechamento": .55, "suspensao": .6,
    "incerteza": .6, "indefinicao": .5, "impasse": .55, "tensao": .6,
    "urgente": .7, "imediato": .5, "emergencia": .85, "inesperado": .7,
    "surpresa": .6, "reviravolta": .7, "disparou": .7, "dispara": .7,
    "recorde": .6, "historico": .5, "sem precedentes": .9,
    # ingles, porque Bloomberg/FT/CNBC entram no pool
    "fraud": 1.0, "collapse": .9, "plunge": .85, "crash": 1.0, "panic": 1.0,
    "crisis": .8, "risk": .55, "probe": .75, "lawsuit": .6, "default": .9,
    "bankruptcy": 1.0, "strike": .65, "emergency": .85, "surge": .7,
    "soars": .7, "record": .6, "unprecedented": .9, "warning": .65,
}
JANELA_CASCATA_H = 2.0       # "primeiras horas" da propagacao


def fontes_efetivas(dominios: list[str]) -> float:
    """Numero efetivo de fontes independentes (numero de Hill, exp-entropia).

    Dez linhas de um dominio -> ~1.0. Dez dominios distintos -> ~10.0.
    E isto, nao a contagem bruta, que traduz "varias redacoes acharam
    relevante" sem deixar o replicador automatico inflar o numero.
    """
    if not dominios:
        return 0.0
    cont = Counter(dominios)
    n = sum(cont.values())
    h = -sum((c / n) * math.log(c / n) for c in cont.values())
    return math.exp(h)


def medo(texto: str) -> float:
    """Intensidade emocional 0..1. Nao e polaridade: mede excitacao."""
    t = norm(texto or "")
    if not t:
        return 0.0
    total = 0.0
    for termo, peso in MEDO.items():
        if termo in t:
            total += peso
    # satura: a terceira palavra de medo acrescenta menos que a primeira
    return 1.0 - math.exp(-total / 1.5)


def features_cluster(con, article_id: int, asof_ts: int | None = None) -> dict:
    """Features de atencao do cluster a que o artigo pertence.

    TUDO EX-ANTE: so considera artigos com published_ts <= asof_ts. Sem esse
    corte a feature enxergaria a repercussao que so veio DEPOIS do fechamento,
    que e a forma classica de vazar futuro em dado de noticia.
    """
    row = con.execute(
        "SELECT cluster_id, published_ts, domain, title FROM articles WHERE id=?",
        (article_id,)).fetchone()
    if row is None:
        return _vazio()
    asof = asof_ts if asof_ts is not None else row["published_ts"]
    if row["cluster_id"] is None:
        return {**_vazio(), "medo": medo(row["title"]),
                "fontes_efetivas": 1.0, "n_copias": 1}

    irmaos = con.execute(
        "SELECT domain, published_ts, title FROM articles "
        "WHERE cluster_id=? AND published_ts <= ? ORDER BY published_ts",
        (row["cluster_id"], asof)).fetchall()
    if not irmaos:
        return _vazio()

    doms = [r["domain"] or "" for r in irmaos]
    t0 = irmaos[0]["published_ts"]
    efetivas = fontes_efetivas(doms)
    cedo = [r for r in irmaos
            if (r["published_ts"] - t0) <= JANELA_CASCATA_H * 3600]
    return {
        # quantas redacoes DISTINTAS pegaram o assunto nas primeiras horas:
        # a medida de "varios acharam que interessaria", sem contar copia
        "velocidade_cascata": fontes_efetivas([r["domain"] or "" for r in cedo]),
        "fontes_efetivas": efetivas,
        "n_copias": len(irmaos),
        # 1.0 = toda a contagem e copia; 0.0 = toda publicacao e fonte nova
        "razao_repeticao": 1.0 - (efetivas / len(irmaos)) if irmaos else 0.0,
        "horas_ate_agora": max(0.0, (asof - t0) / 3600.0),
        "medo": max(medo(r["title"]) for r in irmaos),
    }


def _vazio() -> dict:
    return {"velocidade_cascata": 0.0, "fontes_efetivas": 0.0, "n_copias": 0,
            "razao_repeticao": 0.0, "horas_ate_agora": 0.0, "medo": 0.0}


def surto(con, ticker: str, asof_ts: int, janela_h: float = 24.0,
          base_dias: int = 30) -> float:
    """attention_burst: artigos/hora do papel agora contra a propria media.

    Relativo ao papel, nao absoluto: 5 materias e surto para a SUZB3 e rotina
    para a PETR4 -- mesma razao pela qual a agitacao usa limiar por papel.
    """
    jan = con.execute(
        "SELECT COUNT(*) FROM mentions m JOIN articles a ON a.id=m.article_id "
        "WHERE m.ticker=? AND a.published_ts <= ? AND a.published_ts > ?",
        (ticker, asof_ts, asof_ts - int(janela_h * 3600))).fetchone()[0]
    base = con.execute(
        "SELECT COUNT(*) FROM mentions m JOIN articles a ON a.id=m.article_id "
        "WHERE m.ticker=? AND a.published_ts <= ? AND a.published_ts > ?",
        (ticker, asof_ts, asof_ts - base_dias * 86400)).fetchone()[0]
    taxa_base = base / (base_dias * 24.0)
    taxa_jan = jan / janela_h
    if taxa_base <= 0:
        return 1.0 if taxa_jan > 0 else 0.0
    return taxa_jan / taxa_base


def painel_atencao(con, ticker: str, asof_ts: int, window_h: int = 36) -> dict:
    """Agrega as features de atencao das noticias vivas do papel.

    Devolve o que a cabeca de AGITACAO deve consumir. Nao toca na direcao:
    atencao nao diz lado.
    """
    rows = con.execute(
        "SELECT a.id FROM mentions m JOIN articles a ON a.id=m.article_id "
        "WHERE m.ticker=? AND a.published_ts <= ? AND a.published_ts > ?",
        (ticker, asof_ts, asof_ts - window_h * 3600)).fetchall()
    if not rows:
        return {**_vazio(), "surto": surto(con, ticker, asof_ts), "n": 0}
    fs = [features_cluster(con, r["id"], asof_ts) for r in rows]
    return {
        "velocidade_cascata": max(f["velocidade_cascata"] for f in fs),
        "fontes_efetivas": max(f["fontes_efetivas"] for f in fs),
        "razao_repeticao": max(f["razao_repeticao"] for f in fs),
        "medo": max(f["medo"] for f in fs),
        "n_copias": sum(f["n_copias"] for f in fs),
        "horas_ate_agora": min(f["horas_ate_agora"] for f in fs),
        "surto": surto(con, ticker, asof_ts),
        "n": len(fs),
    }
