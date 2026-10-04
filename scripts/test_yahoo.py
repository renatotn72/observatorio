#!/usr/bin/env python3
"""Trava o comportamento do chart v8 do Yahoo. SEM REDE -- respostas montadas.

POR QUE SEM REDE: teste que depende da API estar de pe nao roda em CI e, quando
falha, nao diz se o defeito e nosso ou da fonte. Aqui as respostas sao
construidas no formato EXATO do esquema JSON da especificacao de 04/10/2026, e
o teste responde uma pergunta so: "o nosso mapeamento e o nosso deslizamento de
janela ainda estao certos?".

De onde vem cada coisa, para ninguem confundir medicao com fixture: a ESTRUTURA
(arrays paralelos, `adjclose` em array separado, `events.dividends`/`splits`
indexados por epoch, erro em `chart.error` com HTTP 200) e o esquema que o
usuario entregou. Os NUMEROS sao sinteticos, escolhidos para que cada armadilha
tenha um caso que falha alto se o codigo regredir. Nenhuma resposta crua foi
capturada aqui -- a rede deste ambiente nao alcanca query2.finance.yahoo.com.

AS ARMADILHAS QUE ELE TRAVA, todas silenciosas:

  1. ARRAYS PARALELOS COM BURACO. `timestamp` tem N posicoes e cada array de
     `quote` tem N, com `null` em pregao sem negocio, leilao e feriado. Ignorar
     o null grava 0,0 ou quebra na conversao.
  2. `adjclose` E ARRAY SEPARADO e so vem quando `events` foi pedido. Se
     faltar, a coluna tem de ficar NULL -- jamais receber o fechamento cru
     disfarcado de ajustado.
  3. ERRO VEM COM HTTP 200, em `chart.error`, com `result: null`. Tratar so o
     status confundiria papel inexistente com papel sem negocio.
  4. JANELA VAZIA NAO E FIM DA SERIE. Uma janela de 8 dias pode cair inteira em
     recesso. Parar na primeira encurtaria a coleta -- a mesma licao da pagina
     32 da UOL, que veio vazia com as de 34 a 39 cheias.
  5. `COALESCE(adjclose, close)` E DEFEITO, nao atalho. Metade da serie
     ajustada e metade crua da um salto na fronteira que nao houve no mercado.
     A escolha e por papel e inteira.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FALHAS = []


def ok(cond, desc, det=""):
    marca = "OK " if cond else "FALHOU"
    if not cond:
        FALHAS.append(desc)
    print(f"  [{marca}] {desc}" + (f"  -- {det}" if det else ""))


os.environ["OBS_DB"] = os.path.join(
    tempfile.mkdtemp(prefix="obs_yf_"), "teste.db")
for m in list(sys.modules):
    if m.startswith("obs"):
        del sys.modules[m]

from obs import db as _db, prices as _prices, yahoo as _yf   # noqa: E402
from obs.db import connect as _connect                       # noqa: E402

DIA = 86400


# ---------------------------------------------------------------- fixtures --
def resposta(ts, close, *, open_=None, high=None, low=None, vol=None,
             adj="igual", eventos=None, nome="TESTE S.A."):
    """Monta `chart.result[0]` no formato do esquema.

    adj="igual"  -> adjclose = close
    adj=None     -> SEM array de adjclose (o caso de `events` nao pedido)
    adj=lista    -> valores proprios
    """
    q = {"close": list(close),
         "open": list(open_ if open_ is not None else close),
         "high": list(high if high is not None else close),
         "low": list(low if low is not None else close),
         "volume": list(vol if vol is not None else [1000] * len(close))}
    ind = {"quote": [q]}
    if adj == "igual":
        ind["adjclose"] = [{"adjclose": list(close)}]
    elif adj is not None:
        ind["adjclose"] = [{"adjclose": list(adj)}]
    res = {"meta": {"symbol": "TEST.SA", "longName": nome,
                    "instrumentType": "EQUITY", "currency": "BRL",
                    "exchangeName": "SAO",
                    "firstTradeDate": ts[0] if ts else None,
                    "validRanges": ["1d", "5d", "max"]},
           "timestamp": list(ts), "indicators": ind}
    if eventos is not None:
        res["events"] = eventos
    return {"chart": {"result": [res], "error": None}}


class _Resp:
    def __init__(self, dados):
        self._d = dados
        self.text = ""

    def json(self):
        return self._d


# =========================================================== 1. mapeamento ==
print("1. arrays paralelos, buraco e adjclose em array separado")

T0 = 1760000000
ts = [T0, T0 + DIA, T0 + 2 * DIA, T0 + 3 * DIA]
# pregao 2 sem negocio: close null, e os outros campos tambem
cru = resposta(ts, [10.0, None, 12.0, 13.0],
               vol=[100, None, 300, 400],
               adj=[9.0, None, 11.0, 12.0])
barras = _yf.mapeia_barras(cru["chart"]["result"][0], diario=True)
ok(len(barras) == 3, "barra sem fechamento e DESCARTADA, nao gravada como 0",
   f"{len(barras)} de 4 posicoes")
ok([b["close"] for b in barras] == [10.0, 12.0, 13.0],
   "os fechamentos sobreviventes estao na ordem certa",
   [b["close"] for b in barras])
ok([b["adjclose"] for b in barras] == [9.0, 11.0, 12.0],
   "adjclose veio do array SEPARADO, alinhado por indice",
   [b["adjclose"] for b in barras])
ok(barras[0]["volume"] == 100 and barras[-1]["volume"] == 400,
   "volume acompanha o mesmo indice")
ok(all("date" in b for b in barras) and "ts" not in barras[0],
   "no modo diario a chave e a DATA, nao o epoch", barras[0].get("date"))

semadj = resposta(ts[:2], [10.0, 11.0], adj=None)
b2 = _yf.mapeia_barras(semadj["chart"]["result"][0], diario=True)
ok(all(b["adjclose"] is None for b in b2),
   "sem array de adjclose, a coluna fica NULL -- nunca o close cru no lugar",
   [b["adjclose"] for b in b2])

intra = _yf.mapeia_barras(resposta(ts, [1.0, 2.0, 3.0, 4.0])["chart"]["result"][0],
                          diario=False)
ok(all("ts" in b for b in intra) and intra[0]["ts"] == T0,
   "no modo intradiario a chave e o EPOCH", intra[0]["ts"])


# ============================================================= 2. eventos ===
print("\n2. proventos e desdobramentos")

EV = {"dividends": {"1335963600": {"amount": 0.25, "date": 1335963600},
                    "1392987600": {"amount": 0.40, "date": 1392987600}},
      "splits": {"1443704400": {"date": 1443704400, "numerator": 2,
                                "denominator": 1, "splitRatio": "2:1"}}}
evs = _yf.mapeia_eventos({"events": EV})
ok(len(evs) == 3, "os tres eventos saem", len(evs))
divs = [e for e in evs if e["tipo"] == "dividendo"]
spl = [e for e in evs if e["tipo"] == "desdobramento"]
ok(sorted(e["valor"] for e in divs) == [0.25, 0.40],
   "valor do dividendo vem de `amount`")
ok(spl[0]["razao"] == "2:1" and spl[0]["numerador"] == 2.0,
   "desdobramento guarda razao E os dois numeros", spl[0])
ok(evs == sorted(evs, key=lambda x: (x["data"], x["tipo"])),
   "saida ordenada, para a gravacao ser estavel")
ok(_yf.mapeia_eventos({}) == [],
   "resposta sem `events` nao quebra: devolve lista vazia")
# a chave do dicionario e o epoch e o valor REPETE a data. Usamos `date`.
so_chave = {"dividends": {"1335963600": {"amount": 1.0}}}
_sem_date = _yf.mapeia_eventos({"events": so_chave})
ok(len(_sem_date) == 1
   and _sem_date[0]["data"] == _yf.date_str(1335963600),
   "se `date` faltar, cai para a chave em vez de perder o evento",
   _sem_date[0]["data"] if _sem_date else "perdeu o evento")


# =============================================== 3. erro com HTTP 200 =======
print("\n3. o erro do Yahoo vem com HTTP 200")

CHAMADAS = []


def _http_erro(url, **kw):
    CHAMADAS.append(url)
    return _Resp({"chart": {"result": None,
                            "error": {"code": "Not Found",
                                      "description": "No data found, symbol "
                                                     "may be delisted"}}})


_yf.http_get = _http_erro
barras, evs2, m = _yf.diario("NAOEXISTE3")
ok(barras == [] and evs2 == [], "papel inexistente nao devolve barra")
ok("Not Found" in (m.get("erro") or ""),
   "e a DESCRICAO do erro chega a quem chamou, em vez de 'serie vazia'",
   m.get("erro"))


# ====================================== 4. janela deslizante do intradiario =
print("\n4. janela deslizante: 8 dias por requisicao, e vazia nao e fim")

# serie de 1 min sintetica cobrindo 25 dias, com um VAO de 9 dias no meio --
# maior que a janela, para que uma requisicao caia inteira no vao.
HOJE = 1760000000
PASSOS = []
for d in list(range(0, 8)) + list(range(17, 25)):
    PASSOS.append(HOJE - d * DIA)
PASSOS.sort()


def _http_janela(url, params=None, **kw):
    CHAMADAS.append((params or {}).get("period1"))
    p1 = int((params or {}).get("period1", 0))
    p2 = int((params or {}).get("period2", 0))
    dentro = [t for t in PASSOS if p1 <= t <= p2]
    if not dentro:
        return _Resp(resposta([], []))
    return _Resp(resposta(dentro, [10.0 + i for i in range(len(dentro))]))


_yf.http_get = _http_janela
_yf.PAUSA_S = 0
CHAMADAS.clear()
ser, rel = _yf.intradiario("TEST3", "1m", janelas_max=20, ate=HOJE)
ok(len(ser) == len(PASSOS),
   "a serie inteira foi recuperada APESAR do vao maior que a janela",
   f"{len(ser)} de {len(PASSOS)}")
ok(rel["janelas_pedidas"] >= 4,
   "foram varias janelas, nao uma so", rel["janelas_pedidas"])
ok(len({b["ts"] for b in ser}) == len(ser),
   "janelas sobrepostas NAO duplicam barra")
ok(ser == sorted(ser, key=lambda b: b["ts"]), "saida em ordem de tempo")
ok(rel["mais_antiga"] == _yf.date_str(min(PASSOS)),
   "o relatorio diz o ALCANCE MEDIDO, nao um alcance prometido",
   rel["mais_antiga"])

# o teto de janela por intervalo e respeitado
# a LARGURA pedida e a do intervalo, medida nos period1 que sairam
_yf.http_get = _http_janela
CHAMADAS.clear()
_yf.intradiario("TEST3", "1h", janelas_max=2, ate=HOJE)
p1s = [int(c) for c in CHAMADAS if c is not None]
ok(p1s and abs((HOJE - p1s[0]) / DIA - 720) < 1,
   "a primeira janela de 1h pede 720 dias, nao 8 nem 60",
   f"{(HOJE - p1s[0]) / DIA:.0f} dias")
CHAMADAS.clear()
_yf.intradiario("TEST3", "5m", janelas_max=1, ate=HOJE)
p5 = [int(c) for c in CHAMADAS if c is not None]
ok(p5 and abs((HOJE - p5[0]) / DIA - 60) < 1,
   "a de 5m pede 60 dias", f"{(HOJE - p5[0]) / DIA:.0f} dias")
ok(_yf.JANELA_DIAS["1m"] == 8 and _yf.JANELA_DIAS["5m"] == 60
   and _yf.JANELA_DIAS["1h"] == 720,
   "os tetos de janela sao os da especificacao (8 / 60 / 720 dias)")
ok(_yf.JANELA_DIAS["1d"] is None,
   "o diario nao desliza: cabe inteiro numa requisicao")
try:
    _yf.intradiario("TEST3", "1d")
    ok(False, "pedir diario ao deslizador deveria quebrar alto")
except ValueError:
    ok(True, "pedir diario ao deslizador quebra alto, em vez de deslizar atoa")

# para depois de 2 janelas vazias SEGUIDAS, nao na primeira
_yf.http_get = lambda url, params=None, **kw: _Resp(resposta([], []))
ser0, rel0 = _yf.intradiario("TEST3", "1m", janelas_max=50, ate=HOJE)
ok(ser0 == [] and rel0["janelas_pedidas"] == _yf.JANELAS_VAZIAS_PARA_PARAR,
   f"serie seca para em {_yf.JANELAS_VAZIAS_PARA_PARAR} janelas vazias, "
   f"nao em 50", rel0["janelas_pedidas"])


# ========================================= 5. a serie usada para retorno ====
print("\n5. adjclose x close: a escolha e POR PAPEL e INTEIRA")

_db.init()
con = _connect()
with con:
    # COMPLETO: adjclose em todas as barras
    # ATENCAO AO ESCOLHER OS NUMEROS: se adjclose fosse um multiplo fixo do
    # close (9.0/10.0, 9.9/11.0...), o RETORNO sairia identico nos dois modos
    # e este teste passaria mesmo com `ajustado` sendo ignorado. O ajuste por
    # provento nao e proporcional -- ele muda so o trecho ANTES da data-ex --
    # entao a fixture tem de ser nao proporcional tambem.
    for i, (d, c, a) in enumerate([("2026-01-02", 10.0, 9.00),
                                   ("2026-01-05", 11.0, 10.20),
                                   ("2026-01-06", 12.0, 11.40)]):
        con.execute("INSERT OR REPLACE INTO prices"
                    "(ticker,date,close,adjclose,origem) VALUES (?,?,?,?,?)",
                    ("CHEI4", d, c, a, "yahoo"))
    # PELA METADE: uma barra sem adjclose
    for d, c, a in [("2026-01-02", 20.0, 18.0), ("2026-01-05", 22.0, None),
                    ("2026-01-06", 24.0, 21.6)]:
        con.execute("INSERT OR REPLACE INTO prices"
                    "(ticker,date,close,adjclose,origem) VALUES (?,?,?,?,?)",
                    ("MEIO4", d, c, a, "yahoo"))
con.close()

con = _connect()
usa = _prices.serie_usada(con)
ok(usa["CHEI4"] == "adjclose",
   "papel com adjclose COMPLETO usa a serie ajustada")
ok(usa["MEIO4"] == "close",
   "papel com UMA barra sem adjclose usa `close` na serie INTEIRA "
   "-- e o defeito que COALESCE causaria", usa["MEIO4"])

r_aj = _prices.returns_by_date(con, ajustado=True)
r_cr = _prices.returns_by_date(con, ajustado=False)
ok(abs(r_aj["CHEI4"]["2026-01-05"] - (10.20 / 9.00 - 1)) < 1e-9,
   "com ajustado=True o retorno sai do adjclose",
   f"{r_aj['CHEI4']['2026-01-05']:.4f}")
ok(abs(r_aj["CHEI4"]["2026-01-05"] - r_cr["CHEI4"]["2026-01-05"]) > 0.03,
   "e os dois modos dao retorno DIFERENTE -- sem isso o teste nao provaria "
   "que `ajustado` e obedecido",
   f"{r_aj['CHEI4']['2026-01-05']:.4f} vs "
   f"{r_cr['CHEI4']['2026-01-05']:.4f}")
ok(abs(r_cr["CHEI4"]["2026-01-05"] - (11.0 / 10.0 - 1)) < 1e-9,
   "ajustado=False reproduz o calculo ANTIGO, sobre `close`",
   r_cr["CHEI4"]["2026-01-05"])
ok(r_aj["MEIO4"] == r_cr["MEIO4"],
   "no papel incompleto os dois modos coincidem: nao ha salto de fronteira")
con.close()


# ================================= 6. gravacao complementar com adjclose ====
print("\n6. o Yahoo completo entra sem apagar, e traz adjclose")

con = _connect()
with con:
    con.execute("DELETE FROM prices")
    con.execute("INSERT INTO prices(ticker,date,close,origem) "
                "VALUES ('PETR4','2026-01-02',30.00,'legado')")
con.close()
n = _prices.grava_diario(
    {"PETR4": [{"date": "2026-01-02", "close": 31.00, "open": 29.0,
                "high": 31.5, "low": 28.9, "volume": 9e6, "adjclose": 28.70},
               {"date": "2026-01-05", "close": 32.00, "open": 31.0,
                "high": 32.5, "low": 30.9, "volume": 8e6, "adjclose": 29.60}]},
    "yahoo", complementar=True)
con = _connect()
velha = dict(con.execute("SELECT * FROM prices WHERE ticker='PETR4' AND "
                         "date='2026-01-02'").fetchone())
nova = dict(con.execute("SELECT * FROM prices WHERE ticker='PETR4' AND "
                        "date='2026-01-05'").fetchone())
con.close()
ok(velha["close"] == 30.00 and velha["origem"] == "legado",
   "o fechamento que ja estava FICA", f"{velha['close']} / {velha['origem']}")
ok(velha["adjclose"] == 28.70 and velha["origem_ohlc"] == "yahoo",
   "mas o adjclose VAZIO foi preenchido, e a origem dele registrada",
   f"{velha['adjclose']} / {velha['origem_ohlc']}")
ok(nova["close"] == 32.00 and nova["adjclose"] == 29.60,
   "barra que nao existia entra inteira, com as duas colunas")
ok(n == 2, "duas barras tocadas", n)


# ============================== 7. conferir o ajuste num desdobramento ======
print("\n7. a serie esta ajustada? conferido num desdobramento conhecido")

con = _connect()
with con:
    con.execute("DELETE FROM prices")
    # desdobramento 2:1 em 2026-03-10: `close` cru CAI pela metade,
    # `adjclose` nao se mexe.
    for d, c, a in [("2026-03-09", 40.00, 20.00), ("2026-03-10", 20.00, 20.00),
                    ("2026-03-11", 20.50, 20.50)]:
        con.execute("INSERT OR REPLACE INTO prices"
                    "(ticker,date,close,adjclose,origem) VALUES (?,?,?,?,?)",
                    ("SPLT3", d, c, a, "yahoo"))
con.close()
_yf.grava_proventos("SPLT3", [{"data": "2026-03-10",
                               "tipo": "desdobramento", "valor": None,
                               "numerador": 2.0, "denominador": 1.0,
                               "razao": "2:1"}])
r = _yf.conferir_ajuste("SPLT3")
ok(r["desdobramentos"] == 1, "o desdobramento foi lido do banco")
ok(r["close_salta"] is True,
   "`close` SALTA no desdobramento -- e serie crua, como deve ser",
   r["casos"][0]["var_close"])
ok(r["adjclose_salta"] is False,
   "`adjclose` NAO salta -- e serie ajustada, confirmado em vez de suposto",
   r["casos"][0]["var_adjclose"])


# ===================================== 8. cadastro: uma linha por fonte =====
print("\n8. `ativos` guarda uma linha por (ticker, fonte)")

con = _connect()
with con:
    con.execute("INSERT OR REPLACE INTO ativos"
                "(ticker,fonte,id_externo,nome,categoria,status) "
                "VALUES ('PETR4','uol','6836','PETROBRAS PN','acao','ativo')")
con.close()
_yf.grava_cadastro("PETR4", {"nome": "Petroleo Brasileiro S.A.",
                             "tipo": "EQUITY"}, 2500, "2026-10-02",
                   "ativo", "2500 barras")
con = _connect()
linhas = {r["fonte"]: dict(r) for r in con.execute(
    "SELECT * FROM ativos WHERE ticker='PETR4'")}
con.close()
ok(set(linhas) == {"uol", "yahoo"},
   "as duas fontes convivem no mesmo ticker", sorted(linhas))
ok(linhas["uol"]["id_externo"] == "6836",
   "o data-id da UOL NAO foi apagado pelo cadastro do Yahoo",
   linhas["uol"]["id_externo"])
ok(linhas["yahoo"]["id_externo"] == "PETR4.SA",
   "e o Yahoo guarda o simbolo dele", linhas["yahoo"]["id_externo"])


# ================================================= 9. o universo pedido =====
print("\n9. os 89 papeis pedidos, e a correcao de SBSPSP3")

from obs import config as _cfg                                # noqa: E402
_cfg._CACHE = {} if hasattr(_cfg, "_CACHE") else None
uni = _cfg.universo()
ok(len(uni) == 89, "o universo tem os 89 papeis", len(uni))
ok("SBSP3" in uni and "SBSPSP3" not in uni,
   "SBSPSP3 (sete caracteres, 'SP' repetido) entrou como SBSP3, a Sabesp")
ok({"ARZZ3", "AZZA3"} <= set(uni) and {"NTCO3", "AXIA3"} <= set(uni),
   "os pares predecessor/sucessor ficaram os dois -- o antigo tem o historico")
ok(set(_cfg.tickers()) <= set(uni),
   "o universo CONTEM a watchlist")
ok(len(_cfg.tickers()) == 10,
   "e a watchlist continua com 10: o benchmark __crosssec__ nao mudou",
   len(_cfg.tickers()))

print()
if FALHAS:
    print(f"{len(FALHAS)} CASO(S) FALHARAM:")
    for f in FALHAS:
        print("  -", f)
    sys.exit(1)
print("todos os casos passaram")
