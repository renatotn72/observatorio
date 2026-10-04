"""Carregamento de configuracao."""
from __future__ import annotations
import os
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
# OBS_DB existe para rodar contra banco ISOLADO (verificacao de caminho em
# scripts/test_*.py). Sem ela, um teste que grava score ou job escreveria no
# banco de medicao -- e dado de teste misturado com dado de medicao e
# exatamente a categoria 4 de obs/limpeza.py.
DB_PATH = (pathlib.Path(os.environ["OBS_DB"]).expanduser()
           if os.environ.get("OBS_DB") else DATA_DIR / "observatorio.db")


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def watchlist() -> dict:
    return _load("watchlist.yml")


def tickers() -> dict:
    return watchlist().get("tickers", {})


def sources() -> dict:
    return _load("sources.yml")


def alarms() -> dict:
    return _load("alarms.yml")


def resolve_env(val):
    """Permite 'env:NOME_DA_VAR' nos YAMLs para nao versionar segredo."""
    if isinstance(val, str) and val.startswith("env:"):
        return os.environ.get(val[4:], "")
    return val
