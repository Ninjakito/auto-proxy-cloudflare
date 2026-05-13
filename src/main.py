import os
import sys
import time
import logging
import signal
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
CF_API_KEY = os.getenv("CF_API_KEY", "")
CF_EMAIL = os.getenv("CF_EMAIL", "")
DOMAINS_RAW = os.getenv("DOMAINS", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

CF_API_BASE = "https://api.cloudflare.com/client/v4"
CHECK_API_URL = "https://deinser.com/cloudflare/laliga/"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
log = logging.getLogger("auto-proxy-cloudflare")

# ---------------------------------------------------------------------------
# Cloudflare helpers
# ---------------------------------------------------------------------------

def cf_headers() -> dict:
    if CF_API_TOKEN:
        return {
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json",
        }
    return {
        "X-Auth-Email": CF_EMAIL,
        "X-Auth-Key": CF_API_KEY,
        "Content-Type": "application/json",
    }


def get_root_zone(domain: str) -> str:
    """Extract registrable domain: sub.example.com -> example.com"""
    parts = domain.rstrip(".").split(".")
    return ".".join(parts[-2:])


_zone_cache: dict = {}


def get_zone_id(root_zone: str):
    if root_zone in _zone_cache:
        return _zone_cache[root_zone]
    url = f"{CF_API_BASE}/zones?name={root_zone}"
    try:
        r = requests.get(url, headers=cf_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("result"):
            zone_id = data["result"][0]["id"]
            _zone_cache[root_zone] = zone_id
            log.debug("Cached zone ID for %s: %s", root_zone, zone_id)
            return zone_id
        log.error("No zone found for %s in Cloudflare account.", root_zone)
    except Exception as e:
        log.error("Failed to get zone ID for %s: %s", root_zone, e)
    return None


def get_dns_records(zone_id: str, domain: str) -> list:
    url = f"{CF_API_BASE}/zones/{zone_id}/dns_records?name={domain}"
    try:
        r = requests.get(url, headers=cf_headers(), timeout=15)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        log.error("Failed to get DNS records for %s: %s", domain, e)
    return []


def set_proxy(zone_id: str, record_id: str, domain: str, proxied: bool) -> bool:
    url = f"{CF_API_BASE}/zones/{zone_id}/dns_records/{record_id}"
    try:
        r = requests.patch(url, json={"proxied": proxied}, headers=cf_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("success"):
            log.info("Set proxied=%s for %s (record %s)", proxied, domain, record_id)
            return True
        log.warning("Cloudflare returned success=false for %s: %s", domain, data.get("errors"))
    except Exception as e:
        log.error("Failed to patch DNS record %s for %s: %s", record_id, domain, e)
    return False

# ---------------------------------------------------------------------------
# Check API
# ---------------------------------------------------------------------------

def check_domain(domain: str):
    try:
        r = requests.get(
            CHECK_API_URL,
            params={"domain": domain, "json": "1"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Failed to check domain %s: %s", domain, e)
    return None

# ---------------------------------------------------------------------------
# Discord notifications
# ---------------------------------------------------------------------------

def notify_discord(domain: str, blocked: bool) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    state_str = "BLOQUEADO (proxy desactivado)" if blocked else "DESBLOQUEADO (proxy reactivado)"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    payload = {
        "embeds": [
            {
                "title": f"Auto-Proxy Cloudflare \u2014 {domain}",
                "description": (
                    f"**Dominio:** `{domain}`\n"
                    f"**Estado:** {state_str}\n"
                    f"**Hora:** {ts}"
                ),
                "color": 0xFF4444 if blocked else 0x44FF88,
            }
        ]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        log.debug("Discord notification sent for %s (blocked=%s)", domain, blocked)
    except Exception as e:
        log.warning("Failed to send Discord notification: %s", e)

# ---------------------------------------------------------------------------
# Per-domain state and processing
# ---------------------------------------------------------------------------

# state[domain] = {"proxied": None | True | False, "zone_id": str | None}
# proxied=None  -> initial/unknown state
# proxied=False -> proxy disabled by this service
# proxied=True  -> proxy re-enabled by this service
state: dict = {}


def process_domain(domain: str) -> None:
    result = check_domain(domain)
    if result is None:
        return  # API failure, will retry next cycle

    domain_blocked: bool = result.get("domain_blocked", False)
    current = state.setdefault(domain, {"proxied": None, "zone_id": None})

    log.debug(
        "Domain %s: blocked=%s proxy_state=%s",
        domain, domain_blocked, current["proxied"],
    )

    if domain_blocked and current["proxied"] is not False:
        log.info("Domain %s is BLOCKED by La Liga. Disabling Cloudflare proxy.", domain)
        root_zone = get_root_zone(domain)
        zone_id = get_zone_id(root_zone)
        if not zone_id:
            log.error("Cannot find zone ID for %s \u2014 skipping.", domain)
            return
        records = get_dns_records(zone_id, domain)
        if not records:
            log.warning("No DNS records found for %s in zone %s.", domain, zone_id)
            return
        # Only patch records that are currently proxied
        to_patch = [rec for rec in records if rec.get("proxied", False)]
        if not to_patch:
            log.debug("All records for %s are already unproxied.", domain)
            current["proxied"] = False
            current["zone_id"] = zone_id
            return
        all_ok = all(set_proxy(zone_id, rec["id"], domain, False) for rec in to_patch)
        if all_ok:
            current["proxied"] = False
            current["zone_id"] = zone_id
            notify_discord(domain, blocked=True)
        else:
            log.error("Some records for %s could not be unproxied \u2014 will retry next cycle.", domain)

    elif not domain_blocked and current["proxied"] is False:
        log.info("Domain %s is UNBLOCKED. Re-enabling Cloudflare proxy.", domain)
        zone_id = current.get("zone_id") or get_zone_id(get_root_zone(domain))
        if not zone_id:
            log.error("Cannot find zone ID for %s \u2014 skipping.", domain)
            return
        records = get_dns_records(zone_id, domain)
        if not records:
            log.warning("No DNS records found for %s in zone %s.", domain, zone_id)
            return
        # Only patch records that are currently unproxied
        to_patch = [rec for rec in records if not rec.get("proxied", True)]
        if not to_patch:
            log.debug("All records for %s are already proxied.", domain)
            current["proxied"] = True
            return
        all_ok = all(set_proxy(zone_id, rec["id"], domain, True) for rec in to_patch)
        if all_ok:
            current["proxied"] = True
            notify_discord(domain, blocked=False)
        else:
            log.error("Some records for %s could not be re-proxied \u2014 will retry next cycle.", domain)

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_running = True


def _handle_signal(signum, frame):
    global _running
    log.info("Received signal %s, shutting down gracefully...", signum)
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Validate credentials
    has_token = bool(CF_API_TOKEN)
    has_legacy = bool(CF_API_KEY and CF_EMAIL)
    if not (has_token or has_legacy):
        log.critical(
            "No Cloudflare credentials configured. "
            "Set CF_API_TOKEN, or both CF_API_KEY and CF_EMAIL."
        )
        sys.exit(1)

    if not DOMAINS_RAW.strip():
        log.critical("No DOMAINS configured. Set the DOMAINS environment variable.")
        sys.exit(1)

    domains = [d.strip() for d in DOMAINS_RAW.split(",") if d.strip()]

    auth_method = "API Token" if has_token else "Global API Key"
    log.info("Starting auto-proxy-cloudflare (auth: %s)", auth_method)
    log.info("Monitoring %d domain(s): %s", len(domains), ", ".join(domains))
    log.info("Check interval: %d seconds", CHECK_INTERVAL)
    if DISCORD_WEBHOOK_URL:
        log.info("Discord notifications enabled.")

    while _running:
        log.debug("--- Starting check cycle ---")
        for domain in domains:
            if not _running:
                break
            process_domain(domain)
        # Sleep in 1-second steps to respond quickly to SIGTERM
        for _ in range(CHECK_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    log.info("Shutdown complete.")


if __name__ == "__main__":
    main()
