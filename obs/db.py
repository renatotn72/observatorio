"""Esquema SQLite. Um arquivo, zero servidor -- trocavel por Postgres depois."""
from __future__ import annotations
import sqlite3

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id           INTEGER PRIMARY KEY,
  url          TEXT UNIQUE NOT NULL,
  title        TEXT NOT NULL,
  body         TEXT,
  domain       TEXT,
  lang         TEXT,
  published_ts INTEGER NOT NULL,   -- timestamp de PUBLICACAO (point-in-time)
  ingested_ts  INTEGER NOT NULL,   -- quando NOS vimos (detecta atraso da fonte)
  source       TEXT,               -- gdelt | rss
  simhash      INTEGER,
  cluster_id   INTEGER             -- grupo de quase-duplicatas
);
CREATE INDEX IF NOT EXISTS ix_art_pub ON articles(published_ts);
CREATE INDEX IF NOT EXISTS ix_art_cluster ON articles(cluster_id);

-- Uma mencao pode vir do NOME da empresa ou de um DRIVER que ela escuta
-- (roteamento). As colunas de driver ficam NULL no primeiro caso.
--   driver       : qual assunto trouxe a materia (BRENT, DXY, ...)
--   peso_driver  : o `share` daquele driver na cadeia de afetacao do papel
--   sinal_driver : +1 ou -1, o sinal do beta -- noticia boa para o petroleo
--                  e boa para PETR4 (+) e ruim para quem consome (-)
CREATE TABLE IF NOT EXISTS mentions (
  article_id    INTEGER NOT NULL REFERENCES articles(id),
  ticker        TEXT NOT NULL,
  relevance     REAL NOT NULL,     -- 0..1: a noticia e DE FATO sobre a empresa?
  matched_alias TEXT,
  driver        TEXT,
  peso_driver   REAL,
  sinal_driver  INTEGER,
  PRIMARY KEY (article_id, ticker)
);
CREATE INDEX IF NOT EXISTS ix_men_ticker ON mentions(ticker);

CREATE TABLE IF NOT EXISTS scores (
  article_id INTEGER NOT NULL REFERENCES articles(id),
  ticker     TEXT NOT NULL,
  scorer     TEXT NOT NULL,        -- lexicon | llm | ensemble
  s          REAL NOT NULL,        -- direcao -1..+1
  magnitude  REAL NOT NULL,        -- 0..1 materialidade
  event_type TEXT,                  -- legado: mantido para nao quebrar medicao
  tipo_evento TEXT,                 -- corporativo|macro|judicial|legislativo|calendario
  orientacao TEXT,                  -- conjunto ordenado: "futuro,passado"
  novelty    REAL NOT NULL,        -- 1.0 primeira reportagem, decai em repercussao
  -- EXTRACAO ESTRUTURADA (preenchida so pelo scorer que LE o texto).
  -- Em coluna, e nao enterrada no `raw`, por um motivo so: feature que nao da
  -- para consultar nao da para medir. O ganho incremental do canal de texto
  -- exige cruzar `ja_precificado` e `is_rumor` com retorno realizado, e isso
  -- e um GROUP BY -- nao um json_extract em 50 mil linhas.
  -- O lexico deixa as quatro em NULL, e esse NULL e informativo: e exatamente
  -- o que contagem de palavras nao tem como responder.
  papel_no_fato  TEXT,              -- beneficiada|prejudicada|neutra|apenas_citada
  ja_precificado INTEGER,           -- 1 = rotina, etapa procedimental, retrospectiva
  is_rumor       INTEGER,           -- 1 = boato, fonte anonima, especulacao
  quote          TEXT,              -- trecho do texto que sustenta a nota
  raw        TEXT,
  PRIMARY KEY (article_id, ticker, scorer)
);

CREATE TABLE IF NOT EXISTS signals (
  ticker     TEXT NOT NULL,
  asof_ts    INTEGER NOT NULL,
  z          REAL NOT NULL,        -- sinal bruto agregado
  n_eff      REAL NOT NULL,        -- evidencia efetiva (soma de pesos)
  dispersion REAL NOT NULL,        -- discordancia entre fontes
  p_up       REAL, p_flat REAL, p_down REAL,
  base_up    REAL, base_flat REAL, base_down REAL,
  calibrated INTEGER NOT NULL DEFAULT 0,
  n_articles INTEGER NOT NULL DEFAULT 0,
  -- cabeca de VOLATILIDADE: mesma linha, mesmas features, saida separada.
  -- p_vol = P(amanha ficar no top 20% de agitacao deste papel)
  p_vol      REAL,
  vol_base   REAL,
  vol_calib  INTEGER NOT NULL DEFAULT 0,
  -- QUAL LEITOR produziu este sinal. Sem a coluna, um backfill pontuado pelo
  -- lexico e uma rodada ao vivo pontuada pelo LLM ficam indistinguiveis na
  -- mesma tabela -- e o calibrador treina na mistura sem ninguem ver.
  scorer     TEXT,
  PRIMARY KEY (ticker, asof_ts)
);

CREATE TABLE IF NOT EXISTS prices (
  ticker TEXT NOT NULL,
  date   TEXT NOT NULL,
  close  REAL NOT NULL,
  -- OHLCV: nulo nas fontes que so dao fechamento (Yahoo, brapi). `volume` e o
  -- insumo de LIQUIDEZ, que e o filtro que docs/universo.md pede desde o
  -- inicio para ampliar o universo de 10 para 150-300 papeis.
  open   REAL, high REAL, low REAL, volume REAL,
  -- PROCEDENCIA POR BARRA, em DOIS campos. Sem isto, misturar fontes com
  -- regras de ajuste diferentes produz salto onde nao houve evento, e
  -- ninguem consegue dizer de onde veio o ponto torto.
  --   origem      = quem deu o FECHAMENTO (o numero que vira retorno)
  --   origem_ohlc = quem deu abertura/maxima/minima/volume
  -- Sao separados porque uma fonte pode COMPLEMENTAR a outra: a serie
  -- ajustada vem de uma, o volume vem de outra, e cada metade continua
  -- rastreavel. Um campo so obrigaria a escolher, e escolher aqui significa
  -- jogar fora dado bom.
  origem TEXT, origem_ohlc TEXT,
  PRIMARY KEY (ticker, date)
);

-- Cadastro de ativos negociados: ticker -> id interno da fonte -> estado.
-- Separado de `prices` porque o id e o status sao CADASTRO, nao serie: o id
-- nao muda a cada coleta e reextrai-lo por barra seria pagar scraping de
-- pagina para cada cotacao.
CREATE TABLE IF NOT EXISTS ativos (
  ticker       TEXT NOT NULL,
  -- de onde veio o id: uol, yahoo, ...
  -- A CHAVE E (ticker, fonte), NAO ticker. As fontes tem fatos de cadastro
  -- INDEPENDENTES sobre o mesmo papel: para a UOL o PETR4 e o id interno
  -- 6836, para o Yahoo e o simbolo PETR4.SA. Com chave so no ticker, a
  -- segunda fonte a sondar apagaria o id da primeira e a coleta dela
  -- passaria a pedir o id errado -- em silencio, porque a linha continua
  -- existindo e parecendo valida.
  fonte        TEXT NOT NULL,
  id_externo   TEXT,               -- data-id da UOL, simbolo .SA do Yahoo
  nome         TEXT,
  -- acao | bdr | etf_fii | outro. Guardada, nunca descartada: BDR fica de
  -- fora por padrao mas o usuario pode reincluir por opcao.
  categoria    TEXT NOT NULL,
  -- nao_sondado | ativo | sem_dado | descontinuado
  status       TEXT NOT NULL DEFAULT 'nao_sondado',
  barras       INTEGER,            -- quantas a sondagem encontrou
  ultima_barra TEXT,               -- data da mais recente
  motivo       TEXT,               -- por que caiu em sem_dado
  sondado_ts   INTEGER,            -- quando foi sondado (nao resondar < 30d)
  visto_ts     INTEGER,            -- quando apareceu no catalogo pela ultima vez
  PRIMARY KEY (ticker, fonte)
);
CREATE INDEX IF NOT EXISTS ix_ativos_cat ON ativos(categoria, status);

-- Proventos e desdobramentos, que `events=div|split` do chart v8 do Yahoo
-- entrega junto do preco (obs/yahoo.py).
--
-- POR QUE ISTO MERECE TABELA PROPRIA, e nao uma coluna em `prices`
-- Ela responde uma pergunta que o projeto nao conseguia responder: a serie
-- esta AJUSTADA por proventos? Ate agora docs/precos-fontes.md registrava o
-- ajuste da serie atual como "provavel", inferido de nao haver salto > 35% em
-- 10 anos -- inferencia, nao medicao. Com a DATA de cada desdobramento, o
-- teste e direto: no dia de um desdobramento 2:1, serie ajustada nao salta e
-- serie crua cai pela metade. E o teste que a armadilha 3 de obs/uol.py pedia
-- e que nao tinha como rodar por falta justamente destas datas.
CREATE TABLE IF NOT EXISTS proventos (
  ticker      TEXT NOT NULL,
  data        TEXT NOT NULL,       -- YYYY-MM-DD (data-ex / data do evento)
  tipo        TEXT NOT NULL,       -- dividendo | desdobramento
  valor       REAL,                -- dividendo: valor por acao
  numerador   REAL,                -- desdobramento: 2 em "2:1"
  denominador REAL,                -- desdobramento: 1 em "2:1"
  razao       TEXT,                -- "2:1", como a fonte escreve
  origem      TEXT,
  visto_ts    INTEGER,
  PRIMARY KEY (ticker, data, tipo)
);
CREATE INDEX IF NOT EXISTS ix_prov_tipo ON proventos(tipo, data);

-- Rotulos: retorno ANORMAL (vs benchmark) classificado em alta/neutro/queda
CREATE TABLE IF NOT EXISTS labels (
  ticker  TEXT NOT NULL,
  asof_ts INTEGER NOT NULL,
  horizon TEXT NOT NULL,           -- '1d' | '5d'
  car     REAL NOT NULL,
  sigma   REAL NOT NULL,
  cls     INTEGER NOT NULL,        -- +1 alta | 0 neutro | -1 queda
  PRIMARY KEY (ticker, asof_ts, horizon)
);

CREATE TABLE IF NOT EXISTS calibrators (
  name       TEXT PRIMARY KEY,     -- ex: 'up:1d', 'down:1d'
  payload    TEXT NOT NULL,        -- JSON: pontos da isotonica
  n          INTEGER NOT NULL,
  fitted_ts  INTEGER NOT NULL,
  metrics    TEXT
);

-- Cache das leituras do LLM. A chave inclui a VERSAO DO PROMPT: mudar o
-- prompt muda a resposta, logo invalida o cache em vez de servir leitura
-- velha com prompt novo.
--
-- POR QUE ISTO E ESTRUTURAL, E NAO OTIMIZACAO
-- `limpar --aplicar` apaga os scores e repontua; `backfill --sem-baixar`
-- reprocessa o banco inteiro. Com o lexico isso custava segundos. Com o LLM
-- custaria a corpus inteira em chamadas, a cada vez -- e o operador deixaria
-- de repontuar, que e a operacao que conserta regra errada.
CREATE TABLE IF NOT EXISTS llm_cache (
  chave     TEXT PRIMARY KEY,      -- sha256(versao_prompt|modelo|ticker|texto)
  modelo    TEXT NOT NULL,
  resposta  TEXT NOT NULL,         -- JSON cru devolvido pelo modelo
  criado_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alarm_events (
  id        INTEGER PRIMARY KEY,
  ts        INTEGER NOT NULL,
  ticker    TEXT NOT NULL,
  direction TEXT NOT NULL,
  p         REAL NOT NULL,
  base      REAL NOT NULL,
  edge      REAL NOT NULL,
  n_eff     REAL NOT NULL,
  message   TEXT NOT NULL,
  delivered TEXT
);
CREATE INDEX IF NOT EXISTS ix_alarm_ts ON alarm_events(ts);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _migra(con) -> list[str]:
    """Acrescenta colunas novas sem destruir banco existente."""
    feitas = []
    cols = {r["name"] for r in con.execute("PRAGMA table_info(mentions)")}
    for nome, tipo in (("driver", "TEXT"), ("peso_driver", "REAL"),
                       ("sinal_driver", "INTEGER")):
        if nome not in cols:
            con.execute(f"ALTER TABLE mentions ADD COLUMN {nome} {tipo}")
            feitas.append(f"mentions.{nome}")
    # Classificacao de evento em duas dimensoes (obs/evento.py). SEM `with`
    # proprio: `_migra` ja e chamada dentro de uma transacao aberta por init(),
    # e abrir outra aninhada levanta erro no sqlite3.
    cols = {r["name"] for r in con.execute("PRAGMA table_info(scores)")}
    for nome, tipo in (("tipo_evento", "TEXT"), ("orientacao", "TEXT"),
                       # extracao estruturada do leitor de notica (obs/score.py)
                       ("papel_no_fato", "TEXT"), ("ja_precificado", "INTEGER"),
                       ("is_rumor", "INTEGER"), ("quote", "TEXT")):
        if nome not in cols:
            con.execute(f"ALTER TABLE scores ADD COLUMN {nome} {tipo}")
            feitas.append(f"scores.{nome}")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(signals)")}
    if "scorer" not in cols:
        con.execute("ALTER TABLE signals ADD COLUMN scorer TEXT")
        feitas.append("signals.scorer")
    # OHLCV e procedencia nos precos (obs/prices.py, provedores por fonte)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(prices)")}
    for nome, tipo in (("open", "REAL"), ("high", "REAL"), ("low", "REAL"),
                       ("volume", "REAL"), ("origem", "TEXT"),
                       ("origem_ohlc", "TEXT"), ("adjclose", "REAL")):
        if nome not in cols:
            con.execute(f"ALTER TABLE prices ADD COLUMN {nome} {tipo}")
            feitas.append(f"prices.{nome}")
            if nome == "origem":
                # Barra gravada ANTES desta coluna existir nao tem como dizer
                # de qual fonte veio: `prices.sync` tentava brapi e caia para
                # Yahoo, e nada registrava qual atendeu cada papel. 'legado'
                # afirma so o que e verificavel -- "coletada antes de haver
                # registro de procedencia" -- e e melhor que NULL, que confunde
                # "sem registro" com "nunca preenchido".
                con.execute("UPDATE prices SET origem='legado' "
                            "WHERE origem IS NULL AND close IS NOT NULL")
            if nome == "origem_ohlc":
                # Quem gravou OHLCV antes desta coluna existir tambem deu o
                # fechamento -- a barra veio inteira de uma fonte so. Deixar
                # NULL faria a proxima fonte complementar reivindicar OHLCV
                # que nao e dela, e e exatamente a rastreabilidade que esta
                # coluna existe para dar.
                con.execute(
                    "UPDATE prices SET origem_ohlc = origem WHERE "
                    "origem IS NOT NULL AND origem_ohlc IS NULL AND ("
                    "open IS NOT NULL OR high IS NOT NULL OR "
                    "low IS NOT NULL OR volume IS NOT NULL)")
    # `intraday` e criada por obs/intraday.py, nao pelo SCHEMA daqui. Se ainda
    # nao existe, PRAGMA devolve vazio e o ALTER quebraria com "no such table".
    cols = {r["name"] for r in con.execute("PRAGMA table_info(intraday)")}
    if cols:
        # bid/ask vem na resposta da UOL e dao SPREAD, que e medida de
        # liquidez -- docs/canal-noticias.md pede "liquidez e spread estimado"
        # como feature de contexto e ate agora nao havia de onde tirar.
        for nome, tipo in (("volume", "REAL"), ("origem", "TEXT"),
                           ("bid", "REAL"), ("ask", "REAL")):
            if nome not in cols:
                con.execute(f"ALTER TABLE intraday ADD COLUMN {nome} {tipo}")
                feitas.append(f"intraday.{nome}")

    # `ativos` nasceu com PRIMARY KEY (ticker). Com duas fontes de cadastro --
    # UOL pelo data-id, Yahoo pelo simbolo .SA -- a segunda a sondar apagaria
    # o id da primeira, e a coleta dela passaria a pedir o id errado SEM
    # ERRO: a linha continua existindo e parecendo valida. A chave certa e
    # (ticker, fonte).
    #
    # SQLite nao troca PRIMARY KEY com ALTER, so recriando a tabela. Detecto
    # pelo PRAGMA (uma coluna marcada pk=1 em vez de duas) e recrio copiando
    # o conteudo, dentro da transacao que `init` ja abriu.
    pk = [r["name"] for r in con.execute("PRAGMA table_info(ativos)")
          if r["pk"]]
    if pk == ["ticker"]:
        con.execute("ALTER TABLE ativos RENAME TO ativos_antiga")
        con.executescript(_TRECHO_ATIVOS)
        con.execute(
            "INSERT OR REPLACE INTO ativos SELECT ticker, fonte, id_externo,"
            " nome, categoria, status, barras, ultima_barra, motivo,"
            " sondado_ts, visto_ts FROM ativos_antiga")
        con.execute("DROP TABLE ativos_antiga")
        feitas.append("ativos.PK -> (ticker, fonte)")
    return feitas


# Usado so pela migracao acima, para recriar `ativos` com a chave certa.
# Fica recortado do SCHEMA para nao haver duas definicoes divergindo.
_TRECHO_ATIVOS = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS ativos ("):
                        SCHEMA.index("CREATE INDEX IF NOT EXISTS ix_ativos_cat")
                        + len("CREATE INDEX IF NOT EXISTS ix_ativos_cat "
                              "ON ativos(categoria, status);")]


def init(verbose: bool = False) -> None:
    con = connect()
    with con:
        con.executescript(SCHEMA)
        feitas = _migra(con)
        # Esquemas auxiliares permanecem locais; não acionam IA nem rede.
        from . import reports, earnings
        reports.init(con)
        earnings.init(con)
    con.close()
    if verbose and feitas:
        print("  [db] colunas acrescentadas:", ", ".join(feitas))
