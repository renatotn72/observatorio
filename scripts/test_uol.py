#!/usr/bin/env python3
"""Trava o comportamento da fonte UOL. SEM REDE -- usa respostas gravadas.

POR QUE SEM REDE, E POR QUE ISSO E O CERTO
Teste que depende da API estar de pe nao roda em CI e nao roda offline. Pior:
quando falha, nao se sabe se o defeito e nosso ou da fonte. Aqui as respostas
sao fixtures com os valores EXATOS medidos na sondagem de 04/10/2026, entao
o teste responde uma pergunta so: "o nosso mapeamento ainda esta certo?".

As tres armadilhas que ele trava -- cada uma grava serie errada EM SILENCIO:

  1. INTERDAY: `close` e o fechamento da SESSAO ANTERIOR, nao da barra. O
     fechamento da barra esta em `price`. Medido: a barra 20261002 do ITUB4
     traz close=44.15, que e o `price` da barra 20261001. Mapear close->close
     desloca a serie INTEIRA em um dia, e nada no dado denuncia.

  2. INTRADAY: so `price` e `date` sao por barra. `high`/`low`/`open` sao da
     SESSAO e vem constantes; `volume` e ACUMULADO no dia.

  3. CATALOGO: pagina vazia nao e fim da lista (?p=32 veio vazia enquanto 34
     a 39 vieram cheias), e BDR nao e acao.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obs import uol                                          # noqa: E402

FALHAS = []


def ok(cond, desc, det=""):
    marca = "OK " if cond else "FALHOU"
    if not cond:
        FALHAS.append(desc)
    print(f"  [{marca}] {desc}" + (f"  -- {det}" if det else ""))


# ---------------------------------------------------------------- fixtures --
# Valores EXATOS da sondagem do ITUB4 (data_id 884). docs vem DECRESCENTE.
INTERDAY = {"prev": None, "next": None, "docs": [
    {"date": "20261002000000", "price": 44.80, "close": 44.15,
     "open": 44.20, "high": 45.00, "low": 44.10, "volume": 31_000_000,
     "change": 0.65, "pctChange": 1.47},
    {"date": "20261001000000", "price": 44.15, "close": 43.90,
     "open": 43.95, "high": 44.30, "low": 43.80, "volume": 28_500_000,
     "change": 0.25, "pctChange": 0.57},
    {"date": "20260930000000", "price": 43.90, "close": 43.70,
     "open": 43.75, "high": 44.00, "low": 43.60, "volume": 30_100_000,
     "change": 0.20, "pctChange": 0.46},
]}

# Na sessao, high/low/open sao CONSTANTES e volume e ACUMULADO.
INTRADAY = {"prev": None, "next": None, "docs": [
    {"date": "20261002170000", "price": 44.80, "close": 44.15,
     "open": 45.25, "high": 45.27, "low": 43.10, "volume": 31_000_000},
    {"date": "20261002165900", "price": 44.75, "close": 44.15,
     "open": 45.25, "high": 45.27, "low": 43.10, "volume": 30_800_000},
    {"date": "20261002165800", "price": 44.70, "close": 44.15,
     "open": 45.25, "high": 45.27, "low": 43.10, "volume": 30_500_000},
]}

PAGINA_PAPEL = '''<html><body>
<div class="financial-market-full stockAcao stockPage" data-mode="graphic"
     data-title="ITAUUNIBANCO PN" data-id="884" ng-controller="ChartController"
     ng-init='stockPage=true;error=false;'
     data-dateTime='{"timeCurrency":{"startTime":"9:00","endTime":"17:00"}}'
     data-metrics-view=""></div>
</body></html>'''

PAGINA_LISTA = '''<html><body>
 <a href="/cotacoes/bolsas/acoes/bvsp-bovespa/itub4-sa/">ITUB4</a>
 <a href="/cotacoes/bolsas/acoes/bvsp-bovespa/petr4-sa/">PETR4</a>
 <a href="/cotacoes/bolsas/acoes/bvsp-bovespa/a1fl34-sa/">A1FL34</a>
 <a href="/cotacoes/bolsas/acoes/bvsp-bovespa/bova11-sa/">BOVA11</a>
 <a href="/cotacoes/bolsas/acoes/bvsp-bovespa/itub4-sa/">repetido</a>
</body></html>'''


print("\n1. ARMADILHA 1 — no interday, `price` e o fechamento da barra")
barras = uol.mapeia_interday(INTERDAY["docs"])
ok(len(barras) == 3, "tres barras mapeadas", len(barras))
ok([b["date"] for b in barras] == ["2026-09-30", "2026-10-01", "2026-10-02"],
   "ordem invertida para CRESCENTE (a API devolve decrescente)",
   [b["date"] for b in barras])
ultima = barras[-1]
ok(ultima["close"] == 44.80,
   "o fechamento da barra 02/10 e 44.80 (o `price`), nao 44.15", ultima["close"])
ok(ultima["fechamento_anterior"] == 44.15,
   "o `close` da API vira `fechamento_anterior`", ultima["fechamento_anterior"])
# A PROVA do deslocamento: o `close` de uma barra e o `price` da anterior.
penultima = barras[-2]
ok(ultima["fechamento_anterior"] == penultima["close"],
   "PROVA: o `close` da API e o fechamento do pregao ANTERIOR",
   f"{ultima['fechamento_anterior']} == {penultima['close']}")
ok(ultima["open"] == 44.20 and ultima["high"] == 45.00
   and ultima["low"] == 44.10 and ultima["volume"] == 31_000_000,
   "OHLCV do interday preservado")

print("\n2. ARMADILHA 2 — no intraday nao ha OHLC, e o volume e acumulado")
intra = uol.mapeia_intraday(INTRADAY["docs"])
ok(len(intra) == 3, "tres barras", len(intra))
ok([b["ts"] for b in intra] == sorted(b["ts"] for b in intra),
   "ordem crescente por timestamp")
ok(all("high" not in b and "low" not in b and "open" not in b for b in intra),
   "NAO devolve OHLC: a API da valor de SESSAO, nao de barra")
# volume da barra = diferenca entre acumulados consecutivos
ok(intra[1]["volume"] == 30_800_000 - 30_500_000,
   "volume da barra = diferenca dos acumulados", intra[1]["volume"])
ok(intra[2]["volume"] == 31_000_000 - 30_800_000,
   "idem na barra seguinte", intra[2]["volume"])
ok(intra[0]["volume"] == 30_500_000,
   "a primeira barra fica com o acumulado (nao ha anterior)", intra[0]["volume"])
ok(intra[-1]["close"] == 44.80, "o preco da barra e o `price`", intra[-1]["close"])
# fuso: a UOL carimba em horario de Brasilia
import datetime as _dt                                        # noqa: E402
hora = _dt.datetime.fromtimestamp(
    intra[-1]["ts"], _dt.timezone(_dt.timedelta(hours=-3))).strftime("%H:%M")
ok(hora == "17:00", "timestamp interpretado em horario de Brasilia", hora)

print("\n3. data-id extraido da pagina do papel")
did, titulo = uol.extrai_id(PAGINA_PAPEL)
ok(did == "884", "data-id do ITUB4 e 884", did)
ok(titulo == "ITAUUNIBANCO PN", "data-title tambem vem", titulo)
# a ordem dos atributos nao pode importar: HTML gerado troca sem aviso
trocado = PAGINA_PAPEL.replace(
    'data-title="ITAUUNIBANCO PN" data-id="884"',
    'data-id="884" data-title="ITAUUNIBANCO PN"')
ok(uol.extrai_id(trocado)[0] == "884", "a ordem dos atributos nao importa")
ok(uol.extrai_id("<html>nada aqui</html>") == (None, None),
   "pagina sem a div devolve (None, None), sem quebrar")

print("\n4. ARMADILHA 3 — catalogo: BDR nao e acao, e pagina vazia nao e fim")
casos = [("ITUB4", uol.ACAO), ("PETR3", uol.ACAO), ("VALE3", uol.ACAO),
         ("TAEE11", uol.ETF_FII), ("BOVA11", uol.ETF_FII),
         ("A1FL34", uol.BDR), ("A1GI34", uol.BDR), ("AAPL34", uol.BDR),
         ("PETR4F", uol.OUTRO), ("", uol.OUTRO)]
for t, esperado in casos:
    got = uol.classifica(t)
    ok(got == esperado, f"{t or '(vazio)'} -> {esperado}", got)

achados = uol.tickers_da_pagina(PAGINA_LISTA)
ok(achados == ["ITUB4", "PETR4", "A1FL34", "BOVA11"],
   "tickers extraidos sem repetir", achados)

print("\n5. a sondagem separa ATIVO de SEM_DADO")
import datetime as dtm                                        # noqa: E402
hoje = dtm.date(2026, 10, 4)
muitas = [{"date": (dtm.date(2026, 3, 2) + dtm.timedelta(days=i)).isoformat(),
           "close": 10.0} for i in range(0, 216)]
st, _m = uol.avalia(muitas, hoje)
ok(st == "ativo", "serie longa e recente -> ativo", st)
st, m = uol.avalia(muitas[:30], hoje)
ok(st == "sem_dado", "menos de 60 barras -> sem_dado", m)
antigas = [{"date": (dtm.date(2025, 1, 2) + dtm.timedelta(days=i)).isoformat(),
            "close": 10.0} for i in range(0, 200)]
st, m = uol.avalia(antigas, hoje)
ok(st == "descontinuado", "ultima barra velha -> descontinuado", m)
st, m = uol.avalia([], hoje)
ok(st == "sem_dado", "sem barra nenhuma -> sem_dado", m)

print("\n6. ARMADILHA 3b — deteccao de serie nao ajustada por proventos")
# desdobramento 4:1 nao ajustado aparece como queda de 75% num pregao
com_split = [{"date": "2026-01-02", "close": 40.0},
             {"date": "2026-01-05", "close": 10.0},
             {"date": "2026-01-06", "close": 10.1}]
s = uol.conferir_ajuste(com_split)
ok(len(s) == 1, "salto detectado", len(s))
ok(abs(s[0]["razao"] - 4.0) < 1e-9, "razao 4:1 identificada", s[0]["razao"])
ok(uol.conferir_ajuste([{"date": "2026-01-02", "close": 40.0},
                        {"date": "2026-01-05", "close": 41.0}]) == [],
   "serie normal nao acusa salto")

print("\n7. a URL montada e a que foi sondada")
u = uol._url("years", "884")
for pedaco in ("interday/list/years/", "item=884", "format=JSON",
               "price", "volume", "date"):
    ok(pedaco in u, f"a URL contem {pedaco!r}")
ok(uol._url("intraday", "884").startswith(
    "https://api.cotacoes.uol.com/asset/intraday/list/"), "URL de intraday")
ok("days" not in uol.PERIODOS and "weeks" not in uol.PERIODOS,
   "/days/ e /weeks/ nao entram: devolvem HTTP 500")

print("\n8. o parser aguenta resposta degenerada sem gravar lixo")
ok(uol.mapeia_interday([]) == [], "docs vazio -> lista vazia")
ok(uol.mapeia_interday(None) == [], "docs None -> lista vazia")
ok(uol.mapeia_interday([{"date": "20261002000000"}]) == [],
   "barra sem `price` e descartada, nao vira close=0")
ok(uol.mapeia_intraday([{"price": 1.0}]) == [],
   "barra sem `date` e descartada")

print("\n9. A CADEIA INTEIRA — descobrir, sondar, coletar, com rede FALSA")
# Prova que o encanamento grava o que deve, sem depender da UOL estar de pe.
# E o que separa "o codigo compila" de "a ingestao funciona".
import tempfile                                               # noqa: E402

os.environ["OBS_DB"] = os.path.join(
    tempfile.mkdtemp(prefix="obs_uol_"), "teste.db")
# precisa recarregar os modulos que leem DB_PATH na importacao
for m in list(sys.modules):
    if m.startswith("obs"):
        del sys.modules[m]
from obs import db as _db, prices as _prices, uol as _uol      # noqa: E402
from obs.db import connect as _connect                         # noqa: E402

CHAMADAS = []


class _Resp:
    def __init__(self, texto=None, dados=None):
        self.text = texto or ""
        self._dados = dados

    def json(self):
        if self._dados is None:
            raise ValueError("sem json")
        return self._dados


def _falso_http(url, **kw):
    CHAMADAS.append(url)
    # a listagem: pagina 1 cheia, 2 de BDR, 3 em diante vazias
    if url.rstrip("/").endswith("bvsp-bovespa") or "bvsp-bovespa/?p=" in url:
        if "?p=" not in url:
            return _Resp(texto=PAGINA_LISTA)
        p = int(url.split("?p=")[1])
        if p == 2:
            # BDR novo + um repetido da pagina 1: testa dedup E o fato de
            # que pagina com so repetidos NAO conta como vazia
            return _Resp(texto='<a href="/cotacoes/bolsas/acoes/bvsp-bovespa/'
                               'a1gi34-sa/">x</a>'
                               '<a href="/cotacoes/bolsas/acoes/bvsp-bovespa/'
                               'itub4-sa/">rep</a>')
        return _Resp(texto="<html>sem papeis</html>")
    # pagina do papel -> data-id
    if "-sa/" in url:
        return _Resp(texto=PAGINA_PAPEL)
    # API de cotacao
    if "interday/list/years" in url:
        hoje = dtm.date.today()
        docs = [{"date": (hoje - dtm.timedelta(days=i)).strftime("%Y%m%d") + "000000",
                 "price": 44.80 - i * 0.01, "close": 44.80 - (i + 1) * 0.01,
                 "open": 44.2, "high": 45.0, "low": 44.1, "volume": 1e6 + i}
                for i in range(200)]
        return _Resp(dados={"prev": None, "next": None, "docs": docs})
    if "intraday/list" in url:
        return _Resp(dados=INTRADAY)
    return None


_uol.http_get = _falso_http
_uol.PAUSA_S = 0           # o teste nao espera 1,2s por requisicao
_db.init()

r = _uol.descobrir(paginas_max=8, verbose=False)
ok(r["total"] == 5, "catalogo gravou os 5 tickers distintos "
   "(o repetido entre paginas nao duplica)", r["total"])
ok(r["por_categoria"].get("acao") == 2,
   "classificou 2 acoes (ITUB4, PETR4)", r["por_categoria"])
ok(r["por_categoria"].get("bdr") == 2, "e 2 BDR (A1FL34, A1GI34)",
   r["por_categoria"])
ok(r["por_categoria"].get("etf_fii") == 1, "e 1 ETF (BOVA11)")
paginas = [u for u in CHAMADAS if "?p=" in u]
ok(len(paginas) >= 4,
   "nao parou na primeira pagina vazia (3 vazias seguidas e o criterio)",
   f"{len(paginas)} paginas pedidas")

CHAMADAS.clear()
s = _uol.sondar(categorias=("acao",), verbose=False)
ok(s["resumo"]["ativo"] == 2, "as 2 acoes ficaram ATIVAS", s["resumo"])
con = _connect()
a = dict(con.execute("SELECT * FROM ativos WHERE ticker='ITUB4'").fetchone())
con.close()
ok(a["id_externo"] == "884", "o data-id foi cacheado no cadastro", a["id_externo"])
ok(a["nome"] == "ITAUUNIBANCO PN", "o nome tambem", a["nome"])
ok(a["status"] == "ativo" and a["barras"] == 200, "status e contagem gravados",
   f"{a['status']}/{a['barras']}")
ok(a["sondado_ts"], "carimbo da sondagem gravado (nao resondar antes de 30d)")

# pendentes nao devolve quem ja esta ativo e foi sondado agora
ok(_uol.pendentes(("acao",)) == [], "papel ativo recem-sondado sai da fila")

CHAMADAS.clear()
c = _uol.coletar(verbose=False)
ok(c["papeis"] == 2, "coletou os 2 ativos", c["papeis"])
ok(c["barras"] == 400, "400 barras gravadas (200 x 2)", c["barras"])
ok(not c["saltos"], "nenhum salto suspeito nesta serie sintetica")

con = _connect()
b = dict(con.execute(
    "SELECT * FROM prices WHERE ticker='ITUB4' ORDER BY date DESC LIMIT 1").fetchone())
n_origem = con.execute(
    "SELECT COUNT(*) FROM prices WHERE origem='uol'").fetchone()[0]
con.close()
ok(b["origem"] == "uol", "a ORIGEM foi carimbada em cada barra", b["origem"])
ok(n_origem == 400, "todas as barras com origem=uol", n_origem)
ok(b["close"] == 44.80, "o close gravado e o `price` da API (armadilha 1)",
   b["close"])
ok(b["volume"] is not None and b["high"] is not None,
   "OHLCV gravado -- o que o Yahoo nao da",
   f"high={b['high']} volume={b['volume']}")

# idempotencia: recoletar nao duplica
antes = _connect().execute("SELECT COUNT(*) FROM prices").fetchone()[0]
_uol.coletar(verbose=False)
depois = _connect().execute("SELECT COUNT(*) FROM prices").fetchone()[0]
ok(antes == depois, "recoletar NAO duplica (idempotente por ticker+data)",
   f"{antes} -> {depois}")

n_intra = _uol.coletar_intraday(["ITUB4"], verbose=False)
con = _connect()
bi = dict(con.execute("SELECT * FROM intraday WHERE simbolo='ITUB4' "
                      "ORDER BY ts DESC LIMIT 1").fetchone())
con.close()
ok(n_intra == 3, "3 barras de 1 min gravadas", n_intra)
ok(bi["origem"] == "uol" and bi["intervalo"] == "1m", "intervalo e origem certos")
ok(bi["volume"] == 200000.0, "volume da barra ja diferenciado (armadilha 2)",
   bi["volume"])

e = _uol.estado()
ok(e["com_barras"] == 2, "o relatorio de aceite conta os papeis com barra",
   e["com_barras"])
ok(e["por_categoria"].get("bdr") == 2,
   "a categoria BDR ficou guardada, nao descartada", e["por_categoria"])

print()
if FALHAS:
    print(f"{len(FALHAS)} CASO(S) FALHARAM:")
    for f in FALHAS:
        print("  -", f)
    sys.exit(1)
print("todos os casos passaram")
