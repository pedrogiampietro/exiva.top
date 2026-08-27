"""Camada de persistência via SQLAlchemy Core. Roda em SQLite (local) e Postgres (prod).

O dialeto é escolhido pela DATABASE_URL (ver config.py). Timestamps são gravados como
texto ISO-8601 (UTC), portável entre os dois bancos e compatível com o SQLite existente.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (Column, Integer, MetaData, String, Table, create_engine,
                        func, select)
from sqlalchemy.engine import Engine

from . import config

metadata = MetaData()

deaths_t = Table(
    "deaths", metadata,
    Column("id", String, primary_key=True),
    Column("occurred_at", String, nullable=False, index=True),
    Column("victim", String, nullable=False, index=True),
    Column("victim_level", Integer),
    Column("world", String),
    Column("has_player_kill", Integer, nullable=False, default=0),
    Column("collected_at", String, nullable=False),
)

death_killers_t = Table(
    "death_killers", metadata,
    Column("death_id", String, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("killer_name", String, nullable=False, index=True),
    Column("is_player", Integer, nullable=False),
)

guilds_t = Table(
    "guilds", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", String),
    Column("collected_at", String, nullable=False),
)

guild_members_t = Table(
    "guild_members", metadata,
    Column("guild_id", Integer, primary_key=True),
    Column("character_name", String, primary_key=True, index=True),
    Column("guild_name", String),
    Column("vocation", String),
    Column("level", Integer),
    Column("rank", String),
    Column("collected_at", String, nullable=False),
)

experience_t = Table(
    "experience_snapshots", metadata,
    Column("character_name", String, primary_key=True),
    Column("snapshot_date", String, primary_key=True, index=True),
    Column("world", String),
    Column("vocation", String),
    Column("level", Integer),
    Column("experience", Integer, nullable=False),
    Column("collected_at", String, nullable=False),
)

characters_t = Table(
    "characters", metadata,
    Column("name", String, primary_key=True),
    Column("world", String),
    Column("level", Integer),
    Column("vocation", String),
    Column("guild_id", Integer),
    Column("guild_name", String, index=True),
    Column("resolved_at", String, nullable=False),
)

_ENGINE: Engine | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        url = config.database_url()
        if url.startswith("sqlite"):
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _ENGINE = create_engine(url, future=True, pool_pre_ping=True)
    return _ENGINE


# Compat: nome antigo usado pelo restante do código.
def connect() -> Engine:
    return get_engine()


def init_db(engine: Engine | None = None) -> None:
    metadata.create_all(engine or get_engine())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dialect_insert(engine: Engine):
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


# ------------------------------------------------------------------ upserts

def upsert_deaths(engine: Engine, deaths: list[dict]) -> int:
    insert = _dialect_insert(engine)
    now = _now()
    inserted = 0
    with engine.begin() as conn:
        for d in deaths:
            stmt = insert(deaths_t).values(
                id=d["id"], occurred_at=d["occurred_at"], victim=d["victim"],
                victim_level=d["victim_level"], world=d["world"],
                has_player_kill=int(d["has_player_kill"]), collected_at=now,
            ).on_conflict_do_nothing(index_elements=["id"])
            if conn.execute(stmt).rowcount:
                inserted += 1
                for pos, k in enumerate(d["killers"]):
                    conn.execute(insert(death_killers_t).values(
                        death_id=d["id"], position=pos, killer_name=k["name"],
                        is_player=int(k["is_player"]),
                    ).on_conflict_do_nothing(index_elements=["death_id", "position"]))
    return inserted


def upsert_guild(engine: Engine, guild_id: int, name: str | None,
                 members: list[dict]) -> None:
    insert = _dialect_insert(engine)
    now = _now()
    with engine.begin() as conn:
        conn.execute(insert(guilds_t).values(id=guild_id, name=name, collected_at=now)
                     .on_conflict_do_update(index_elements=["id"],
                                            set_={"name": name, "collected_at": now}))
        conn.execute(guild_members_t.delete().where(guild_members_t.c.guild_id == guild_id))
        for m in members:
            conn.execute(insert(guild_members_t).values(
                guild_id=guild_id, character_name=m["name"], guild_name=name,
                vocation=m.get("vocation"), level=m.get("level"), rank=m.get("rank"),
                collected_at=now,
            ).on_conflict_do_nothing(index_elements=["guild_id", "character_name"]))


def upsert_experience(engine: Engine, rows: list[dict], snapshot_date: str) -> int:
    insert = _dialect_insert(engine)
    now = _now()
    n = 0
    with engine.begin() as conn:
        for r in rows:
            if r.get("experience") is None:
                continue
            conn.execute(insert(experience_t).values(
                character_name=r["name"], snapshot_date=snapshot_date, world=r.get("world"),
                vocation=r.get("vocation"), level=r.get("level"),
                experience=r["experience"], collected_at=now,
            ).on_conflict_do_update(
                index_elements=["character_name", "snapshot_date"],
                set_={"experience": r["experience"], "level": r.get("level"),
                      "collected_at": now}))
            n += 1
    return n


def upsert_character(engine: Engine, ch: dict) -> None:
    insert = _dialect_insert(engine)
    now = _now()
    set_ = {"world": ch.get("world"), "level": ch.get("level"),
            "vocation": ch.get("vocation"), "guild_id": ch.get("guild_id"),
            "guild_name": ch.get("guild_name"), "resolved_at": now}
    with engine.begin() as conn:
        conn.execute(insert(characters_t).values(name=ch["name"], **set_)
                     .on_conflict_do_update(index_elements=["name"], set_=set_))


def players_needing_guild(engine: Engine, max_age_days: int = 7) -> list[str]:
    """Jogadores vistos em mortes sem guild resolvida (ou resolvida há muito tempo)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    sql = """
        WITH seen AS (
            SELECT victim AS name FROM deaths
            UNION
            SELECT killer_name FROM death_killers WHERE is_player = 1
        )
        SELECT s.name FROM seen s
        LEFT JOIN characters c ON c.name = s.name
        WHERE c.name IS NULL OR c.resolved_at < :cutoff
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        return [row[0] for row in conn.execute(text(sql), {"cutoff": cutoff})]


def stats(engine: Engine) -> dict:
    with engine.begin() as conn:
        deaths = conn.execute(select(
            func.count(), func.min(deaths_t.c.occurred_at), func.max(deaths_t.c.occurred_at)
        )).one()
        guilds = conn.execute(select(func.count()).select_from(guilds_t)).scalar()
        members = conn.execute(select(func.count()).select_from(guild_members_t)).scalar()
        chars = conn.execute(select(func.count()).select_from(characters_t)).scalar()
        exp_rows = conn.execute(select(func.count()).select_from(experience_t)).scalar()
        exp_days = conn.execute(
            select(func.count(func.distinct(experience_t.c.snapshot_date)))).scalar()
    return {
        "deaths": deaths[0], "period": (deaths[1], deaths[2]),
        "guilds": guilds, "members": members, "characters": chars,
        "exp_rows": exp_rows, "exp_days": exp_days,
    }
