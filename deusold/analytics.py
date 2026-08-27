"""Consultas analíticas sobre o banco. Retorna DataFrames prontos pro dashboard.

Regras de atribuição (guerra entre guilds):
- Uma MORTE conta como 1 "kill" para a guild inimiga se a vítima pertence a uma
  guild e pelo menos um matador-jogador pertence à guild oposta.
- O crédito de "top killer" vai para cada jogador que participou da morte.
- Vínculo nome->guild vem do snapshot mais recente de guild_members.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from . import db


def connect() -> Engine:
    """Retorna o engine SQLAlchemy (SQLite local ou Postgres, conforme DATABASE_URL)."""
    return db.get_engine()


def guild_options(conn: Engine) -> pd.DataFrame:
    """Guilds com contagem de membros, para os seletores."""
    return pd.read_sql_query(
        """SELECT g.name, COUNT(gm.character_name) AS members
           FROM guilds g LEFT JOIN guild_members gm ON gm.guild_id = g.id
           WHERE g.name IS NOT NULL
           GROUP BY g.id ORDER BY members DESC, g.name""",
        conn,
    )


def pvp_deaths(conn: Engine) -> pd.DataFrame:
    """Uma linha por (morte, matador-jogador), enriquecida com guild da vítima e do matador.

    Colunas: id, occurred_at (datetime), date, victim, victim_level, world,
    killer_name, victim_guild, killer_guild.
    """
    # Guild resolvida por /character (characters) tem prioridade sobre o roster
    # (guild_members); COALESCE combina as duas fontes.
    df = pd.read_sql_query(
        """SELECT d.id, d.occurred_at, d.victim, d.victim_level, d.world,
                  k.killer_name,
                  COALESCE(cv.guild_name, mv.guild_name) AS victim_guild,
                  COALESCE(ck.guild_name, mk.guild_name) AS killer_guild
           FROM deaths d
           JOIN death_killers k ON k.death_id = d.id AND k.is_player = 1
           LEFT JOIN characters    cv ON cv.name = d.victim
           LEFT JOIN guild_members mv ON mv.character_name = d.victim
           LEFT JOIN characters    ck ON ck.name = k.killer_name
           LEFT JOIN guild_members mk ON mk.character_name = k.killer_name""",
        conn,
    )
    if df.empty:
        df["occurred_at"] = pd.to_datetime([])
        df["date"] = []
        return df
    df["occurred_at"] = pd.to_datetime(df["occurred_at"])
    df["date"] = df["occurred_at"].dt.date
    return df


def name_guild_map(conn: Engine) -> pd.DataFrame:
    """Mapa nome->guild combinando characters (prioridade) e roster."""
    return pd.read_sql_query(
        """SELECT s.name, COALESCE(c.guild_name, m.guild_name) AS guild
           FROM (SELECT name FROM characters
                 UNION SELECT character_name FROM guild_members) s
           LEFT JOIN characters c ON c.name = s.name
           LEFT JOIN guild_members m ON m.character_name = s.name""",
        conn,
    )


def experience_frame(conn: Engine) -> pd.DataFrame:
    """Todos os snapshots de experiência (long)."""
    df = pd.read_sql_query(
        """SELECT character_name, snapshot_date, world, vocation, level, experience
           FROM experience_snapshots ORDER BY character_name, snapshot_date""",
        conn,
    )
    if df.empty:
        df["snapshot_date"] = pd.to_datetime([]).date
        return df
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    return df


def daily_exp(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona exp_gained = diferença de experiência vs. snapshot anterior do char.

    Só há valor onde existe um snapshot de dia anterior (precisa de >= 2 dias).
    """
    if df.empty:
        return df.assign(exp_gained=[])
    df = df.sort_values(["character_name", "snapshot_date"]).copy()
    df["exp_gained"] = df.groupby("character_name")["experience"].diff()
    return df


def power_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    """Ranking atual por experiência total (último snapshot de cada char)."""
    if df.empty:
        return df
    latest = df.sort_values("snapshot_date").groupby("character_name").tail(1)
    return latest.sort_values("experience", ascending=False).reset_index(drop=True)


def top_player_rivalries(df: pd.DataFrame, limit: int = 15,
                         require_bidirectional: bool = True) -> pd.DataFrame:
    """Maiores rivalidades entre jogadores (par não-ordenado A×B).

    Colunas: player_a, player_b, a_kills (A matou B), b_kills (B matou A), total.
    require_bidirectional: só pares onde os dois lados já se mataram.
    """
    if df.empty:
        return pd.DataFrame(columns=["player_a", "player_b", "a_kills", "b_kills", "total"])

    dc = (df[df["killer_name"] != df["victim"]]
          .groupby(["killer_name", "victim"])["id"].nunique()
          .reset_index(name="kills"))
    dc["pair"] = dc.apply(lambda r: tuple(sorted((r["killer_name"], r["victim"]))), axis=1)

    rows = []
    for (a, b), grp in dc.groupby("pair"):
        a_kills = int(grp.loc[grp["killer_name"] == a, "kills"].sum())
        b_kills = int(grp.loc[grp["killer_name"] == b, "kills"].sum())
        if require_bidirectional and (a_kills == 0 or b_kills == 0):
            continue
        # ordena para o lado com mais kills virar "player_a"
        if b_kills > a_kills:
            a, b, a_kills, b_kills = b, a, b_kills, a_kills
        rows.append({"player_a": a, "player_b": b,
                     "a_kills": a_kills, "b_kills": b_kills, "total": a_kills + b_kills})

    return (pd.DataFrame(rows).sort_values(["total", "a_kills"], ascending=False)
            .head(limit).reset_index(drop=True))


def players_in_pvp(df: pd.DataFrame) -> list[str]:
    """Lista ordenada de jogadores que aparecem em PvP (como matador ou vítima)."""
    if df.empty:
        return []
    names = pd.concat([df["killer_name"], df["victim"]]).dropna().unique()
    return sorted(names, key=str.lower)


def exp_for_players(exp_df: pd.DataFrame, names: list[str],
                    date_range: tuple | None = None) -> dict:
    """Resumo de experiência para uma lista de jogadores.

    Retorna {name: {found, level, total_xp, gained, series}} onde series é o
    DataFrame (snapshot_date, exp_gained) do período. `found=False` se o jogador
    não está nos snapshots (ex.: fora do top monitorado do ranking).
    """
    out: dict = {}
    for name in names:
        sub = exp_df[exp_df["character_name"] == name].sort_values("snapshot_date")
        if sub.empty:
            out[name] = {"found": False, "level": None, "total_xp": None,
                         "gained": None, "series": sub}
            continue
        latest = sub.iloc[-1]
        series = sub
        if date_range:
            start, end = date_range
            series = sub[(sub["snapshot_date"] >= start) & (sub["snapshot_date"] <= end)]
        gained = series["exp_gained"].dropna().sum() if "exp_gained" in series else 0
        out[name] = {
            "found": True,
            "level": int(latest["level"]) if pd.notna(latest["level"]) else None,
            "total_xp": int(latest["experience"]),
            "gained": int(gained) if pd.notna(gained) else 0,
            "series": series[["snapshot_date", "exp_gained"]].dropna(),
        }
    return out


def head_to_head_players(
    df: pd.DataFrame, player_a: str, player_b: str,
    world: str | None = None, date_range: tuple | None = None,
) -> dict:
    """Confronto direto entre dois jogadores a partir do frame de pvp_deaths."""
    d = df
    if world and world != "Todos":
        d = d[d["world"] == world]
    if date_range:
        start, end = date_range
        d = d[(d["date"] >= start) & (d["date"] <= end)]

    a_rows = d[(d["killer_name"] == player_a) & (d["victim"] == player_b)]  # A matou B
    b_rows = d[(d["killer_name"] == player_b) & (d["victim"] == player_a)]  # B matou A
    a_kills, b_kills = a_rows["id"].nunique(), b_rows["id"].nunique()

    daily = (
        pd.concat([
            a_rows[["id", "date"]].drop_duplicates().assign(side=player_a),
            b_rows[["id", "date"]].drop_duplicates().assign(side=player_b),
        ]).groupby(["date", "side"]).size().rename("kills").reset_index()
        if (not a_rows.empty or not b_rows.empty)
        else pd.DataFrame(columns=["date", "side", "kills"])
    )

    feed = pd.concat([
        a_rows.assign(direction=f"{player_a} → {player_b}"),
        b_rows.assign(direction=f"{player_b} → {player_a}"),
    ])
    if not feed.empty:
        feed = (feed.sort_values("occurred_at", ascending=False).drop_duplicates("id")
                [["occurred_at", "direction", "victim_level", "world"]])

    return {"a_kills": int(a_kills), "b_kills": int(b_kills), "daily": daily, "feed": feed}


def head_to_head(
    df: pd.DataFrame,
    guild_a: str,
    guild_b: str,
    world: str | None = None,
    date_range: tuple | None = None,
    min_level: int = 0,
) -> dict:
    """Calcula o confronto A vs B a partir do frame de pvp_deaths."""
    d = df
    if world and world != "Todos":
        d = d[d["world"] == world]
    if min_level:
        d = d[d["victim_level"].fillna(0) >= min_level]
    if date_range:
        start, end = date_range
        d = d[(d["date"] >= start) & (d["date"] <= end)]

    # A matou B: vítima em B, matador em A.
    a_kills_rows = d[(d["killer_guild"] == guild_a) & (d["victim_guild"] == guild_b)]
    b_kills_rows = d[(d["killer_guild"] == guild_b) & (d["victim_guild"] == guild_a)]

    def _top_killer(rows: pd.DataFrame) -> tuple[str | None, int]:
        if rows.empty:
            return None, 0
        vc = rows["killer_name"].value_counts()
        return vc.index[0], int(vc.iloc[0])

    a_top, a_top_n = _top_killer(a_kills_rows)
    b_top, b_top_n = _top_killer(b_kills_rows)

    # "kills" da guild = mortes distintas (frags), não linhas.
    a_kills = a_kills_rows["id"].nunique()
    b_kills = b_kills_rows["id"].nunique()

    # atividade diária (mortes distintas por dia, cada lado)
    daily = (
        pd.concat([
            a_kills_rows[["id", "date"]].drop_duplicates().assign(side=guild_a),
            b_kills_rows[["id", "date"]].drop_duplicates().assign(side=guild_b),
        ])
        .groupby(["date", "side"]).size().rename("kills").reset_index()
        if (not a_kills_rows.empty or not b_kills_rows.empty) else
        pd.DataFrame(columns=["date", "side", "kills"])
    )

    # feed do confronto (mortes distintas, ambos os sentidos)
    feed = pd.concat([
        a_kills_rows.assign(direction=f"{guild_a} → {guild_b}"),
        b_kills_rows.assign(direction=f"{guild_b} → {guild_a}"),
    ])
    if not feed.empty:
        feed = (feed.sort_values("occurred_at", ascending=False)
                    .drop_duplicates("id"))
        feed = feed[["occurred_at", "killer_name", "victim", "victim_level",
                     "direction", "world"]]

    return {
        "a_kills": int(a_kills), "b_kills": int(b_kills),
        "a_top": a_top, "a_top_n": a_top_n,
        "b_top": b_top, "b_top_n": b_top_n,
        "daily": daily, "feed": feed,
    }
