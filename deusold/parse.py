"""Parsers de HTML -> estruturas Python. Sem I/O de rede aqui (fácil de testar)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import unquote

from bs4 import BeautifulSoup

_TIME_FMT = "%d %b %Y, %H:%M"  # ex.: "27 Aug 2026, 01:51"

_VOCATIONS = (
    "Master Sorcerer", "Elder Druid", "Royal Paladin", "Elite Knight",
    "Sorcerer", "Druid", "Paladin", "Knight", "None",
)


def _char_name_from_href(href: str) -> str:
    # https://deusold.com/character/Tomy%20Hits -> "Tomy Hits"
    return unquote(href.rsplit("/character/", 1)[-1]).strip()


def death_id(occurred_at: str, victim: str, killer_names: list[str]) -> str:
    raw = f"{occurred_at}|{victim.lower()}|{'&'.join(k.lower() for k in killer_names)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def parse_deaths(html: str) -> list[dict]:
    """Extrai as linhas do feed /community/deaths.

    Retorna dicts com: occurred_at (ISO), victim, victim_level, world,
    killers (lista de {name, is_player}), id, has_player_kill.
    """
    soup = BeautifulSoup(html, "lxml")
    deaths: list[dict] = []

    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:  # pula cabeçalho e linhas incompletas
            continue

        # td[0]: hora
        time_txt = tds[0].get_text(strip=True)
        try:
            occurred_at = datetime.strptime(time_txt, _TIME_FMT).isoformat()
        except ValueError:
            continue  # linha que não bate o formato -> ignora

        # td[1]: vítima (sempre link)
        victim_link = tds[1].find("a")
        if not victim_link:
            continue
        victim = victim_link.get_text(strip=True)

        # td[2]: level
        lvl_txt = tds[2].get_text(strip=True)
        victim_level = int(lvl_txt) if lvl_txt.isdigit() else None

        # td[3]: "morto por" — <a> = jogador, <span> = monstro/ambiente,
        # na ordem do documento (preserva assists).
        killers: list[dict] = []
        for el in tds[3].find_all(["a", "span"]):
            name = el.get_text(strip=True)
            if not name:
                continue
            killers.append({"name": name, "is_player": el.name == "a"})

        # td[4]: mundo
        world = tds[4].get_text(strip=True)

        kid = death_id(occurred_at, victim, [k["name"] for k in killers])
        deaths.append({
            "id": kid,
            "occurred_at": occurred_at,
            "victim": victim,
            "victim_level": victim_level,
            "world": world,
            "killers": killers,
            "has_player_kill": any(k["is_player"] for k in killers),
        })

    return deaths


def parse_deaths_last_page(html: str) -> int:
    """Descobre o número da última página de mortes a partir da paginação."""
    soup = BeautifulSoup(html, "lxml")
    pages = [1]
    for a in soup.find_all("a", href=True):
        m = re.search(r"[?&]page=(\d+)", a["href"])
        if m:
            pages.append(int(m.group(1)))
    return max(pages)


def parse_guild_ids(html: str) -> list[int]:
    """Extrai os ids das guilds da lista /community/guilds."""
    soup = BeautifulSoup(html, "lxml")
    ids: list[int] = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"/community/guild/(\d+)", a["href"])
        if m:
            ids.append(int(m.group(1)))
    # preserva ordem, remove duplicados
    seen: set[int] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def _num(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse_highscores(html: str) -> list[dict]:
    """Extrai o ranking /ranking. Mapeia colunas pelo cabeçalho (robusto a reordenação).

    Retorna dicts: rank, name, world, level, experience, vocation.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue

        def col(*keys: str) -> int | None:
            for i, h in enumerate(headers):
                if any(k in h for k in keys):
                    return i
            return None

        i_rank = col("rank")
        i_name = col("nome", "name")
        i_world = col("mundo", "world")
        i_level = col("level")
        i_exp = col("experi", "experience")
        i_voc = col("voca")
        if i_name is None or i_exp is None:
            continue

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < len(headers):
                continue
            link = tds[i_name].find("a")
            name = (_char_name_from_href(link["href"]) if link and link.has_attr("href")
                    else tds[i_name].get_text(strip=True))
            if not name:
                continue
            rows.append({
                "rank": _num(tds[i_rank].get_text()) if i_rank is not None else None,
                "name": name,
                "world": tds[i_world].get_text(strip=True) if i_world is not None else None,
                "level": _num(tds[i_level].get_text()) if i_level is not None else None,
                "experience": _num(tds[i_exp].get_text()),
                "vocation": tds[i_voc].get_text(strip=True) if i_voc is not None else None,
            })
        if rows:
            break  # usa a primeira tabela válida
    return rows


def parse_character(html: str) -> dict:
    """Extrai dados de /character/<nome>: name, world, level, vocation,
    guild_name, guild_id.
    """
    soup = BeautifulSoup(html, "lxml")
    out: dict = {"name": None, "world": None, "level": None, "vocation": None,
                 "guild_name": None, "guild_id": None}

    # A ficha é uma lista rótulo->valor. Varre o texto por rótulos conhecidos.
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    labels = {
        "Nome:": "name", "Profissão:": "vocation", "Level:": "level", "Mundo:": "world",
    }
    for i, line in enumerate(lines[:-1]):
        if line in labels:
            key = labels[line]
            if out[key] is not None:  # primeiro vence (há um 2º "Nome:" no form de busca)
                continue
            val = lines[i + 1]
            out[key] = _num(val) if key == "level" else val

    guild_link = soup.find("a", href=re.compile(r"/community/guild/\d+"))
    if guild_link:
        out["guild_name"] = guild_link.get_text(strip=True)
        m = re.search(r"/community/guild/(\d+)", guild_link["href"])
        if m:
            out["guild_id"] = int(m.group(1))
    return out


def parse_guild_page(html: str) -> tuple[str | None, list[dict]]:
    """Extrai (nome_da_guild, membros) de /community/guild/<id>.

    Cada membro: {name, vocation, level, rank}.
    """
    soup = BeautifulSoup(html, "lxml")

    name_el = soup.find(["h1", "h2"])
    guild_name = name_el.get_text(strip=True) if name_el else None

    members: list[dict] = []
    for tr in soup.select("table tr"):
        link = tr.find("a", href=re.compile(r"/character/"))
        if not link or "/character/search" in link.get("href", ""):
            continue
        member_name = _char_name_from_href(link["href"]) or link.get_text(strip=True)

        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        row_text = " ".join(cells)

        level = None
        nums = re.findall(r"\b(\d{1,4})\b", row_text)
        if nums:
            level = int(nums[-1])

        vocation = next((v for v in _VOCATIONS if v in row_text), None)
        rank = cells[0] if cells else None
        if rank:  # remove letra de ícone que vem colada, ex.: "a Vice-Leader"
            rank = re.sub(r"^[a-zA-Z]\s+", "", rank).strip() or None

        members.append({
            "name": member_name,
            "vocation": vocation,
            "level": level,
            "rank": rank,
        })

    return guild_name, members
