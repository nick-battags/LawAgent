# LawAgent: Full Replit Exit (Cheapest VPS + Home Ollama)

This guide moves LawAgent off Replit entirely:

- Cheap VPS hosts web app + PostgreSQL + TLS.
- Home machine hosts Ollama models.
- Runtime mode supports `auto`, `llm`, and `deterministic`.

## 1) What This Architecture Gives You

- Always-on public app at `lawagent.yourdomain.com`.
- Full 2-model CRAG when home Ollama is reachable.
- Deterministic fallback if Ollama is down (in `auto` mode).
- Main website can stay where it is (`nickvbattaglia.com` unchanged).

## 2) Responsibility Split

### What Codex can do in this repo

- Add deployment files (`Dockerfile`, compose, env template, runbook).
- Add runtime mode controls in backend and frontend.
- Add preflight checks and health validation scripts.
- Update docs to remove Replit dependency.

### What you must do (infra + accounts)

- Provision VPS.
- Set DNS for `lawagent.<domain>` to VPS.
- Install Docker and deploy stack.
- Install Tailscale on VPS and home machine.
- Install and run Ollama on home machine.
- Pull models and keep Ollama service running.
- Set real secrets in `.env.vps`.

### Replit actions (to exit fully)

- Disable/remove Replit deployment.
- Remove Replit app custom domain mapping.
- Keep repo connected only to Git remote you control.

## 3) Cheapest VPS Baseline

Use a small VPS first (2 vCPU / 4 GB RAM class is enough for web + DB).

- Example: Hetzner CX23 class.
- App stack runs on VPS.
- Ollama does **not** run on VPS in this hybrid model.

## 4) DNS and Domain

Add DNS A record:

- Host: `lawagent`
- Type: `A`
- Value: `<your_vps_public_ip>`
- TTL: default (or 300)

Wait for propagation before TLS bootstrap.

## 5) Home Server (Ollama Node)

Install Ollama and pull models on your always-on home machine:

```bash
ollama pull llama3.1:8b
ollama pull command-r:7b
ollama pull nomic-embed-text
ollama list
```

Keep Ollama running as a service.

## 6) Private Connectivity (Recommended: Tailscale)

Install Tailscale on both VPS and home machine and join the same tailnet.

Verify from VPS:

```bash
curl http://<home_tailscale_ip>:11434/api/tags
```

If this fails, fix connectivity before app deploy.

## 7) Deploy on VPS

### 7.1 Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

### 7.2 Clone and configure

```bash
git clone <your-repo-url> lawagent
cd lawagent/deployment
cp .env.vps.example .env.vps
```

Edit `.env.vps`:

- `LAWAGENT_DOMAIN=lawagent.yourdomain.com`
- `ADMIN_PIN=...`
- `FLASK_SECRET_KEY=...`
- `POSTGRES_PASSWORD=...`
- `OLLAMA_BASE_URL=http://<home_tailscale_ip>:11434`
- Leave `LAWAGENT_RUNTIME_MODE=auto` initially.

### 7.3 Start stack

```bash
chmod +x scripts/preflight.sh
./scripts/preflight.sh
docker compose -f docker-compose.hybrid.yml --env-file .env.vps up -d --build
docker compose -f docker-compose.hybrid.yml ps
```

### 7.4 Validate

```bash
curl -f https://lawagent.yourdomain.com/health
curl -f https://lawagent.yourdomain.com/api/v2/pipeline/status
curl -f https://lawagent.yourdomain.com/api/v2/llm/status
```

## 8) Runtime Mode Behavior

- `auto` (recommended): LLM when reachable, deterministic fallback otherwise.
- `llm`: no fallback. If Ollama unavailable, LLM paths return unavailable state.
- `deterministic`: always skip Ollama.

Frontend selector on analyzer panel sends mode for V2 analysis/template runs.

## 8.1) Automatic Vector Sync

Vector sync now runs automatically after corpus-changing operations:

- manual uploads
- deposit ingestion
- MAUD ingestion completion
- CUAD ingestion completion
- EDGAR ingestion
- document tag updates
- document deletion (with targeted vector removal)

You can still run `/api/v2/vectors/sync` manually if needed.

## 9) Operations

### Update app

```bash
cd ~/lawagent
git pull
cd deployment
docker compose -f docker-compose.hybrid.yml --env-file .env.vps up -d --build
```

### Logs

```bash
docker compose -f docker-compose.hybrid.yml logs -f app
docker compose -f docker-compose.hybrid.yml logs -f caddy
docker compose -f docker-compose.hybrid.yml logs -f postgres
```

### Stop/start

```bash
docker compose -f docker-compose.hybrid.yml --env-file .env.vps down
docker compose -f docker-compose.hybrid.yml --env-file .env.vps up -d
```

## 10) Minimum Cutover Checklist

1. DNS `lawagent` -> VPS IP.
2. Tailscale connectivity VPS -> home Ollama confirmed.
3. `.env.vps` filled with real secrets and tailnet Ollama URL.
4. Compose stack healthy.
5. `/health` and `/api/v2/pipeline/status` both green.
6. Replit deployment/domain disabled.
