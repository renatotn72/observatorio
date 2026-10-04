"""Entrega de alarme: console, arquivo, Telegram (opcional), notify-send."""
from __future__ import annotations
import pathlib
import shutil
import subprocess

from . import config
from .config import ROOT, resolve_env
from .util import http_get, iso


def console(ev: dict) -> None:
    print("  !! " + ev["message"])


def to_file(ev: dict) -> None:
    cfg = config.alarms().get("notify", {})
    path = ROOT / cfg.get("file_path", "data/alarms.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{iso(ev['ts'])}\t{ev['message']}\n")


def desktop(ev: dict) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", f"Observatorio: {ev['ticker']}", ev["message"]],
                       check=False)


def telegram(ev: dict) -> None:
    cfg = (config.alarms().get("notify", {}) or {}).get("telegram")
    if not cfg:
        return
    token = resolve_env(cfg.get("bot_token"))
    chat = resolve_env(cfg.get("chat_id"))
    if not token or not chat:
        return
    http_get(f"https://api.telegram.org/bot{token}/sendMessage",
             params={"chat_id": chat, "text": ev["message"]})


CHANNELS = {"console": console, "file": to_file, "desktop": desktop, "telegram": telegram}


def deliver(events: list[dict]) -> None:
    for ev in events:
        for ch in ev.get("channels", ["console"]):
            fn = CHANNELS.get(ch)
            if fn:
                try:
                    fn(ev)
                except Exception as exc:                      # noqa: BLE001
                    print(f"  [notify:{ch}] falhou: {exc}")
