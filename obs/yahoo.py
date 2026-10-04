"""Yahoo chart v8: historico completo, janelas deslizantes, proventos e ajuste.

O ENDPOINT, destrinchado
    GET https://query2.finance.yahoo.com/v8/finance/chart/<PAPEL>.SA
        ?period1=0&period2=9791133200&interval=1d
        &includePrePost=true&events=div|split|earn
        &lang=en-US&region=BR&source=cosaic

    `period1`/`period2` sao epoch em SEGUNDOS. Para o diario da para pedir a
    serie inteira numa requisicao: period1=0 e um period2 absurdo
    (9791133200 ~ ano 2280) devolvem tudo o que existe, inclusive pre-2016.
    Para intradiario NAO da: cada intervalo tem uma janela MAXIMA, e pedir
    mais que ela devolve a janela permitida em silencio, nao um erro. E por
    isso que a coleta intradiaria DESLIZA a janela para tras em vez de pedir
    tudo.

TETO DE JANELA POR INTERVALO -- a restricao que organiza o modulo inteiro
    1m          8 dias por requisicao
    2m a 30m    60 dias por requisicao
    1h (60m)    720 dias por requisicao
    1d          sem teto: a serie toda de uma vez

    Deslizar nao e o mesmo que ter: o teto diz quanto CABE numa resposta, nao
    quanto o Yahoo GUARDA. Para o diario os dois coincidem (ele guarda tudo).
    Para 1m a retencao historica e curta, e ninguem sabe exatamente quanto sem
    medir -- por isso `intradiario` para sozinho depois de
    JANELAS_VAZIAS_PARA_PARAR janelas seguidas sem barra, do mesmo jeito que o
    catalogo da UOL para depois de 3 paginas vazias. O relatorio diz ate onde
    chegou de fato, em vez de o codigo afirmar um alcance que nao conferiu.

O QUE ESTA RESPOSTA TRAZ QUE NENHUMA OUTRA FONTE DO PROJETO TRAZIA
    1. `indicators.adjclose[0].adjclose` -- fechamento AJUSTADO por proventos
       e desdobramentos. E a serie certa para calcular retorno, e ate agora o
       projeto nao tinha nenhuma: `docs/precos-fontes.md` registrava o ajuste
       da serie atual como "provavel", inferido de nao haver salto > 35%.
       Agora e dado, nao inferencia.
    2. `events.dividends` e `events.splits` -- datas e valores. Com isso da
       para CONFERIR ajuste em vez de supor: num desdobramento 2:1, serie
       ajustada nao da salto e serie crua da. E o teste que a armadilha 3 da
       UOL pedia e que nao tinha como rodar.
    3. `meta.longName` -- o nome do papel vem junto do preco, entao nao e
       preciso digitar 89 nomes a mao.

CLOSE x ADJCLOSE: OS DOIS SAO GRAVADOS, E NAO SE MISTURAM
    `close` e o fechamento do dia como negociado -- e o numero que aparece na
    tela e que o usuario reconhece. `adjclose` e o mesmo fechamento corrigido
    para tras a cada provento -- e o numero com que se calcula retorno.
    Usar `close` para retorno cria queda artificial em cada data-ex; usar
    `adjclose` na tela mostra preco que ninguem viu. Guardar so um dos dois
    obriga a escolher qual dos dois erros cometer.
"""
from __future__ import annotations

import concurrent.futures as cf
import time

from .db import connect
from .util import date_str, http_get, now_ts

NOME = "yahoo"

BASE = "https://query2.finance.yahoo.com/v8/finance/chart/"
SUFIXO_B3 = ".SA"

# period2 "absurdo" da especificacao: ~ano 2280. Nao e magica -- e so um teto
# que o Yahoo trunca para a ultima barra que existe.
PERIOD2_TETO = 9791133200

# Teto de janela por intervalo, em DIAS. Medido/especificado em 04/10/2026.
# None = sem teto, cabe a serie inteira numa requisicao.
JANELA_DIAS = {
    "1m": 8,
    "2m": 60, "5m": 60, "15m": 60, "30m": 60, "90m": 60,
    "60m": 720, "1h": 720,
    "1d": None, "1wk": None, "1mo": None,
}
# Nomes que o resto do projeto usa -> nomes que o Yahoo aceita. O banco guarda
# "1h"; a API quer "60m" nesse caso e aceita "1h" tambem, mas fixar a
# traducao evita descobrir isso por tentativa.
PARA_YF = {"1h": "60m"}

JANELAS_VAZIAS_PARA_PARAR = 2
PAUSA_S = 0.35          # entre requisicoes do MESMO papel
PARALELO = 6            # papeis simultaneos; cada um serializa suas janelas

CABECALHO = {"User-Agent": "Mozilla/5.0 (compatible; observatorio-academico)"}

DIA_S = 86400


def _simbolo(ticker: str) -> str:
    t = ticker.strip().upper()
    return t if t.endswith(SUFIXO_B3) else t + SUFIXO_B3


def _params(interval: str, p1: int, p2: int) -> dict:
    return {"period1": str(int(p1)), "period2": str(int(p2)),
            "interval": PARA_YF.get(interval, interval),
            "includePrePost": "true", "events": "div|split|earn",
            "lang": "en-US", "region": "BR", "source": "cosaic"}


def _pega(ticker: str, interval: str, p1: int, p2: int) -> dict | None:
    """Uma requisicao. Devolve `chart.result[0]` cru, ou None.

    O ERRO DO YAHOO NAO VEM COMO HTTP 4xx: vem 200 com
    `chart.error = {"code": ..., "description": ...}` e `result = null`.
    Tratar so o status esconderia papel inexistente e devolveria serie vazia
    como se fosse papel sem negocio -- duas causas diferentes com o mesmo
    sintoma.
    """
    r = http_get(BASE + _simbolo(ticker), params=_params(interval, p1, p2),
                 headers=CABECALHO, timeout=45)
    if r is None:
        return None
    try:
        ch = r.json().get("chart") or {}
    except ValueError:
        return None
    if ch.get("error"):
        err = ch["error"]
        return {"_erro": f"{err.get('code')}: {err.get('description')}"}
    res = ch.get("result") or []
    return res[0] if res else None


# ------------------------------------------------------------- mapeadores ----
def mapeia_barras(res: dict, diario: bool) -> list[dict]:
    """`chart.result[0]` -> barras no formato que obs/prices.py grava.

    DUAS ARMADILHAS DESTE FORMATO, as duas silenciosas:

    1. OS ARRAYS SAO PARALELOS E TEM BURACO. `timestamp` tem N posicoes e cada
       array de `quote` tem as mesmas N, mas com `null` em pregao sem negocio,
       leilao e barra de feriado. Fechar os olhos para o null grava 0,0 ou
       quebra na conversao; aqui a barra sem fechamento e DESCARTADA, porque
       barra sem preco nao e observacao.

    2. `adjclose` E UM ARRAY SEPARADO, em `indicators.adjclose[0]`, e ele SO
       vem quando `events` foi pedido. Se faltar, nao se inventa: a coluna
       fica NULL e quem for calcular retorno sabe que ali nao ha serie
       ajustada, em vez de receber o fechamento cru disfarcado de ajustado.
    """
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    q = (ind.get("quote") or [{}])[0] or {}
    aj = (ind.get("adjclose") or [{}])[0] or {}
    adj = aj.get("adjclose") or []

    def _em(arr, i):
        if i < len(arr or []):
            v = arr[i]
            return None if v is None else float(v)
        return None

    out = []
    for i, t in enumerate(ts):
        c = _em(q.get("close"), i)
        if c is None:                      # sem fechamento nao e barra
            continue
        b = {"close": c,
             "open": _em(q.get("open"), i),
             "high": _em(q.get("high"), i),
             "low": _em(q.get("low"), i),
             "volume": _em(q.get("volume"), i),
             "adjclose": _em(adj, i)}
        if diario:
            b["date"] = date_str(int(t))
        else:
            b["ts"] = int(t)
        out.append(b)
    out.sort(key=lambda x: x.get("date") or x.get("ts"))
    return out


def mapeia_eventos(res: dict) -> list[dict]:
    """`events` -> proventos e desdobramentos, um registro por data.

    A CHAVE DO DICIONARIO E O EPOCH, e o valor REPETE a data em `date`. Uso o
    campo `date`, nao a chave: sao iguais hoje, e depender da chave seria
    depender de um detalhe de serializacao que ninguem prometeu.
    """
    ev = res.get("events") or {}
    out = []
    for epoch, d in (ev.get("dividends") or {}).items():
        try:
            quando = int(d.get("date") or epoch)
        except (TypeError, ValueError):
            continue
        out.append({"data": date_str(quando), "tipo": "dividendo",
                    "valor": float(d.get("amount") or 0.0),
                    "numerador": None, "denominador": None, "razao": None})
    for epoch, d in (ev.get("splits") or {}).items():
        try:
            quando = int(d.get("date") or epoch)
        except (TypeError, ValueError):
            continue
        num, den = d.get("numerator"), d.get("denominator")
        out.append({"data": date_str(quando), "tipo": "desdobramento",
                    "valor": None,
                    "numerador": float(num) if num else None,
                    "denominador": float(den) if den else None,
                    "razao": d.get("splitRatio")})
    out.sort(key=lambda x: (x["data"], x["tipo"]))
    return out


def meta(res: dict) -> dict:
    m = res.get("meta") or {}
    return {"nome": m.get("longName") or m.get("shortName"),
            "moeda": m.get("currency"), "bolsa": m.get("exchangeName"),
            "tipo": m.get("instrumentType"),
            "primeiro_negocio": (date_str(int(m["firstTradeDate"]))
                                 if m.get("firstTradeDate") else None),
            "intervalos_validos": m.get("validRanges") or []}


# ---------------------------------------------------------------- coleta -----
def diario(ticker: str) -> tuple[list[dict], list[dict], dict]:
    """Serie diaria INTEIRA numa requisicao, mais proventos e metadados."""
    res = _pega(ticker, "1d", 0, PERIOD2_TETO)
    if not res or res.get("_erro"):
        return [], [], {"erro": (res or {}).get("_erro", "sem resposta")}
    return mapeia_barras(res, diario=True), mapeia_eventos(res), meta(res)


def intradiario(ticker: str, intervalo: str, janelas_max: int = 400,
                ate: int | None = None, verbose: bool = False
                ) -> tuple[list[dict], dict]:
    """Serie intradiaria DESLIZANDO a janela para tras ate ela secar.

    Cada requisicao cobre `JANELA_DIAS[intervalo]` dias; a seguinte pede o
    bloco imediatamente anterior. Para quando `JANELAS_VAZIAS_PARA_PARAR`
    janelas CONSECUTIVAS voltam sem barra -- consecutivas, e nao a primeira,
    porque uma janela pode cair inteira em recesso ou em um trecho sem
    negocio sem que a serie tenha acabado. E a mesma licao da paginacao da
    UOL, onde a pagina 32 veio vazia e as de 34 a 39 vieram cheias.

    `janelas_max` e um teto de seguranca: 1m com janela de 8 dias levaria 46
    requisicoes por ano de historico, e sem teto um papel com erro de
    paginacao renderia requisicao infinita.
    """
    dias = JANELA_DIAS.get(intervalo)
    if dias is None:
        raise ValueError(f"intervalo {intervalo!r} nao desliza; use diario()")
    fim = int(ate if ate is not None else now_ts())
    vistos: dict[int, dict] = {}
    vazias = 0
    pedidas = 0
    erro = None
    mais_antiga = None
    for _ in range(janelas_max):
        ini = fim - dias * DIA_S
        res = _pega(ticker, intervalo, max(ini, 0), fim)
        pedidas += 1
        time.sleep(PAUSA_S)
        if res and res.get("_erro"):
            erro = res["_erro"]
            break
        barras = mapeia_barras(res, diario=False) if res else []
        novas = [b for b in barras if b["ts"] not in vistos]
        for b in barras:
            vistos.setdefault(b["ts"], b)
        if verbose:
            print(f"    [{intervalo}] {date_str(max(ini, 0))} -> "
                  f"{date_str(fim)}: {len(barras)} barras "
                  f"({len(novas)} novas)")
        if not barras:
            vazias += 1
            if vazias >= JANELAS_VAZIAS_PARA_PARAR:
                break
        else:
            vazias = 0
            mais_antiga = min(b["ts"] for b in barras)
        fim = max(ini, 0)
        if fim == 0:
            break
    ser = sorted(vistos.values(), key=lambda b: b["ts"])
    rel = {"janelas_pedidas": pedidas, "barras": len(ser),
           "mais_antiga": date_str(mais_antiga) if mais_antiga else None,
           "erro": erro}
    return ser, rel


# ----------------------------------------------------------- persistencia ----
def grava_proventos(ticker: str, eventos: list[dict]) -> int:
    con = connect()
    n = 0
    with con:
        for e in eventos:
            cur = con.execute(
                "INSERT OR REPLACE INTO proventos"
                "(ticker,data,tipo,valor,numerador,denominador,razao,origem,visto_ts)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (ticker, e["data"], e["tipo"], e["valor"], e["numerador"],
                 e["denominador"], e["razao"], NOME, now_ts()))
            n += cur.rowcount
    con.close()
    return n


def grava_cadastro(ticker: str, m: dict, barras: int,
                   ultima: str | None, status: str, motivo: str) -> None:
    """Reusa a tabela `ativos`, que a UOL criou. Mesma pergunta, mesma tabela:
    quem existe, de onde, com quanta serie, e quando foi conferido."""
    con = connect()
    with con:
        con.execute(
            "INSERT OR REPLACE INTO ativos"
            "(ticker,fonte,id_externo,nome,categoria,status,barras,"
            " ultima_barra,motivo,sondado_ts,visto_ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ticker, NOME, _simbolo(ticker), m.get("nome"),
             m.get("tipo") or "acao", status, barras, ultima, motivo,
             now_ts(), now_ts()))
    con.close()


def grava_intraday(ticker: str, intervalo: str, barras: list[dict]) -> int:
    from . import intraday as intra
    con = connect()
    intra.init(con)
    n = 0
    with con:
        for b in barras:
            cur = con.execute(
                "INSERT OR REPLACE INTO intraday"
                "(simbolo,intervalo,ts,close,volume,origem)"
                " VALUES (?,?,?,?,?,?)",
                (ticker, intervalo, b["ts"], b["close"], b.get("volume"), NOME))
            n += cur.rowcount
    con.close()
    return n


# --------------------------------------------------------- orquestracao ------
def coletar_diario(tickers: list[str] | None = None, complementar: bool = True,
                   verbose: bool = True) -> dict:
    """Historico diario COMPLETO de cada papel, numa requisicao por papel.

    `complementar=True` por padrao, pela mesma razao da UOL: as 24.920 barras
    que o banco ja tinha nao tem procedencia registrada (origem='legado') e
    nao e para serem trocadas por um download sem que alguem decida isso. O
    que falta entra; o que existe recebe o OHLCV vazio e o `adjclose`, e o
    fechamento fica.
    """
    from . import config, prices
    alvos = [t.upper() for t in (tickers or config.universo())]
    if verbose:
        print(f"{len(alvos)} papel(is), historico diario completo "
              f"(period1=0, uma requisicao cada)")

    def _um(t):
        return (t,) + diario(t)

    series, provs, falhas, metas = {}, 0, [], {}
    with cf.ThreadPoolExecutor(max_workers=PARALELO) as pool:
        for i, (t, barras, eventos, m) in enumerate(pool.map(_um, alvos), 1):
            if m.get("erro") or not barras:
                falhas.append((t, m.get("erro") or "serie vazia"))
                grava_cadastro(t, m, 0, None, "sem_dado",
                               m.get("erro") or "serie vazia")
                continue
            series[t] = barras
            metas[t] = m
            provs += grava_proventos(t, eventos)
            grava_cadastro(t, m, len(barras), barras[-1]["date"], "ativo",
                           f"{len(barras)} barras desde {barras[0]['date']}")
            if verbose and (i % 10 == 0 or i == len(alvos)):
                print(f"  [yahoo] {i}/{len(alvos)}")

    div = prices.divergencia(series, NOME) if complementar else []
    n = prices.grava_diario(series, NOME, complementar=complementar)
    if verbose:
        print(f"-> {len(series)} papeis, {n} barras gravadas"
              f"{' (complementando)' if complementar else ' (substituindo)'}, "
              f"{provs} proventos/desdobramentos")
        if falhas:
            print(f"\nSEM SERIE ({len(falhas)}) -- confira se algum papel bom "
                  f"caiu aqui:")
            for t, m in falhas:
                print(f"   {t:<10}{m}")
        prices.imprime_divergencia(div, csv="data/divergencia_yahoo.csv")
    return {"papeis": len(series), "barras": n, "proventos": provs,
            "falhas": falhas, "divergencias": div, "meta": metas}


def coletar_intraday(tickers: list[str] | None = None,
                     intervalos: tuple[str, ...] = ("1h", "15m", "5m", "1m"),
                     janelas_max: int = 400, verbose: bool = True) -> dict:
    """Intradiario de cada papel em cada intervalo, deslizando a janela.

    ORDEM DOS INTERVALOS IMPORTA PARA O CUSTO, nao para o resultado: 1h cobre
    720 dias por requisicao e 1m cobre 8. Comecar pelo grosso significa que,
    se a coleta for interrompida, o que ficou no banco e a parte com mais
    alcance por requisicao gasta.
    """
    from . import config
    alvos = [t.upper() for t in (tickers or config.universo())]
    total = {}
    relatos = []
    for intervalo in intervalos:
        if JANELA_DIAS.get(intervalo) is None:
            print(f"  [yahoo] {intervalo} nao e intradiario; pulando")
            continue
        if verbose:
            print(f"\n{intervalo}: janela de {JANELA_DIAS[intervalo]} dias por "
                  f"requisicao, deslizando para tras ate secar")

        def _um(t, _i=intervalo):
            return (t,) + intradiario(t, _i, janelas_max=janelas_max)

        n_int = 0
        with cf.ThreadPoolExecutor(max_workers=PARALELO) as pool:
            for k, (t, barras, rel) in enumerate(pool.map(_um, alvos), 1):
                if barras:
                    n_int += grava_intraday(t, intervalo, barras)
                relatos.append({"ticker": t, "intervalo": intervalo, **rel})
                if verbose and (k % 10 == 0 or k == len(alvos)):
                    print(f"  [yahoo] {intervalo} {k}/{len(alvos)}  "
                          f"{n_int} barras")
        total[intervalo] = n_int
        if verbose:
            alcance = [r["mais_antiga"] for r in relatos
                       if r["intervalo"] == intervalo and r["mais_antiga"]]
            if alcance:
                print(f"  -> {n_int} barras; a mais antiga de todas e "
                      f"{min(alcance)} (ALCANCE MEDIDO, nao prometido)")
    return {"por_intervalo": total, "relatos": relatos}


def estado() -> dict:
    con = connect()
    out = {}
    out["papeis_com_diario"] = con.execute(
        "SELECT COUNT(DISTINCT ticker) FROM prices WHERE origem=? OR "
        "origem_ohlc LIKE ?", (NOME, f"%{NOME}%")).fetchone()[0]
    out["com_adjclose"] = con.execute(
        "SELECT COUNT(*) FROM prices WHERE adjclose IS NOT NULL").fetchone()[0]
    out["proventos"] = {
        r["tipo"]: r["n"] for r in con.execute(
            "SELECT tipo, COUNT(*) n FROM proventos GROUP BY 1")}
    out["por_intervalo"] = {
        r["intervalo"]: r["n"] for r in con.execute(
            "SELECT intervalo, COUNT(*) n FROM intraday WHERE origem=? "
            "GROUP BY 1", (NOME,))}
    out["sem_dado"] = [dict(r) for r in con.execute(
        "SELECT ticker, motivo FROM ativos WHERE fonte=? AND status!='ativo' "
        "ORDER BY ticker", (NOME,))]
    con.close()
    return out


# ------------------------------------------------------- conferir o ajuste ---
def conferir_ajuste(ticker: str, limiar: float = 0.25) -> dict:
    """Num desdobramento conhecido, a serie AJUSTADA nao salta e a crua salta.

    E o teste que a armadilha 3 de obs/uol.py pedia e nao tinha como rodar,
    porque faltava data de desdobramento. Agora ela vem em `events.splits`.

    Le o banco, nao a rede. Devolve, para cada desdobramento registrado, a
    variacao de `close` e de `adjclose` no dia -- e um veredito por serie.
    """
    con = connect()
    splits = con.execute(
        "SELECT data, razao FROM proventos WHERE ticker=? AND "
        "tipo='desdobramento' ORDER BY data", (ticker,)).fetchall()
    casos = []
    for s in splits:
        viz = con.execute(
            "SELECT date, close, adjclose FROM prices WHERE ticker=? AND "
            "date <= ? ORDER BY date DESC LIMIT 2", (ticker, s["data"])
        ).fetchall()
        if len(viz) < 2:
            continue
        dep, ant = dict(viz[0]), dict(viz[1])

        def _var(a, b):
            return None if not a or not b else abs(b / a - 1.0)
        casos.append({
            "data": s["data"], "razao": s["razao"],
            "var_close": _var(ant["close"], dep["close"]),
            "var_adjclose": _var(ant["adjclose"], dep["adjclose"])})
    con.close()

    def _saltou(chave):
        vs = [c[chave] for c in casos if c[chave] is not None]
        return any(v >= limiar for v in vs) if vs else None
    return {"ticker": ticker, "desdobramentos": len(splits), "casos": casos,
            "close_salta": _saltou("var_close"),
            "adjclose_salta": _saltou("var_adjclose")}
