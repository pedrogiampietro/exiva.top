"""Dashboard War & Statistics — DeusOLD.

Rodar:  streamlit run dashboard/app.py
Colete dados antes:  python -m deusold.collect all --pages 40
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deusold import analytics, config, db  # noqa: E402

GREEN = "#22c55e"
RED = "#ef4444"
GOLD = "#f59e0b"

st.set_page_config(page_title="War & Statistics — DeusOLD", page_icon="⚔️", layout="wide")


@st.cache_data(ttl=60)
def load():
    eng = analytics.connect()
    db.init_db(eng)
    data = {
        "guilds": analytics.guild_options(eng),
        "pvp": analytics.pvp_deaths(eng),
        "exp": analytics.daily_exp(analytics.experience_frame(eng)),
        "name_guild": analytics.name_guild_map(eng),
        "meta": db.stats(eng),
    }
    return data


data = load()
st.title("⚔️ War & Statistics")
st.caption("Analytics de guerras e evolução de XP a partir dos dados do DeusOLD.")

if data is None or data["guilds"].empty:
    st.warning("Banco vazio. Rode:  `python -m deusold.collect all --pages 40`")
    st.stop()

meta = data["meta"]
tab_war, tab_riv, tab_exp = st.tabs(
    ["⚔️ Guerra (Guilds)", "🤺 Rivalidade (Players)", "📈 Daily Exp (Players)"])


# ========================= GUERRA ENTRE GUILDS ============================
def render_war() -> None:
    guilds, pvp = data["guilds"], data["pvp"]
    guild_names = guilds["name"].tolist()
    worlds = ["Todos"] + sorted(w for w in pvp["world"].dropna().unique())
    min_date, max_date = pvp["date"].min(), pvp["date"].max()

    def _default(name: str, fb: int) -> int:
        return guild_names.index(name) if name in guild_names else fb

    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 0.8])
    world = c1.selectbox("Mundo", worlds)
    guild_a = c2.selectbox("Guild A (aliada)", guild_names, index=_default("Brutality", 0))
    guild_b = c3.selectbox("Guild B (inimiga)", guild_names,
                           index=_default("Fusion", min(1, len(guild_names) - 1)))
    min_level = c4.number_input("Level mínimo", min_value=0, value=0, step=10)
    date_range = st.slider("Período", min_value=min_date, max_value=max_date,
                           value=(min_date, max_date), format="DD/MM")

    if guild_a == guild_b:
        st.info("Escolha duas guilds diferentes.")
        return

    res = analytics.head_to_head(pvp, guild_a, guild_b, world, date_range, int(min_level))

    left, mid, right = st.columns(3)
    with left:
        st.markdown(f"### 🛡️ {guild_a}")
        st.metric("Kills", res["a_kills"])
        if res["a_top"]:
            st.caption(f"Top killer: **{res['a_top']}** ({res['a_top_n']})")
    with mid:
        st.markdown("### ⚔️ Confronto")
        total = res["a_kills"] + res["b_kills"]
        share = res["a_kills"] / total if total else 0.5
        st.markdown(
            f"<div style='display:flex;height:26px;border-radius:6px;overflow:hidden'>"
            f"<div style='width:{share*100:.1f}%;background:{GREEN}'></div>"
            f"<div style='width:{(1-share)*100:.1f}%;background:{RED}'></div></div>"
            f"<div style='display:flex;justify-content:space-between;font-size:22px;"
            f"font-weight:700;margin-top:4px'><span>{res['a_kills']}</span>"
            f"<span>{res['b_kills']}</span></div>",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(f"### 💀 {guild_b}")
        st.metric("Kills", res["b_kills"])
        if res["b_top"]:
            st.caption(f"Top killer: **{res['b_top']}** ({res['b_top_n']})")

    st.divider()
    st.subheader("📊 Atividade diária da guerra")
    daily = res["daily"]
    if daily.empty:
        st.info("Nenhum confronto direto entre essas guilds no período/dados coletados.")
    else:
        piv = daily.pivot(index="date", columns="side", values="kills").fillna(0).sort_index()
        fig = go.Figure()
        if guild_a in piv:
            fig.add_bar(x=piv.index, y=piv[guild_a], name=f"Kills {guild_a}", marker_color=GREEN)
        if guild_b in piv:
            fig.add_bar(x=piv.index, y=piv[guild_b], name=f"Kills {guild_b}", marker_color=RED)
        fig.update_layout(barmode="group", height=360, margin=dict(t=10, b=10, l=10, r=10),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02),
                          yaxis_title="Kills")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("🗡️ Kill feed da guerra")
    feed = res["feed"]
    if feed is None or feed.empty:
        st.info("Sem mortes diretas entre as guilds.")
    else:
        show = feed.rename(columns={
            "occurred_at": "Hora", "killer_name": "Matador", "victim": "Vítima",
            "victim_level": "Lvl", "direction": "Sentido", "world": "Mundo"})
        show["Hora"] = pd.to_datetime(show["Hora"]).dt.strftime("%d/%m %H:%M")
        st.dataframe(show, use_container_width=True, hide_index=True, height=380)


# ======================= RIVALIDADE ENTRE PLAYERS ========================
def _score_row(col, name: str, kills: int, color: str, top: bool = False) -> None:
    border = f"2px solid {color}" if top else "1px solid #334155"
    col.markdown(
        f"<div style='border:{border};border-radius:10px;padding:14px;text-align:center'>"
        f"<div style='font-size:16px;font-weight:700'>{name}</div>"
        f"<div style='font-size:30px;font-weight:800;color:{color}'>{kills}</div>"
        f"<div style='opacity:.7;font-size:12px'>kills</div></div>",
        unsafe_allow_html=True,
    )


def render_rivalry() -> None:
    pvp = data["pvp"]
    players = analytics.players_in_pvp(pvp)
    if not players:
        st.info("Sem dados de PvP entre jogadores ainda.")
        return

    riv = analytics.top_player_rivalries(pvp, limit=12)

    st.subheader("🔥 Principais rivalidades")
    if riv.empty:
        st.caption("Nenhuma rivalidade bidirecional ainda (cresce com a coleta agendada).")
    else:
        chips = riv.assign(
            Confronto=lambda d: d["player_a"] + "  " + d["a_kills"].astype(str)
            + " × " + d["b_kills"].astype(str) + "  " + d["player_b"],
            Total=lambda d: d["total"],
        )[["Confronto", "Total"]]
        st.dataframe(chips, use_container_width=True, hide_index=True, height=200)

    # seleção (default = maior rivalidade)
    def_a = riv.iloc[0]["player_a"] if not riv.empty else players[0]
    def_b = riv.iloc[0]["player_b"] if not riv.empty else players[min(1, len(players) - 1)]

    c1, c2, c3 = st.columns([1.4, 1.4, 1])
    pa = c1.selectbox("Jogador A", players, index=players.index(def_a))
    pb = c2.selectbox("Jogador B", players, index=players.index(def_b))
    worlds = ["Todos"] + sorted(w for w in pvp["world"].dropna().unique())
    world = c3.selectbox("Mundo", worlds, key="riv_world")

    if pa == pb:
        st.info("Escolha dois jogadores diferentes.")
        return

    min_date, max_date = pvp["date"].min(), pvp["date"].max()
    date_range = st.slider("Período", min_value=min_date, max_value=max_date,
                           value=(min_date, max_date), format="DD/MM", key="riv_period")

    res = analytics.head_to_head_players(pvp, pa, pb, world, date_range)

    left, mid, right = st.columns(3)
    _score_row(left, pa, res["a_kills"], GREEN, top=res["a_kills"] >= res["b_kills"])
    with mid:
        st.markdown("<div style='text-align:center;opacity:.6;font-size:13px;"
                    "letter-spacing:1px'>CONFRONTO DIRETO</div>", unsafe_allow_html=True)
        total = res["a_kills"] + res["b_kills"]
        share = res["a_kills"] / total if total else 0.5
        st.markdown(
            f"<div style='display:flex;height:26px;border-radius:6px;overflow:hidden;margin-top:6px'>"
            f"<div style='width:{share*100:.1f}%;background:{GREEN}'></div>"
            f"<div style='width:{(1-share)*100:.1f}%;background:{RED}'></div></div>",
            unsafe_allow_html=True,
        )
    _score_row(right, pb, res["b_kills"], RED, top=res["b_kills"] > res["a_kills"])

    st.divider()
    st.subheader("📊 Atividade diária do duelo")
    daily = res["daily"]
    if daily.empty:
        st.info("Esses dois jogadores não se mataram no período/dados coletados.")
    else:
        piv = daily.pivot(index="date", columns="side", values="kills").fillna(0).sort_index()
        fig = go.Figure()
        if pa in piv:
            fig.add_bar(x=piv.index, y=piv[pa], name=pa, marker_color=GREEN)
        if pb in piv:
            fig.add_bar(x=piv.index, y=piv[pb], name=pb, marker_color=RED)
        fig.update_layout(barmode="group", height=340, margin=dict(t=10, b=10, l=10, r=10),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02),
                          yaxis_title="Kills")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("🗡️ Feed do duelo")
    feed = res["feed"]
    if feed is None or feed.empty:
        st.info("Sem mortes diretas entre os dois.")
    else:
        show = feed.rename(columns={"occurred_at": "Hora", "direction": "Quem matou quem",
                                    "victim_level": "Lvl vítima", "world": "Mundo"})
        show["Hora"] = pd.to_datetime(show["Hora"]).dt.strftime("%d/%m %H:%M")
        st.dataframe(show, use_container_width=True, hide_index=True, height=320)

    # ---- exp diária entre os dois rivais ----
    st.subheader("📈 Exp no duelo")
    exp_sum = analytics.exp_for_players(data["exp"], [pa, pb], date_range)
    ea, eb = exp_sum[pa], exp_sum[pb]

    m1, m2 = st.columns(2)
    for col, name, e, color in [(m1, pa, ea, GREEN), (m2, pb, eb, RED)]:
        with col:
            if not e["found"]:
                st.markdown(f"**{name}** — sem dados de XP "
                            "(fora do ranking monitorado).")
            else:
                lvl = e["level"] if e["level"] is not None else "?"
                st.markdown(f"**{name}** · Lv {lvl}")
                st.metric("XP ganho no período", f"{e['gained']:,}".replace(",", "."))
                st.caption(f"XP total: {e['total_xp']:,}".replace(",", "."))

    # gráfico comparativo de exp/dia (aparece com >= 2 snapshots)
    have = [n for n in (pa, pb) if exp_sum[n]["found"] and not exp_sum[n]["series"].empty]
    if have:
        fig = go.Figure()
        colors = {pa: GREEN, pb: RED}
        for n in have:
            s = exp_sum[n]["series"]
            fig.add_bar(x=s["snapshot_date"], y=s["exp_gained"], name=n, marker_color=colors[n])
        fig.update_layout(barmode="group", height=300, margin=dict(t=10, b=10, l=10, r=10),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02),
                          yaxis_title="XP/dia")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("O comparativo de XP por dia aparece a partir do 2º snapshot diário "
                   "(coletor das 10:05).")


# ============================ DAILY EXP ===================================
def _podium_card(col, rank: int, row, color: str) -> None:
    col.markdown(
        f"<div style='border:1px solid {color};border-radius:10px;padding:14px;text-align:center'>"
        f"<div style='font-size:26px;font-weight:800;color:{color}'>#{rank}</div>"
        f"<div style='font-size:18px;font-weight:700'>{row['character_name']}</div>"
        f"<div style='opacity:.7;font-size:12px'>{row.get('world','')} · Lv "
        f"{int(row['level']) if pd.notna(row['level']) else '?'}</div>"
        f"<div style='margin-top:8px;color:{GREEN};font-weight:700'>"
        f"↑ {int(row['exp_gained']):,} XP</div></div>".replace(",", "."),
        unsafe_allow_html=True,
    )


def render_exp() -> None:
    exp = data["exp"]
    if exp.empty:
        st.info("Sem snapshots de XP. Rode:  `python -m deusold.collect exp --pages 12`")
        return

    have_deltas = exp["exp_gained"].notna().any()
    if not have_deltas:
        st.info(
            f"📸 Já temos **1 snapshot** ({meta['exp_days']} dia). O *exp today* é a **diferença "
            "entre dois dias** — ele aparece a partir do 2º snapshot (amanhã, com o coletor "
            "agendado). Por enquanto, o ranking de **XP total** (powerscore atual):")
        power = analytics.power_leaderboard(exp)
        power = power.merge(data["name_guild"].rename(columns={"name": "character_name"}),
                            on="character_name", how="left")
        show = power[["character_name", "world", "level", "guild", "experience"]].head(100)
        show.columns = ["Jogador", "Mundo", "Level", "Guild", "XP Total"]
        st.dataframe(show, use_container_width=True, hide_index=True, height=500)
        return

    days = sorted(exp.loc[exp["exp_gained"].notna(), "snapshot_date"].unique())
    day = st.selectbox("Dia", days, index=len(days) - 1, format_func=lambda d: d.strftime("%d/%m/%Y"))
    dd = exp[(exp["snapshot_date"] == day) & exp["exp_gained"].notna()].copy()
    dd = dd.merge(data["name_guild"].rename(columns={"name": "character_name"}),
                  on="character_name", how="left")
    dd = dd.sort_values("exp_gained", ascending=False).reset_index(drop=True)

    if dd.empty:
        st.info("Sem ganho de XP registrado nesse dia.")
        return

    # pódio #2 #1 #3
    top3 = dd.head(3)
    if len(top3) >= 1:
        c2, c1, c3 = st.columns(3)
        if len(top3) >= 2:
            _podium_card(c2, 2, top3.iloc[1], "#94a3b8")
        _podium_card(c1, 1, top3.iloc[0], GOLD)
        if len(top3) >= 3:
            _podium_card(c3, 3, top3.iloc[2], RED)

    st.divider()
    q = st.text_input("🔎 Buscar jogador", "")
    view = dd if not q else dd[dd["character_name"].str.contains(q, case=False, na=False)]
    tbl = view[["character_name", "world", "level", "guild", "exp_gained"]].copy()
    tbl.columns = ["Jogador", "Mundo", "Level", "Guild", "XP no dia"]
    st.dataframe(tbl, use_container_width=True, hide_index=True, height=460)

    # histórico de um jogador
    st.subheader("📈 Histórico de XP")
    who = st.selectbox("Jogador", dd["character_name"].tolist())
    hist = data["exp"][data["exp"]["character_name"] == who].sort_values("snapshot_date")
    fig = go.Figure(go.Scatter(x=hist["snapshot_date"], y=hist["experience"],
                               mode="lines+markers", line=dict(color=GREEN, width=3)))
    fig.update_layout(height=340, margin=dict(t=10, b=10, l=10, r=10),
                      yaxis_title="XP total")
    st.plotly_chart(fig, use_container_width=True)


with tab_war:
    render_war()
with tab_riv:
    render_rivalry()
with tab_exp:
    render_exp()

st.caption(
    f"Banco: {meta['deaths']} mortes · {meta['guilds']} guilds · {meta['characters']} chars "
    f"resolvidos · {meta['exp_rows']} snapshots de XP ({meta['exp_days']} dia(s))")
