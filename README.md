# auto-proxy-cloudflare

> Also available in: [Español](README.es.md)

A lightweight daemon that automatically disables and re-enables the Cloudflare proxy on your DNS records when La Liga (the Spanish football association) blocks Cloudflare's IP ranges.

## The Problem

La Liga operates a court-ordered IP blocking system in Spain that targets Cloudflare proxy IPs during football match windows — and sometimes beyond. If your server sits behind a Cloudflare-proxied domain, your users in Spain can be cut off without any warning. The only workaround is to bypass the proxy temporarily so traffic reaches your real server IP directly.

This service automates that workaround: it detects the block, turns off the proxy, and turns it back on once the block is lifted — all without any manual intervention.

## How It Works

```
┌─────────────────────────────────────────────────────┐
│                   Polling loop                      │
│  Every CHECK_INTERVAL seconds for each domain:      │
│                                                     │
│  1. Query deinser.com check API                     │
│     → domain_blocked: true / false                  │
│                                                     │
│  2a. If BLOCKED and proxy is ON                     │
│      → Cloudflare API: set proxied=false            │
│      → (optional) Discord notification              │
│                                                     │
│  2b. If UNBLOCKED and proxy was disabled by us      │
│      → Cloudflare API: set proxied=true             │
│      → (optional) Discord notification              │
└─────────────────────────────────────────────────────┘
```

**Important:** the service only re-enables the proxy on domains it previously disabled. It will never touch DNS records it did not modify itself.

## Block Detection API

Block status is checked using the public API provided by [deinser.com](https://deinser.com):

```
GET https://deinser.com/cloudflare/laliga/?domain=<domain>&json=1
```

Example response:

```json
{
  "domain": "sub.example.com",
  "domain_ips": ["188.114.96.3", "188.114.97.3"],
  "domain_with_cloudflare_proxy": true,
  "domain_blocked": true,
  "blocked_ips": [],
  "futbol_blocking_active": true,
  "from_cache": true
}
```

The service reads the `domain_blocked` field to decide whether to act.

## Configuration

All configuration is done via environment variables. Copy `.env.example` to `.env` and fill in your values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `CF_API_TOKEN` | one of these two | — | Cloudflare API Token (**recommended**) |
| `CF_API_KEY` + `CF_EMAIL` | one of these two | — | Cloudflare Global API Key + account email (legacy) |
| `DOMAINS` | yes | — | Comma-separated list of domains to monitor |
| `CHECK_INTERVAL` | no | `300` | Seconds between checks |
| `DISCORD_WEBHOOK_URL` | no | — | Discord webhook URL for state-change notifications |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Cloudflare API Token permissions

When using `CF_API_TOKEN` (recommended over the Global API Key), create a token with:

- **Permission:** `Zone` → `DNS` → `Edit`
- **Zone resources:** include only the zone(s) you intend to manage

This gives the service the minimum necessary access.

## Running with Docker

### Pull from GHCR

```bash
docker pull ghcr.io/ninjakito/auto-proxy-cloudflare:latest
```

### With Docker Compose

```bash
cp .env.example .env
# edit .env with your values
cp docker-compose.example.yml docker-compose.yml
docker compose up -d
```

### With `docker run`

```bash
docker run -d \
  --name auto-proxy-cloudflare \
  --restart unless-stopped \
  --env-file .env \
  ghcr.io/ninjakito/auto-proxy-cloudflare:latest
```

### Build locally

```bash
docker build -t auto-proxy-cloudflare .
docker run --env-file .env auto-proxy-cloudflare
```

## Running without Docker

Requires Python 3.12+.

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env
export $(grep -v '^#' .env | xargs)
python src/main.py
```

## Discord Notifications

When `DISCORD_WEBHOOK_URL` is set, the service sends an embed message to your Discord channel on every state change:

- **Red embed** — domain blocked, proxy disabled
- **Green embed** — domain unblocked, proxy re-enabled

Notifications are optional and never required for the service to function.

## Docker Image

Multi-architecture images (`linux/amd64` and `linux/arm64`) are built automatically via GitHub Actions and published to the GitHub Container Registry on every push to `main`. Two tags are published per build: `:latest` and `:sha-<short_commit>` for pinning to a specific commit.

## License

MIT
