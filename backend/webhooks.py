"""
ThrowSync — Custom Webhooks
Send game events as HTTP POST to any URL.
Supports Zapier, IFTTT, Home Assistant, Make.com, n8n, and any REST endpoint.
"""
MODULE_VERSION = "1.0.0"

import logging
import asyncio
import time
import json
from typing import Optional

logger = logging.getLogger("throwsync")

DEFAULT_WEBHOOK_CONFIG = {
    "enabled": False,
    "webhooks": [],  # List of webhook definitions
}

# All events that can trigger webhooks
AVAILABLE_EVENTS = {
    "180":               {"label": "180 geworfen",         "icon": "🔥", "category": "score"},
    "match_won":         {"label": "Match gewonnen",       "icon": "🏆", "category": "game"},
    "game_won":          {"label": "Leg gewonnen",         "icon": "✅", "category": "game"},
    "game_on":           {"label": "Match gestartet",      "icon": "🎯", "category": "game"},
    "busted":            {"label": "Überworfen",           "icon": "💥", "category": "game"},
    "player_change":     {"label": "Spielerwechsel",       "icon": "🔄", "category": "game"},
    "checkout_possible": {"label": "Checkout möglich",     "icon": "🎯", "category": "score"},
    "bullseye":          {"label": "Bullseye",             "icon": "🎯", "category": "score"},
    "high_score":        {"label": "High Score (≥100)",    "icon": "💪", "category": "score"},
    "achievement":       {"label": "Achievement freigeschaltet", "icon": "🏅", "category": "misc"},
}

# Rate limiting: max 1 webhook per URL per second
_last_sent: dict[str, float] = {}
RATE_LIMIT_SECONDS = 1.0


def create_webhook_template() -> dict:
    """Return a blank webhook definition."""
    return {
        "id": "",
        "name": "Neuer Webhook",
        "url": "",
        "enabled": True,
        "events": ["180", "match_won"],  # default events
        "headers": {},        # custom HTTP headers
        "secret": "",         # optional HMAC secret for signature
        "include_stats": False,  # include player stats in payload
        "last_status": None,  # last HTTP status code
        "last_sent": None,    # timestamp of last successful send
    }


def build_payload(event_name: str, data: dict, include_stats: bool = False) -> dict:
    """Build the JSON payload for a webhook POST."""
    payload = {
        "event": event_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "ThrowSync",
    }

    # Event-specific data
    if data:
        payload["player"] = data.get("player_name", "")
        payload["score"] = data.get("round_score", 0)

        # Game context
        if data.get("remaining"):
            payload["remaining"] = data["remaining"]
        if data.get("checkout"):
            payload["checkout"] = data["checkout"]
        if data.get("darts_thrown"):
            payload["darts_thrown"] = data["darts_thrown"]
        if data.get("average"):
            payload["average"] = data["average"]
        if data.get("leg_number"):
            payload["leg"] = data["leg_number"]

    # Achievement data
    if event_name == "achievement" and data:
        payload["achievement"] = data.get("achievement_name", "")
        payload["achievement_tier"] = data.get("achievement_tier", "")

    return payload


async def send_webhook(webhook: dict, payload: dict) -> dict:
    """Send a single webhook POST. Returns {success, status, error}."""
    import aiohttp

    url = webhook.get("url", "")
    if not url:
        return {"success": False, "error": "Keine URL"}

    # Rate limiting
    now = time.time()
    last = _last_sent.get(url, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return {"success": False, "error": "Rate limit"}
    _last_sent[url] = now

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ThrowSync-Webhook/1.0",
    }

    # Add custom headers
    custom_headers = webhook.get("headers", {})
    if custom_headers:
        headers.update(custom_headers)

    # Optional HMAC signature
    secret = webhook.get("secret", "")
    if secret:
        import hmac
        import hashlib
        body_bytes = json.dumps(payload).encode()
        sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        headers["X-ThrowSync-Signature"] = f"sha256={sig}"

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                status = resp.status
                success = 200 <= status < 300
                if not success:
                    body = await resp.text()
                    logger.warning(f"Webhook {webhook.get('name', '?')}: HTTP {status} — {body[:200]}")
                else:
                    logger.debug(f"Webhook {webhook.get('name', '?')}: HTTP {status} OK")
                return {"success": success, "status": status}
    except asyncio.TimeoutError:
        logger.warning(f"Webhook {webhook.get('name', '?')}: Timeout")
        return {"success": False, "error": "Timeout (5s)"}
    except Exception as e:
        logger.warning(f"Webhook {webhook.get('name', '?')}: {e}")
        return {"success": False, "error": str(e)[:200]}


async def fire_webhooks(config_manager, event_name: str, data: dict = None):
    """Fire all matching webhooks for an event. Non-blocking."""
    cfg = config_manager.get("webhook_config", DEFAULT_WEBHOOK_CONFIG)
    if not cfg.get("enabled", False):
        return

    webhooks = cfg.get("webhooks", [])
    if not webhooks:
        return

    # Special mapping: player_change with high score → "high_score" event
    effective_event = event_name
    if event_name == "player_change" and data:
        score = data.get("round_score", 0)
        if score >= 100:
            effective_event = "high_score"

    for wh in webhooks:
        if not wh.get("enabled", True):
            continue
        if not wh.get("url"):
            continue
        events = wh.get("events", [])
        if effective_event not in events:
            continue

        payload = build_payload(effective_event, data or {}, wh.get("include_stats", False))

        async def _send(webhook=wh, pl=payload):
            result = await send_webhook(webhook, pl)
            # Update last status in config
            webhook["last_status"] = result.get("status") or result.get("error", "Error")
            if result.get("success"):
                webhook["last_sent"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            config_manager.set("webhook_config", cfg)
            # Don't save() here to avoid disk thrashing — it'll save on next config change

        asyncio.create_task(_send())
