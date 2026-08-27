"""Configuração central do coletor."""
from __future__ import annotations

import os
from pathlib import Path

BASE_URL = "https://deusold.com"

# Caminho do banco SQLite (data/ é ignorado pelo git).
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "deusold.db"


def database_url() -> str:
    """URL do banco (SQLAlchemy). Prod: defina DATABASE_URL (Postgres).
    Local: default = arquivo SQLite em data/deusold.db.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # normaliza o esquema antigo do Heroku/Railway
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url
    return f"sqlite:///{DB_PATH.as_posix()}"

# Headers de navegador: um request "cru" recebe 200 do Cloudflare deste site,
# desde que o User-Agent pareça um navegador real. Sem isso pode tomar challenge.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Educação com o servidor: pausa entre requests (segundos).
REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3

# Fuso do servidor (os horários das mortes vêm sem tz explícito).
SERVER_TZ = "America/Sao_Paulo"  # Brasília (UTC-3), conforme "Brasilia Time" no site.
