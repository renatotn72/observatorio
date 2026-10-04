"""Universo CVM/CSV. Cadastro CVM identifica emissor, não liquidez.

A ativação de 150-300 ações exige filtro posterior por volume financeiro, histórico,
preço disponível e regras de investibilidade.
"""
from __future__ import annotations
import csv
import time
from pathlib import Path
from . import config
from .util import http_get

CVM_CAD = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
OUT = config.DATA_DIR / "universe_cvm.csv"


def fetch_cvm() -> dict:
    r = http_get(CVM_CAD)
    if r is None:
        raise RuntimeError("falha ao baixar cadastro CVM")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(r.content)
    # CSV é separado por ; e tipicamente latin-1.
    text = r.content.decode("latin-1", errors="replace").splitlines()
    rows = list(csv.DictReader(text, delimiter=";"))
    ativos = [x for x in rows if (x.get("SIT") or "").upper() in ("ATIVO", "FASE PRÉ-OPERACIONAL")]
    return {"arquivo": str(OUT), "total": len(rows), "ativos": len(ativos),
            "nota": "CVM fornece cadastro/CNPJ; ticker e liquidez exigem reconciliação adicional."}


def import_csv(path: str | Path) -> dict:
    """CSV de universo: ticker,nome,cnpj,setor,volume_medio.
    Gera config/universe_candidates.csv, sem substituir a watchlist ativa.
    """
    src = Path(path)
    if not src.is_file(): raise FileNotFoundError(src)
    out = config.ROOT / "config" / "universe_candidates.csv"
    rows = list(csv.DictReader(src.open(encoding="utf-8-sig", newline="")))
    required = {"ticker", "nome"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("CSV requer ao menos ticker,nome")
    clean = []
    for r in rows:
        t = r["ticker"].upper().strip()
        if len(t) >= 5 and t[:4].isalpha() and t[4:].isdigit():
            clean.append({k: (v or "").strip() for k,v in r.items()})
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(clean[0]) if clean else ["ticker","nome"])
        w.writeheader(); w.writerows(clean)
    return {"candidatas":len(clean),"arquivo":str(out),
            "nota":"lista importada; ative somente após filtro por liquidez e histórico."}
