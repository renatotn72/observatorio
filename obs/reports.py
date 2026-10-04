"""Registro, visualização e análise de relatórios corporativos.

O módulo aceita PDFs locais e links da CVM/RI. Extração é local; a análise por
LLM só transmite texto para fora se OBS_ALLOW_EXTERNAL_LLM=1 estiver definido.
"""
from __future__ import annotations
import csv
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from . import config
from .db import connect
from .llm_client import chat_json, enabled

REPORTS_DIR = config.DATA_DIR / "reports"
TEXT_DIR = config.DATA_DIR / "report_text"

SCHEMA = """
CREATE TABLE IF NOT EXISTS report_documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 ticker TEXT NOT NULL,
 kind TEXT NOT NULL,
 period TEXT,
 report_date TEXT,
 filed_ts INTEGER,
 title TEXT,
 source_url TEXT,
 local_path TEXT,
 sha256 TEXT,
 pages INTEGER,
 chars INTEGER,
 status TEXT NOT NULL DEFAULT 'registered',
 meta TEXT,
 created_ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_ticker ON report_documents(ticker, filed_ts DESC);
CREATE TABLE IF NOT EXISTS report_ai_chunks (
 report_id INTEGER NOT NULL, chunk_index INTEGER NOT NULL, pages TEXT, status TEXT NOT NULL,
 payload TEXT, error TEXT, analyzed_ts INTEGER NOT NULL, PRIMARY KEY(report_id,chunk_index)
);
CREATE TABLE IF NOT EXISTS report_ai (
 report_id INTEGER PRIMARY KEY,
 analyzer TEXT NOT NULL,
 model TEXT,
 status TEXT NOT NULL,
 payload TEXT,
 error TEXT,
 analyzed_ts INTEGER NOT NULL
);
"""


def init(con=None) -> None:
    own = con is None
    con = con or connect()
    with con:
        con.executescript(SCHEMA)
    if own:
        con.close()


def _safe_ticker(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not re.fullmatch(r"[A-Z]{4}\d{1,2}", ticker):
        raise ValueError("ticker inválido")
    return ticker


def _relative(path: Path) -> str:
    return str(path.relative_to(config.DATA_DIR))


def _absolute(rel: str) -> Path:
    p = (config.DATA_DIR / rel).resolve()
    root = config.DATA_DIR.resolve()
    if root not in p.parents and p != root:
        raise ValueError("caminho fora de data/")
    return p


def add_local(ticker: str, file_path: str | Path, kind: str = "RI",
              period: str = "", report_date: str = "", title: str = "") -> int:
    ticker = _safe_ticker(ticker)
    src = Path(file_path)
    if not src.is_file():
        raise FileNotFoundError(src)
    if src.suffix.lower() != ".pdf":
        raise ValueError("somente PDF é aceito")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    dest_dir = REPORTS_DIR / ticker
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:16]}_{src.name}"
    if not dest.exists():
        shutil.copy2(src, dest)
    con = connect()
    init(con)
    with con:
        row = con.execute("SELECT id FROM report_documents WHERE sha256=? AND ticker=?",
                          (digest, ticker)).fetchone()
        if row:
            rid = int(row["id"])
        else:
            cur = con.execute("""INSERT INTO report_documents
                (ticker,kind,period,report_date,filed_ts,title,local_path,sha256,status,meta,created_ts)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ticker, kind.upper(), period, report_date, int(time.time()),
                 title or src.stem, _relative(dest), digest, "registered", "{}", int(time.time())))
            rid = int(cur.lastrowid)
    con.close()
    return rid


def add_url(ticker: str, url: str, kind: str = "CVM", period: str = "",
            report_date: str = "", title: str = "") -> int:
    """Registra URL oficial uma única vez por ticker; repetições atualizam metadados."""
    ticker = _safe_ticker(ticker)
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL inválida")
    con = connect(); init(con)
    with con:
        row = con.execute("SELECT id FROM report_documents WHERE ticker=? AND source_url=?",
                          (ticker, url)).fetchone()
        if row:
            rid = int(row["id"])
        else:
            cur = con.execute("""INSERT INTO report_documents
                (ticker,kind,period,report_date,filed_ts,title,source_url,status,meta,created_ts)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (ticker, kind.upper(), period, report_date, int(time.time()),
                 title or url, url, "remote", "{}", int(time.time())))
            rid = int(cur.lastrowid)
    con.close()
    return rid


def download_remote(report_id: int) -> dict:
    """Baixa automaticamente somente arquivos que se identificam como PDF.

    Páginas HTML permanecem registradas como URL remota: elas podem conter links
    adicionais, mas não são falsamente tratadas como relatório PDF.
    """
    from .util import http_get
    row = get_report(report_id)
    if not row or not row.get("source_url"):
        raise ValueError("relatório remoto não encontrado")
    res = http_get(row["source_url"])
    if res is None:
        return {"report_id": report_id, "downloaded": False, "reason": "falha HTTP"}
    blob = res.content
    ctype = (res.headers.get("content-type") or "").lower()
    is_pdf = blob[:4] == b"%PDF" or "application/pdf" in ctype
    if not is_pdf:
        con = connect(); init(con)
        with con:
            con.execute("UPDATE report_documents SET status=? WHERE id=?", ("remote_html", report_id))
        con.close()
        return {"report_id": report_id, "downloaded": False, "reason": "URL não retornou PDF"}
    digest = hashlib.sha256(blob).hexdigest()
    dest_dir = REPORTS_DIR / row["ticker"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:16]}_auto.pdf"
    dest.write_bytes(blob)
    con = connect(); init(con)
    with con:
        con.execute("""UPDATE report_documents
          SET local_path=?,sha256=?,status=?,filed_ts=?
          WHERE id=?""", (_relative(dest), digest, "downloaded", int(time.time()), report_id))
    con.close()
    return {"report_id": report_id, "downloaded": True, "path": _relative(dest),
            "bytes": len(blob)}
def list_reports(ticker: str, limit: int = 30) -> list[dict]:
    con = connect(); init(con)
    rows = con.execute("""SELECT d.*, a.status AS ai_status, a.payload AS ai_payload,
                          a.model AS ai_model, a.analyzed_ts
                          FROM report_documents d LEFT JOIN report_ai a ON a.report_id=d.id
                          WHERE d.ticker=? ORDER BY COALESCE(d.report_date,''), d.filed_ts DESC
                          LIMIT ?""", (_safe_ticker(ticker), limit)).fetchall()
    con.close()
    out = []
    for r in rows:
        x = dict(r)
        x["downloadable"] = bool(x.get("local_path"))
        x["ai"] = json.loads(x.pop("ai_payload")) if x.get("ai_payload") else None
        x.pop("sha256", None); x.pop("meta", None)
        out.append(x)
    return out


def get_report(report_id: int) -> dict | None:
    con = connect(); init(con)
    row = con.execute("SELECT * FROM report_documents WHERE id=?", (report_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def file_for_report(report_id: int) -> Path | None:
    row = get_report(report_id)
    if not row or not row.get("local_path"):
        return None
    p = _absolute(row["local_path"])
    return p if p.is_file() else None


def extract_text(report_id: int) -> dict:
    row = get_report(report_id)
    if not row:
        raise ValueError("relatório não encontrado")
    pdf = file_for_report(report_id)
    if not pdf:
        raise ValueError("relatório remoto: baixe/cadastre um PDF local primeiro")
    # pypdf quando existir; senao o extrator de stdlib (obs/pdftext.py), que
    # le streams Flate com zlib. Sem esse plano B o pipeline documental fica
    # parado em ambiente sem pip -- que e o caso aqui.
    from . import pdftext
    r = pdftext.extrai(str(pdf))
    text, n_pag, metodo, qual = r["texto"], r["paginas"], r["metodo"], r["qualidade"]
    if not text.strip():
        con = connect(); init(con)
        with con:
            con.execute("UPDATE report_documents SET status=? WHERE id=?",
                        ("sem_texto", report_id))
        con.close()
        return {"report_id": report_id, "pages": n_pag, "chars": 0,
                "metodo": metodo,
                "aviso": "nenhum texto extraido -- PDF provavelmente escaneado; "
                         "precisa de OCR antes de analisar"}
    pages = text.split("[PÁGINA ")
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = TEXT_DIR / f"report_{report_id}.txt"
    path.write_text(text, encoding="utf-8", errors="ignore")
    con = connect(); init(con)
    with con:
        con.execute("UPDATE report_documents SET pages=?,chars=?,status=? WHERE id=?",
                    (n_pag, len(text), "extracted", report_id))
    con.close()
    return {"report_id": report_id, "pages": n_pag, "chars": len(text),
            "metodo": metodo, "qualidade": qual, "text_path": _relative(path),
            "aviso": ("qualidade baixa: possivel PDF escaneado ou fonte exotica"
                      if qual < 0.6 else None)}


def _local_facts(text: str) -> dict:
    terms = ["receita líquida", "ebitda", "lucro líquido", "prejuízo", "dívida líquida",
             "fluxo de caixa", "guidance", "provisão", "contingência", "impairment"]
    low = text.lower()
    found = {t: len(re.findall(re.escape(t), low)) for t in terms}
    snippets = []
    for t, n in found.items():
        if n:
            i = low.find(t)
            snippets.append(text[max(0, i - 180):i + 450].replace("\n", " "))
    return {"modo": "local", "termos": found, "trechos": snippets[:8],
            "nota": "extração local por termos; não substitui análise contábil ou IA."}


SYSTEM = """Você é extrator documental financeiro. Use exclusivamente o texto fornecido.
Não use conhecimento externo, não recomende compra/venda e não preveja preço ou retorno.
Retorne JSON válido, cite páginas em toda afirmação e use null quando o texto não fornecer dado.
Campos: resumo, resultados_operacionais, guidance, riscos, itens_nao_recorrentes,
endividamento_caixa, sinais_positivos, sinais_negativos, perguntas_abertas,
numeros_mencionados, trechos_evidencia, confianca, limitacoes."""
def _chunks(text, size=12000):
    parts=[]; cur=""; pages=[]
    for piece in re.split(r"(?=\[PÁGINA \d+\])",text):
        if not piece.strip(): continue
        m=re.match(r"\[PÁGINA (\d+)\]",piece); pg=int(m.group(1)) if m else None
        if len(cur)+len(piece)>size and cur:
            parts.append({"pages":pages,"text":cur});cur="";pages=[]
        cur+=piece; pages+=([pg] if pg else [])
    if cur: parts.append({"pages":pages,"text":cur})
    return parts
def analyze(report_id: int, external: bool=False) -> dict:
    row=get_report(report_id)
    if not row: raise ValueError("relatório não encontrado")
    path=TEXT_DIR/f"report_{report_id}.txt"
    if not path.exists(): extract_text(report_id)
    text=path.read_text(encoding="utf-8",errors="ignore"); local=_local_facts(text)
    status=model=err=None
    if not external:
        payload={**local,"status":"local_only"};status="local_only"
    else:
        ok,reason=enabled()
        if not ok: payload={**local,"status":"blocked_external_llm","reason":reason};status="blocked";err=reason
        else:
            answers=[]; errors=[]; con=connect();init(con)
            for i,ch in enumerate(_chunks(text)):
                ans=chat_json(SYSTEM,f"Ticker: {row['ticker']}\nTipo: {row['kind']}\nPáginas: {ch['pages']}\n\n{ch['text']}")
                with con: con.execute("INSERT OR REPLACE INTO report_ai_chunks VALUES (?,?,?,?,?,?,?)",(report_id,i,json.dumps(ch["pages"]), "ok" if ans.get("ok") else "error",json.dumps(ans.get("data"),ensure_ascii=False) if ans.get("ok") else None,ans.get("error"),int(time.time())))
                if ans.get("ok"): answers.append(ans["data"]);model=ans.get("model")
                else: errors.append(ans.get("error"))
            con.close()
            if answers:
                synth=chat_json(SYSTEM,"Consolide os JSONs abaixo sem inventar fatos. Preserve páginas e conflitos.\n"+json.dumps(answers,ensure_ascii=False)[:50000])
                analysis=synth.get("data") if synth.get("ok") else {"chunks":answers,"sintese_erro":synth.get("error")}
                payload={**local,"status":"external_ai","analysis":analysis,"chunks_ok":len(answers),"chunks_error":len(errors),"external_data_sent":True};status="ok"
            else: payload={**local,"status":"external_error","reason":errors,"external_data_sent":True};status="error";err="; ".join(errors)
    con=connect();init(con)
    with con: con.execute("INSERT OR REPLACE INTO report_ai (report_id,analyzer,model,status,payload,error,analyzed_ts) VALUES (?,?,?,?,?,?,?)",(report_id,"report-v2-chunked",model,status,json.dumps(payload,ensure_ascii=False),err,int(time.time())))
    con.close();return payload
