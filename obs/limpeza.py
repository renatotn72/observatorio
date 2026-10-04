"""Auditoria e limpeza do que contamina investigacao futura.

O QUE E "LIXO" AQUI
Nao e arquivo grande nem tabela cheia. E dado calculado sob uma REGRA QUE
MUDOU e que continua no banco parecendo valido. Esse e o perigoso, porque nao
da erro: entra numa medicao futura misturado com dado bom e desloca o
resultado sem avisar.

Cinco categorias, em ordem de dano:

1. SCORE sob lexico antigo. `score.run` so pontua par (artigo,ticker) que
   AINDA NAO TEM score -- entao mudar PHRASES ou a porta de idioma nao
   recalcula nada. O score errado fica.
2. ARTIGO SEM CLUSTER. `novelty` vale 1.0 quando `cluster_id` e NULL, isto e,
   artigo nao agrupado passa por "primeira reportagem" e entra com peso
   MAXIMO. Nao e dado faltando, e dado ERRADO para cima.
3. SINAL sob regra antiga. Peso do driver, camada setorial, porta de idioma:
   tudo mudou hoje. Sinal gravado antes nao reflete o codigo atual.
4. RUN DE TESTE na fila operacional. Contamina qualquer estatistica de
   duracao e de taxa de erro dos jobs.
5. DRIVER fora do registro. Ja documentado no caso do ETF WOOD: remover do
   codigo nao remove as linhas, e `fit_exposures` continuava lendo.

NADA AQUI APAGA POR PADRAO. `limpar()` roda em simulacao e devolve o que
FARIA; so com `aplicar=True` escreve. Apagar dado de medicao sem o usuario
ver antes seria o oposto do ponto deste modulo.
"""
from __future__ import annotations
import os
import time

from . import config
from .db import connect

PREFIXOS_TESTE = ("teste", "test", "verificacao", "debug")


def auditar() -> dict:
    """So LE. Devolve o diagnostico, sem tocar em nada."""
    con = connect()

    def n(sql, *a):
        try:
            return con.execute(sql, a).fetchone()[0]
        except Exception:                                    # noqa: BLE001
            return 0

    marcas = " OR ".join("lower(trigger) LIKE ?" for _ in PREFIXOS_TESTE)
    args = tuple(f"{p}%" for p in PREFIXOS_TESTE)

    from .drivers import DRIVERS
    fantasmas = [r[0] for r in con.execute(
        "SELECT DISTINCT driver FROM driver_prices").fetchall()
        if r[0] not in DRIVERS]

    out = {
        "scores": n("SELECT COUNT(*) FROM scores"),
        "artigos_sem_cluster": n("SELECT COUNT(*) FROM articles WHERE cluster_id IS NULL"),
        "sinais": n("SELECT COUNT(*) FROM signals"),
        "runs_de_teste": n(f"SELECT COUNT(*) FROM ops_runs WHERE {marcas}", *args),
        "drivers_fantasma": fantasmas,
        "idioma_nao_coberto_com_score": n(
            """SELECT COUNT(*) FROM scores sc JOIN articles a ON a.id=sc.article_id
               WHERE sc.scorer='lexicon'
                 AND lower(COALESCE(a.lang,'')) NOT IN
                     ('portuguese','english','pt','en','pt-br','en-us','en-gb','')"""),
    }
    con.close()
    out["arquivos_vazios"] = _arquivos_vazios()
    return out


def _arquivos_vazios() -> list[str]:
    base = config.ROOT / "data"
    if not base.exists():
        return []
    return [f.name for f in base.iterdir()
            if f.is_file() and f.stat().st_size == 0
            and not f.name.endswith(("-wal", "-shm"))]


def limpar(aplicar: bool = False, dias_log: int = 7) -> dict:
    """Corrige o que foi auditado. SIMULA por padrao.

    Ordem importa: agrupar antes de repontuar, porque `novelty` e lido no
    momento em que o score e gravado.
    """
    feito: dict = {"aplicou": aplicar, "acoes": []}

    def registra(acao, n, detalhe=""):
        feito["acoes"].append({"acao": acao, "n": n, "detalhe": detalhe})

    con = connect()

    # 1. agrupar o que ficou sem cluster (novelty=1.0 indevido)
    sem = con.execute("SELECT COUNT(*) FROM articles WHERE cluster_id IS NULL").fetchone()[0]
    if sem:
        if aplicar:
            from . import dedupe
            con.close()
            n = dedupe.cluster_historico(verbose=False)
            con = connect()
            registra("agrupar artigos sem cluster", n,
                     "novelty=1.0 indevido dava peso MAXIMO a eles")
        else:
            registra("agrupar artigos sem cluster", sem,
                     "novelty=1.0 indevido da peso MAXIMO a eles")

    # 2. repontuar: apaga os scores do lexico para que score.run recalcule
    nsc = con.execute("SELECT COUNT(*) FROM scores WHERE scorer='lexicon'").fetchone()[0]
    if nsc:
        if aplicar:
            with con:
                con.execute("DELETE FROM scores WHERE scorer='lexicon'")
            con.close()
            from . import score
            novos = score.run(scorer="lexicon")
            con = connect()
            registra("repontuar com o lexico atual", novos,
                     "score.run nao recalcula par que ja tem score")
        else:
            registra("repontuar com o lexico atual", nsc,
                     "score.run nao recalcula par que ja tem score")

    # 3. sinais: apaga para recalcular sob as regras atuais
    nsg = con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    if nsg:
        if aplicar:
            with con:
                con.execute("DELETE FROM signals")
            registra("apagar sinais sob regra antiga", nsg,
                     "rode `obs signals` para recalcular")
        else:
            registra("apagar sinais sob regra antiga", nsg,
                     "rode `obs signals` para recalcular")

    # 4. runs de teste
    marcas = " OR ".join("lower(trigger) LIKE ?" for _ in PREFIXOS_TESTE)
    args = tuple(f"{p}%" for p in PREFIXOS_TESTE)
    nrt = con.execute(f"SELECT COUNT(*) FROM ops_runs WHERE {marcas}", args).fetchone()[0]
    if nrt:
        if aplicar:
            with con:
                con.execute(f"DELETE FROM ops_runs WHERE {marcas}", args)
        registra("remover runs de teste da fila", nrt,
                 "contaminam estatistica de duracao e de erro dos jobs")

    # 5. drivers fantasma
    from .drivers import DRIVERS, purge_unregistered
    fant = [r[0] for r in con.execute("SELECT DISTINCT driver FROM driver_prices")
            if r[0] not in DRIVERS]
    if fant:
        if aplicar:
            con.close()
            n = purge_unregistered()
            con = connect()
            registra("purgar drivers fora do registro", n, ", ".join(fant))
        else:
            registra("purgar drivers fora do registro", len(fant), ", ".join(fant))

    con.close()

    # 6. arquivos: so os VAZIOS e os logs velhos. Nunca o banco.
    vazios = _arquivos_vazios()
    if vazios:
        if aplicar:
            for f in vazios:
                try:
                    (config.ROOT / "data" / f).unlink()
                except OSError:
                    pass
        registra("remover arquivos vazios", len(vazios), ", ".join(vazios[:6]))

    base = config.ROOT / "data"
    corte = time.time() - dias_log * 86400
    velhos = [f.name for f in base.iterdir()
              if f.is_file() and f.suffix == ".log" and f.stat().st_mtime < corte]
    if velhos:
        if aplicar:
            for f in velhos:
                try:
                    (base / f).unlink()
                except OSError:
                    pass
        registra(f"remover logs com mais de {dias_log} dias", len(velhos))

    return feito
