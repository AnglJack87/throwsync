"""
ThrowSync — Spotify Integration
Controls Spotify playback via Web API.
Uses Authorization Code + PKCE flow (no client secret needed).
"""
MODULE_VERSION = "1.0.0"

import logging
import time
import secrets
import hashlib
import base64
import json

logger = logging.getLogger("throwsync")

DEFAULT_SPOTIFY_CONFIG = {
    "enabled": False,
    "client_id": "",
    "access_token": "",
    "refresh_token": "",
    "token_expires_at": 0,
    "redirect_uri": "",  # Auto-set from server URL
    "duck_on_event": True,
    "duck_level": 20,  # Spotify volume 0-100 during events
    "restore_level": 60,  # Normal volume
}

# PKCE state
_code_verifier = ""
_state = ""

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"


def generate_pkce():
    """Generate PKCE code verifier + challenge."""
    global _code_verifier, _state
    _code_verifier = secrets.token_urlsafe(64)[:128]
    _state = secrets.token_urlsafe(16)
    digest = hashlib.sha256(_code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
    return code_challenge, _state


def get_auth_url(client_id: str, redirect_uri: str) -> str:
    """Build Spotify authorization URL with PKCE."""
    code_challenge, state = generate_pkce()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{SPOTIFY_AUTH_URL}?{query}"


async def exchange_code(client_id: str, code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    import aiohttp
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": _code_verifier,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(SPOTIFY_TOKEN_URL, data=data) as resp:
            result = await resp.json()
            if resp.status == 200:
                return {
                    "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token", ""),
                    "expires_in": result.get("expires_in", 3600),
                }
            else:
                logger.error(f"Spotify token exchange failed: {result}")
                return {"error": result.get("error_description", "Token exchange failed")}


async def refresh_access_token(client_id: str, refresh_token: str) -> dict:
    """Refresh an expired access token."""
    import aiohttp
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(SPOTIFY_TOKEN_URL, data=data) as resp:
            result = await resp.json()
            if resp.status == 200:
                return {
                    "access_token": result["access_token"],
                    "refresh_token": result.get("refresh_token", refresh_token),
                    "expires_in": result.get("expires_in", 3600),
                }
            else:
                logger.error(f"Spotify refresh failed: {result}")
                return {"error": result.get("error_description", "Refresh failed")}


async def spotify_api(method: str, endpoint: str, token: str, data: dict = None) -> dict:
    """Make authenticated Spotify API call."""
    import aiohttp
    url = f"{SPOTIFY_API_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        if method == "GET":
            async with session.get(url, headers=headers) as resp:
                if resp.status == 204:
                    return {"success": True}
                return await resp.json() if resp.status == 200 else {"error": resp.status}
        elif method == "PUT":
            async with session.put(url, headers=headers, json=data or {}) as resp:
                if resp.status == 204:
                    return {"success": True}
                try:
                    return await resp.json()
                except Exception:
                    return {"success": resp.status < 300}
        elif method == "POST":
            async with session.post(url, headers=headers, json=data or {}) as resp:
                if resp.status == 204:
                    return {"success": True}
                try:
                    return await resp.json()
                except Exception:
                    return {"success": resp.status < 300}


async def get_valid_token(config_manager) -> str:
    """Get a valid access token, refreshing if expired."""
    cfg = config_manager.get("spotify_config", DEFAULT_SPOTIFY_CONFIG)
    token = cfg.get("access_token", "")
    expires = cfg.get("token_expires_at", 0)
    
    if not token:
        return ""
    
    if time.time() > expires - 60:  # Refresh 60s before expiry
        refresh = cfg.get("refresh_token", "")
        client_id = cfg.get("client_id", "")
        if refresh and client_id:
            result = await refresh_access_token(client_id, refresh)
            if "access_token" in result:
                cfg["access_token"] = result["access_token"]
                if result.get("refresh_token"):
                    cfg["refresh_token"] = result["refresh_token"]
                cfg["token_expires_at"] = time.time() + result.get("expires_in", 3600)
                config_manager.set("spotify_config", cfg)
                config_manager.save()
                return result["access_token"]
            else:
                return ""
        return ""
    
    return token
