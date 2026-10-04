"""Carregamento de configuracao."""
from __future__ import annotations
import os
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "observatorio.db"


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
