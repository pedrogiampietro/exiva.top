"""Coletor CLI: puxa mortes, guilds, ranking (exp) e fichas de personagem.

Uso:
    python -m deusold.collect all               # tudo (mortes, guilds, exp, chars)
    python -m deusold.collect deaths --pages 40
    python -m deusold.collect guilds
    python -m deusold.collect exp --pages 12     # snapshot de experiência do dia
    python -m deusold.collect characters --limit 150  # resolve guild dos players
"""
from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, db, parse
from .client import DeusoldClient


def server_today() -> str:
    return datetime.now(ZoneInfo(config.SERVER_TZ)).strftime("%Y-%m-%d")


def collect_deaths(client: DeusoldClient, conn, pages: int, world_filter: str | None) -> None:
    print(f"[mortes] coletando até {pages} página(s)...")
    total_new = 0
    for page in range(1, pages + 1):
        params = {"page": page}
        if world_filter:
            params["world_filter"] = world_filter
        deaths = parse.parse_deaths(client.get("/community/deaths", params=params))
        if not deaths:
            print(f"  página {page}: vazia, parando.")
            break
        new = db.upsert_deaths(conn, deaths)
        total_new += new
        print(f"  página {page}: {len(deaths)} lidas, {new} novas")
    print(f"[mortes] concluído. {total_new} mortes inéditas.")


def collect_guilds(client: DeusoldClient, conn) -> None:
    print("[guilds] descobrindo guilds...")
    ids = parse.parse_guild_ids(client.get("/community/guilds"))
    print(f"[guilds] {len(ids)} guilds. Coletando membros...")
    for i, gid in enumerate(ids, 1):
        name, members = parse.parse_guild_page(client.get(f"/community/guild/{gid}"))
        db.upsert_guild(conn, gid, name, members)
    print("[guilds] concluído.")


def collect_exp(client: DeusoldClient, conn, pages: int, world_filter: str) -> None:
    day = server_today()
    print(f"[exp] snapshot de {day}, até {pages} página(s) do ranking...")
    total = 0
    for page in range(1, pages + 1):
        rows = parse.parse_highscores(client.get("/ranking", params={
            "skill_filter": "level", "world_filter": world_filter, "page": page,
        }))
        if not rows:
            print(f"  página {page}: vazia, parando.")
            break
        n = db.upsert_experience(conn, rows, day)
        total += n
        print(f"  página {page}: {n} jogadores")
    print(f"[exp] concluído. {total} registros no snapshot de {day}.")


def collect_characters(client: DeusoldClient, conn, limit: int) -> None:
    pending = db.players_needing_guild(conn)
    todo = pending[:limit]
    print(f"[chars] {len(pending)} pendentes; resolvendo {len(todo)} nesta rodada...")
    for i, name in enumerate(todo, 1):
        ch = parse.parse_character(client.get(f"/character/{name}"))
        if not ch.get("name"):
            ch["name"] = name  # garante gravação mesmo se a ficha não parsear o nome
        db.upsert_character(conn, ch)
        if i % 25 == 0:
            print(f"  ({i}/{len(todo)})")
    print(f"[chars] concluído. {len(todo)} personagens resolvidos.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor de dados do DeusOLD")
    ap.add_argument("command",
                    choices=["all", "deaths", "guilds", "exp", "characters"],
                    nargs="?", default="all")
    ap.add_argument("--pages", type=int, default=10, help="páginas de mortes/ranking")
    ap.add_argument("--limit", type=int, default=150, help="máx. personagens por rodada")
    ap.add_argument("--world", default="1", help="world_filter (1 = Memorium)")
    args = ap.parse_args()

    conn = db.connect()
    db.init_db(conn)

    with DeusoldClient() as client:
        if args.command in ("all", "deaths"):
            collect_deaths(client, conn, args.pages, None)
        if args.command in ("all", "guilds"):
            collect_guilds(client, conn)
        if args.command in ("all", "exp"):
            collect_exp(client, conn, max(args.pages, 12), args.world)
        if args.command in ("all", "characters"):
            collect_characters(client, conn, args.limit)

    s = db.stats(conn)
    print(f"\n[banco] mortes={s['deaths']} guilds={s['guilds']} membros={s['members']} "
          f"chars={s['characters']} exp_snaps={s['exp_rows']}({s['exp_days']} dias)")


if __name__ == "__main__":
    main()
