# Analytics DeusOLD

Coleta e análise de **mortes/guerras** do servidor [deusold.com](https://deusold.com)
(Tibia 7.4 OTServer, mundo *Memorium*). Protótipo end-to-end: **coletor → SQLite → dashboard**.

## Como funciona a captura

O site **não tem API pública** — os dados são HTML renderizado no servidor. Um request
com User-Agent de navegador recebe `200` (o Cloudflare deste site não bloqueia scraping
simples), então usamos `httpx` + `BeautifulSoup`, sem navegador headless.

Fontes mapeadas:

| Rota | Dado |
|---|---|
| `/community/deaths?page=N` | Feed de mortes (50/pág, ~40 págs = ~2000 mortes retidas) |
| `/community/guilds` | Lista de guilds (ids) |
| `/community/guild/<id>` | Nome + membros (nome→guild) |
| `/character/<Nome>` | Ficha: level, vocação, **guild** (resolve nome→guild) |
| `/ranking?skill_filter=level` | Highscores com **level + experiência** (base do powerscore) |

> ⚠️ **O feed só retém ~2000 mortes recentes e não tem filtro por data.** Histórico só se
> constrói **rodando o coletor de tempos em tempos** e acumulando no banco. Não dá pra
> "consultar o passado" sob demanda.

## Instalação

```bash
pip install -r requirements.txt
```

## Uso

**1. Coletar dados** (grava em `data/deusold.db`):

```bash
python -m deusold.collect all --pages 40
```

- `python -m deusold.collect deaths --pages 40` — só mortes
- `python -m deusold.collect guilds` — só guilds
- `python -m deusold.collect exp --pages 12` — snapshot de experiência do dia (powerscore)
- `python -m deusold.collect characters --limit 150` — resolve guild dos players das mortes
- Mortes já vistas são ignoradas (dedup por hash); rodadas repetidas são seguras.

### Agendamento (Windows) — já configurado

Duas tarefas no Agendador do Windows mantêm o histórico crescendo sozinho:

| Tarefa | Frequência | O que faz |
|---|---|---|
| **DeusOLD Collect Frequent** | a cada 15 min | `deaths --pages 5` + `characters --limit 100` |
| **DeusOLD Collect Daily** | 10:05 diariamente | `exp --pages 12` (o site atualiza rankings às 10:00) |

Scripts em `scripts/`. Log em `data/collector.log`. Para gerenciar:

```powershell
Get-ScheduledTask -TaskName "DeusOLD*"                       # status
Start-ScheduledTask -TaskName "DeusOLD Collect Frequent"     # rodar agora
Unregister-ScheduledTask -TaskName "DeusOLD Collect Frequent" -Confirm:$false  # remover
Unregister-ScheduledTask -TaskName "DeusOLD Collect Daily" -Confirm:$false
```

**2. Abrir o dashboard:**

```bash
streamlit run dashboard/app.py
```

Três abas:
- **⚔️ Guerra (Guilds)** — confronto A×B: kills de cada lado, top killer, atividade diária, kill feed.
- **🤺 Rivalidade (Players)** — duelo jogador A×B + ranking das maiores rivalidades (não depende de guild).
- **📈 Daily Exp (Players)** — powerscore: XP total e, com ≥2 snapshots, o "exp today".

## Estrutura

```
deusold/
  config.py     # URLs, headers, caminho do banco, tz do servidor
  client.py     # cliente HTTP (headers de navegador, retry, delay educado)
  parse.py      # HTML -> dicts (mortes, ids de guild, membros)
  db.py         # schema SQLite + upserts idempotentes
  analytics.py  # queries -> DataFrames; lógica de confronto A vs B
  collect.py    # CLI orquestrador
dashboard/
  app.py        # Streamlit
```

## Modelo de dados

- `deaths` — uma linha por morte (id, hora, vítima, level, mundo).
- `death_killers` — matadores de cada morte (jogador ou monstro), na ordem original.
- `guilds` / `guild_members` — snapshot atual de composição (nome→guild).

## Duas características importantes deste servidor (dados, não bugs)

1. **Guild-vs-guild é naturalmente esparso no Memorium.** Só ~11% dos personagens têm guild
   e **~64% das vítimas de PvP são level ≤ 20** — o feed é dominado por PvP de lowbie, que
   quase nunca está em guild. A guerra organizada entre guilds grandes é uma fração pequena.
   → As visões **por jogador** (top killers, rivalidade entre players, powerscore) são bem
   mais ricas aqui do que guild-vs-guild.
2. **"Exp today" precisa de ≥ 2 snapshots diários.** O delta é a diferença de XP entre dois
   dias; começa a aparecer no 2º dia de coleta agendada. Antes disso, a aba mostra o ranking
   de XP total (powerscore atual).

## Roadmap

1. **Rivalidade entre players** (par jogador A × jogador B) — aproveita a densidade do feed.
2. Cobertura de guild sobe sozinha: o resolver `characters` roda a cada 15 min (+100/rodada).
3. Guardar **histórico de composição** de guild com data (jogador mudou de guild).
4. Migrar SQLite → Postgres quando o volume crescer; separar API/backend do dashboard.
