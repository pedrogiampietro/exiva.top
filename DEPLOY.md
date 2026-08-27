# Deploy em VPS (Docker Compose)

Sobe 3 serviços: **db** (Postgres, com volume persistente), **dashboard** (Streamlit) e
**collector** (scheduler que substitui as tarefas do Windows). O coletor faz **backfill
automático** no 1º start (banco vazio), então não é preciso migrar dados do SQLite local —
ele repopula a janela de mortes retida (~2000) e os rankings sozinho.

## 1. Servidor

Uma VPS pequena basta (ex.: Hetzner CX22 / DigitalOcean 1-2 GB, ~€4-5/mês), Ubuntu 22.04+.

```bash
# instalar Docker + compose plugin
curl -fsSL https://get.docker.com | sh
```

## 2. Código e configuração

```bash
git clone <seu-repo> analytics-deusold && cd analytics-deusold
cp .env.example .env
nano .env          # defina POSTGRES_PASSWORD (obrigatório) e ajuste o resto
```

## 3. Subir

```bash
docker compose up -d --build
docker compose logs -f collector      # acompanha o backfill inicial
```

O dashboard fica em `http://SEU_IP:8501`. O collector roda sozinho: mortes+guild a cada
15 min, snapshot de exp 1x/dia às ~10:05.

## 4. (Recomendado) HTTPS + domínio

Coloque um reverse proxy na frente (Caddy é o mais simples — TLS automático):

```bash
# /etc/caddy/Caddyfile
seu-dominio.com {
    reverse_proxy localhost:8501
}
```

Streamlit usa WebSocket; o Caddy/Nginx precisa repassar `Upgrade`/`Connection` (o Caddy já
faz por padrão). Não exponha a porta do Postgres publicamente (o compose só a usa na rede
interna).

## Operação

```bash
docker compose ps                     # status
docker compose logs -f dashboard      # logs
docker compose pull && docker compose up -d --build   # atualizar após git pull
docker compose down                   # parar (mantém o volume/dados)

# backup do banco
docker compose exec db pg_dump -U deusold deusold > backup_$(date +%F).sql
```

## Local vs. Produção

- **Local (dev):** sem `DATABASE_URL` → usa SQLite em `data/deusold.db` (nada muda no seu fluxo).
- **Produção:** o compose define `DATABASE_URL` apontando pro Postgres. O mesmo código roda nos dois.
- As **tarefas do Windows** (Agendador) alimentam só o SQLite local; na VPS quem cuida é o
  container `collector`. Pode manter as duas coisas sem conflito (bancos separados).
