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
  PRIMARY KEY (ticker, date)
);

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
    return feitas


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
