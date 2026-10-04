"""Fuso horario: fonte unica da verdade. Nada de hora local implicita.

POR QUE ESTE MODULO EXISTE
Um defeito medido em 2026-10-02: o feed do Valor carimba `-0000`, que em RFC
2822 significa "fuso desconhecido". O `parsedate_to_datetime` devolve datetime
INGENUO, e `.timestamp()` num ingenuo assume hora LOCAL -- nesta maquina, -03.
Todo artigo do veiculo que mais gera mencao ficou TRES HORAS adiantado, com
carimbo no futuro, sem nunca dar erro.

A LICAO: hora sem fuso explicito e bomba-relogio. Funciona enquanto a maquina
estiver no fuso certo e explode quando muda -- ou quando a fonte muda o
formato dela. Entao aqui vale uma regra so:

    NO BANCO, TUDO E EPOCH UTC. Fuso so aparece na BORDA: ao ler uma fonte
    externa (que pode vir em qualquer fuso) e ao exibir para o usuario
    (que pensa em horario de Brasilia).

O QUE NAO FOI AFETADO PELO DEFEITO -- vale registrar para nao se refazer
medicao a toa. Usam SO preco, nunca carimbo de noticia:
    cabeca de agitacao (AUC 0,590), teste de direcao por drivers (0,4948),
    temas contra proxy (IC 0,157), testes de 5min/1h, beta de baixa,
    surpresa macro, tabela de confiabilidade.
Dependiam do carimbo: estudo de evento de noticia (que estava em n=26 e nao
concluia), agregacao do sinal e os rotulos -- estes foram refeitos.
"""
from __future__ import annotations
import datetime as dt
import time
from zoneinfo import ZoneInfo

# O fuso do usuario e do mercado que o projeto observa.
SP = ZoneInfo("America/Sao_Paulo")
UTC = dt.timezone.utc

# ATENCAO AO HISTORICO: o Brasil tinha horario de verao ate 2019. Antes disso
# o offset de Sao Paulo oscilava entre -02 e -03. Por isso nunca se usa um
# numero fixo de horas aqui -- a ZoneInfo sabe a data de cada mudanca, uma
# constante `-3` nao sabe. Dado diario do projeto vai a 2016 e seria afetado
# se fosse convertido com offset fixo.

# Pregao regular da B3 em horario de SAO PAULO, nao da maquina.
# MEDIDO nas barras do Yahoo: PETR4 tem barra de 1h nas horas 10..17 BRT e de
# 1m nas horas 10..16. O corte em [10, 17) descarta 2 de 3.472 barras (0,1%).
B3_ABRE_H = 10
B3_FECHA_H = 17


def agora_ts() -> int:
    return int(time.time())


def de_epoch(ts: int | float, tz: dt.tzinfo = UTC) -> dt.datetime:
    """Epoch -> datetime COM fuso. Nunca use datetime.fromtimestamp sem tz."""
    return dt.datetime.fromtimestamp(ts, tz)


def para_epoch(d: dt.datetime, supor: dt.tzinfo = UTC) -> int:
    """datetime -> epoch. Ingenuo e tratado como `supor`, nunca como local.

    `supor=UTC` e o padrao de propósito: fonte que nao declara fuso quase
    sempre publica em UTC ou em `-0000`, e assumir local foi exatamente o
    erro que custou 3h em 329 artigos.
    """
    if d.tzinfo is None:
        d = d.replace(tzinfo=supor)
    return int(d.timestamp())


def hora_sp(ts: int) -> int:
    """Hora do dia em Sao Paulo. Independe do fuso da maquina."""
    return de_epoch(ts, SP).hour


def data_sp(ts: int) -> str:
    """Data do PREGAO a que o instante pertence, em Sao Paulo."""
    return de_epoch(ts, SP).date().isoformat()


def no_pregao(ts: int) -> bool:
    h = hora_sp(ts)
    return B3_ABRE_H <= h < B3_FECHA_H


def fechamento_utc(data_iso: str) -> int:
    """Epoch do fechamento da B3 naquela data (17h de Sao Paulo).

    Usado como `asof` na reconstrucao historica. Com ZoneInfo, uma data de
    2018 recebe o offset de 2018 (-02, horario de verao) e uma de 2026 recebe
    -03 -- o que um `+21h UTC` fixo erraria por uma hora no periodo antigo.
    """
    d = dt.date.fromisoformat(data_iso)
    return int(dt.datetime(d.year, d.month, d.day, B3_FECHA_H, 0,
                           tzinfo=SP).timestamp())


# ------------------------------------------------------------- validacao ---
TOLERANCIA_FUTURO_S = 3600       # 1h de folga para relogio dessincronizado


def suspeito(ts: int, agora: int | None = None) -> str | None:
    """Devolve o motivo se o carimbo for implausivel, ou None se estiver ok.

    Carimbo no futuro e a assinatura exata do erro de fuso: um `-0000` lido
    como local adianta o artigo pelo tamanho do offset. Checar isso na
    INGESTAO e o que impede o erro de voltar em silencio.
    """
    agora = agora if agora is not None else agora_ts()
    if ts > agora + TOLERANCIA_FUTURO_S:
        return f"no futuro ({(ts - agora) / 3600:.1f}h adiante)"
    if ts < 946684800:                       # 2000-01-01
        return "anterior a 2000"
    return None


# ----------------------------------------- deteccao de fuso por medicao ---
# POR QUE NAO BASTA LER O FUSO DECLARADO
# Sites declaram fuso errado. O Valor carimba `-0000` sendo brasileiro; outros
# publicam hora local rotulada como UTC. Confiar no rotulo e apostar que toda
# fonte esta certa -- e uma errou, custou 329 artigos deslocados em 3h.
#
# A DEFESA E UM SINAL INDEPENDENTE: a diferenca entre o que a fonte DIZ e o
# instante em que NOS coletamos. Com polling de 1 minuto, pelo menos algumas
# materias sao pegas minutos apos sairem, entao a MENOR latencia de cada
# dominio deve ficar perto de zero.
#
# ATENCAO AO ESTATISTICO CERTO: a MEDIANA nao serve. Feed que traz catalogo
# antigo tem mediana de horas sem nenhum erro de fuso -- MEDIDO: o Economist
# deu mediana de 220.000 minutos simplesmente por publicar arquivo. O que
# denuncia fuso e o PERCENTIL BAIXO, que mede o caso mais fresco.
#
# E SO O CASO NEGATIVO E CONCLUSIVO. Publicacao no futuro e impossivel, logo
# p10 negativo em multiplo de hora e erro de fuso com certeza. Ja um p10 de
# +2h pode ser fuso OU latencia real da fonte -- esse fica como SUSPEITA, para
# o usuario decidir, porque "corrigir" latencia verdadeira seria introduzir o
# erro que se quer evitar.
SCHEMA_FUSO = """
CREATE TABLE IF NOT EXISTS fonte_fuso (
  dominio TEXT PRIMARY KEY, offset_s INTEGER NOT NULL, metodo TEXT NOT NULL,
  n INTEGER, p10_s INTEGER, detectado_ts INTEGER NOT NULL
);
"""
MIN_AMOSTRA_FUSO = 12       # abaixo disso o p10 e ruido
TOL_HORA = 0.25             # quao perto de hora inteira para contar como fuso


def init_fuso(con):
    with con:
        con.executescript(SCHEMA_FUSO)


def diagnostica_fontes(con, dias: int = 30) -> list[dict]:
    """Mede o atraso por dominio e classifica. NAO grava nada."""
    init_fuso(con)
    corte = agora_ts() - dias * 86400
    out = []
    for (dom,) in con.execute(
            "SELECT domain FROM articles WHERE source='rss' AND ingested_ts >= ? "
            "GROUP BY domain HAVING COUNT(*) >= ?", (corte, MIN_AMOSTRA_FUSO)):
        at = sorted(r[0] for r in con.execute(
            "SELECT ingested_ts - published_ts FROM articles WHERE source='rss' "
            "AND domain=? AND ingested_ts >= ?", (dom, corte)))
        if len(at) < MIN_AMOSTRA_FUSO:
            continue
        p10 = at[int(0.10 * (len(at) - 1))]
        horas = p10 / 3600.0
        perto = abs(horas - round(horas)) < TOL_HORA
        if p10 < -600 and perto and round(horas) != 0:
            veredito, offset = "fuso errado", int(round(horas) * 3600)
        elif horas >= 0.75 and perto:
            veredito, offset = "suspeita", int(round(horas) * 3600)
        else:
            veredito, offset = "ok", 0
        out.append({"dominio": dom, "n": len(at), "p10_s": p10,
                    "p10_min": round(p10 / 60, 1), "veredito": veredito,
                    "offset_s": offset})
    return sorted(out, key=lambda d: d["p10_s"])


def aplica_deteccao(con, dias: int = 30, incluir_suspeitas: bool = False) -> int:
    """Grava a correcao dos dominios com veredito conclusivo."""
    n = 0
    for d in diagnostica_fontes(con, dias):
        ok = d["veredito"] == "fuso errado" or (
            incluir_suspeitas and d["veredito"] == "suspeita")
        if not ok or d["offset_s"] == 0:
            continue
        with con:
            con.execute("INSERT OR REPLACE INTO fonte_fuso VALUES (?,?,?,?,?,?)",
                        (d["dominio"], d["offset_s"], d["veredito"], d["n"],
                         d["p10_s"], agora_ts()))
        n += 1
    return n


def offsets_conhecidos(con) -> dict[str, int]:
    init_fuso(con)
    return {r[0]: r[1] for r in con.execute(
        "SELECT dominio, offset_s FROM fonte_fuso")}
