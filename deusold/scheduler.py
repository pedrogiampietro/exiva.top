"""Scheduler para rodar dentro do container `collector` (substitui o Agendador do Windows).

- No 1º start com banco vazio: faz backfill (mortes 40 págs + guilds + exp).
- A cada 15 min: mortes novas + resolve guild dos players.
- 1x/dia (~10:05, após o site atualizar às 10:00): snapshot de experiência.

Config por env:
    FREQUENT_MINUTES (default 15), EXP_HOUR (10), EXP_MINUTE (10), WORLD_FILTER (1)
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, db
from .client import DeusoldClient
from .collect import collect_characters, collect_deaths, collect_exp, collect_guilds

FREQUENT_SECS = int(os.environ.get("FREQUENT_MINUTES", "15")) * 60
EXP_HOUR = int(os.environ.get("EXP_HOUR", "10"))
EXP_MINUTE = int(os.environ.get("EXP_MINUTE", "10"))
WORLD = os.environ.get("WORLD_FILTER", "1")


def _log(msg: str) -> None:
    print(f"{datetime.now(ZoneInfo(config.SERVER_TZ)).isoformat()}  {msg}", flush=True)


def main() -> None:
    engine = db.get_engine()
    db.init_db(engine)
    _log(f"[scheduler] iniciado (dialeto={engine.dialect.name})")

    with DeusoldClient() as client:
        if db.stats(engine)["deaths"] == 0:
            _log("[scheduler] banco vazio → backfill inicial")
            collect_deaths(client, engine, 40, None)
            collect_guilds(client, engine)
            collect_exp(client, engine, 12, WORLD)

        next_frequent = 0.0
        last_exp_day: str | None = None

        while True:
            now = time.monotonic()
            tznow = datetime.now(ZoneInfo(config.SERVER_TZ))

            if now >= next_frequent:
                try:
                    _log("[scheduler] rodada frequente")
                    collect_deaths(client, engine, 5, None)
                    collect_characters(client, engine, 100)
                except Exception as exc:  # nunca derruba o loop
                    _log(f"[scheduler] erro na frequente: {exc}")
                next_frequent = now + FREQUENT_SECS

            past_exp_time = (tznow.hour, tznow.minute) >= (EXP_HOUR, EXP_MINUTE)
            today = tznow.strftime("%Y-%m-%d")
            if past_exp_time and last_exp_day != today:
                try:
                    _log("[scheduler] snapshot diário de exp")
                    collect_exp(client, engine, 12, WORLD)
                    last_exp_day = today
                except Exception as exc:
                    _log(f"[scheduler] erro no exp: {exc}")

            time.sleep(60)


if __name__ == "__main__":
    main()
