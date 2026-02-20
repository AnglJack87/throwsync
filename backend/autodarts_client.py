"""
Autodarts Client - Multi-Board Support
Each board has its own WebSocket connection, credentials, and assigned ESP devices.
Supports multiple Autodarts accounts simultaneously.
"""
MODULE_VERSION = "1.4.0"

import asyncio
import json
import logging
from typing import Optional

from event_defaults import DEFAULT_EVENT_MAPPINGS, get_merged_events

try:
    import aiohttp
except ImportError:
    aiohttp = None
    logging.warning("aiohttp nicht installiert — Autodarts WebSocket deaktiviert. Führe install.sh aus!")

from config_manager import ConfigManager

logger = logging.getLogger("autodarts-client")


class AutodartsBoardConnection:
    """A single connection to one Autodarts board."""

    KEYCLOAK_TOKEN_URL = "https://login.autodarts.io/realms/autodarts/protocol/openid-connect/token"
    KEYCLOAK_CLIENT_ID = "developer-darts-caller"
    KEYCLOAK_CLIENT_SECRET = "e7ex8OkiE3SAN0HhHfqCj1Iap5RhQARu"
    WS_URL = "wss://api.autodarts.io/ms/v0/subscribe"

    def __init__(self, board_config: dict, device_manager, event_mappings: dict):
        self.board_id = board_config.get("board_id", "")
        self.name = board_config.get("name", f"Board {self.board_id[:8]}")
        self.assigned_devices = board_config.get("assigned_devices", [])
        self.enabled = board_config.get("enabled", True)
        self.account_username = board_config.get("account_username", "") or board_config.get("account_email", "")
        self.account_password = board_config.get("account_password", "")

        # Legacy: if api_key is set but no password, keep old behavior hint
        self.api_key = board_config.get("api_key", "")

        self.device_manager = device_manager
        self.event_mappings = event_mappings
        self.event_callback = None  # Set by AutodartsClient for logging
        self.caller_callback = None  # Set by AutodartsClient for caller sounds

        self.connected = False
        self._ws = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._active_effect_task: Optional[asyncio.Task] = None
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._current_match_id: Optional[str] = None
        self._last_game_finished: bool = False
        # ── Caller turn tracking ──
        self._turn_score: int = 0           # Accumulated points in current turn
        self._darts_in_turn: int = 0        # Number of darts thrown this turn
        self._busted: bool = False           # Bust flag set by match state
        self._score_announced: bool = False  # Prevents double-announcement
        self._announce_task: Optional[asyncio.Task] = None  # Delayed announcement
        # ── Match state tracking ──
        self._last_player_index: int = -1
        self._last_scores: Optional[list] = None
        self._my_player_index: int = -1     # Which player index is "me" (board owner)
        self._is_local_match: bool = True   # Local = all players same board, no opponent_turn
        self._bot_player_indices: set = set()  # Indices of bot/CPU players
        self._match_player_names: list = [] # Player names from Autodarts match data
        self._last_activated_player: str = ""  # Last auto-activated profile name

    async def _get_keycloak_token(self) -> bool:
        """Authenticate with Autodarts Keycloak and get access token."""
        if not self.account_username or not self.account_password:
            logger.error(f"Board '{self.name}': Benutzername oder Passwort fehlt")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                data = {
                    "client_id": self.KEYCLOAK_CLIENT_ID,
                    "client_secret": self.KEYCLOAK_CLIENT_SECRET,
                    "scope": "openid",
                    "grant_type": "password",
                    "username": self.account_username,
                    "password": self.account_password,
                }
                async with session.post(self.KEYCLOAK_TOKEN_URL, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        self._access_token = result.get("access_token")
                        self._refresh_token = result.get("refresh_token")
                        expires_in = result.get("expires_in", 300)
                        import time
                        self._token_expires_at = time.time() + expires_in - 30  # 30s safety
                        logger.info(f"Board '{self.name}': Keycloak Login erfolgreich (Token gueltig fuer {expires_in}s)")
                        return True
                    elif resp.status == 401:
                        body = await resp.text()
                        logger.error(f"Board '{self.name}': Login fehlgeschlagen - falsche E-Mail/Passwort. {body}")
                        return False
                    else:
                        body = await resp.text()
                        logger.error(f"Board '{self.name}': Keycloak Fehler {resp.status}: {body}")
                        return False
        except Exception as e:
            logger.error(f"Board '{self.name}': Keycloak Verbindung fehlgeschlagen: {e}")
            return False

    async def _refresh_keycloak_token(self) -> bool:
        """Refresh the access token using refresh_token."""
        if not self._refresh_token:
            return await self._get_keycloak_token()

        try:
            async with aiohttp.ClientSession() as session:
                data = {
                    "client_id": self.KEYCLOAK_CLIENT_ID,
                    "client_secret": self.KEYCLOAK_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                }
                async with session.post(self.KEYCLOAK_TOKEN_URL, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        self._access_token = result.get("access_token")
                        self._refresh_token = result.get("refresh_token", self._refresh_token)
                        expires_in = result.get("expires_in", 300)
                        import time
                        self._token_expires_at = time.time() + expires_in - 30
                        logger.info(f"Board '{self.name}': Token erfolgreich erneuert")
                        return True
                    else:
                        logger.warning(f"Board '{self.name}': Token-Refresh fehlgeschlagen, versuche neuen Login...")
                        return await self._get_keycloak_token()
        except Exception as e:
            logger.error(f"Board '{self.name}': Token-Refresh Fehler: {e}")
            return await self._get_keycloak_token()

    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token, refreshing if needed."""
        import time
        if self._access_token and time.time() < self._token_expires_at:
            return True
        if self._refresh_token:
            return await self._refresh_keycloak_token()
        return await self._get_keycloak_token()

    async def connect(self):
        """Connect to this board's Autodarts WebSocket via Keycloak auth."""
        if not self.account_username or not self.account_password:
            logger.warning(f"Board '{self.name}': Benutzername oder Passwort fehlt")
            return

        if not self.enabled:
            logger.info(f"Board '{self.name}' ist deaktiviert")
            return

        if aiohttp is None:
            logger.error(f"Board '{self.name}': aiohttp nicht installiert! Fuehre install.sh aus.")
            return

        logger.info(f"Verbinde Board '{self.name}' (ID: {self.board_id[:8]}...)...")

        try:
            # Step 1: Keycloak login
            if not await self._get_keycloak_token():
                logger.error(f"Board '{self.name}': Authentifizierung fehlgeschlagen")
                return

            # Step 2: Connect WebSocket with Bearer token header
            self._session = aiohttp.ClientSession()
            headers = {"Authorization": f"Bearer {self._access_token}"}
            logger.info(f"Board '{self.name}': Verbinde WebSocket...")
            self._ws = await self._session.ws_connect(self.WS_URL, headers=headers)
            
            # Step 3: Subscribe to board events
            subscribe_boards = {
                "channel": "autodarts.boards",
                "type": "subscribe",
                "topic": f"{self.board_id}.matches"
            }
            await self._ws.send_json(subscribe_boards)
            logger.info(f"Board '{self.name}': Subscribed to board matches")
            
            subscribe_events = {
                "channel": "autodarts.boards",
                "type": "subscribe",
                "topic": f"{self.board_id}.events"
            }
            await self._ws.send_json(subscribe_events)
            logger.info(f"Board '{self.name}': Subscribed to board events")
            
            self.connected = True
            logger.info(f"Board '{self.name}' verbunden! Zugewiesene Geraete: {self.assigned_devices}")

            await self._trigger_event("idle")

            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_message(data)
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        logger.error(f"Board '{self.name}' Message-Handler Fehler: {e}")
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                    break

        except Exception as e:
            logger.error(f"Board '{self.name}' Fehler: {e}")
        finally:
            self.connected = False
            if self._session:
                await self._session.close()
                self._session = None

    async def disconnect(self):
        self.connected = False
        if self._active_effect_task and not self._active_effect_task.done():
            self._active_effect_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
            self._session = None

    async def _handle_message(self, data: dict):
        channel = data.get("channel", "")
        topic = data.get("topic", "")
        
        # Unwrap channel-based messages
        inner = data
        if channel and "data" in data:
            inner_data = data["data"]
            if isinstance(inner_data, dict):
                inner = inner_data
            elif isinstance(inner_data, str):
                try:
                    inner = json.loads(inner_data)
                except (json.JSONDecodeError, TypeError):
                    inner = data
        
        # Log message (verbose for match state to debug data structure)
        if channel == "autodarts.matches" and ".state" in topic:
            raw_state = json.dumps(inner)[:500] if isinstance(inner, dict) else str(inner)[:500]
            logger.debug(f"Board '{self.name}' STATE RAW <<< {raw_state}")
        else:
            raw_str = json.dumps(data)[:300]
            logger.debug(f"Board '{self.name}' WS <<< {raw_str}")
        
        event_type = inner.get("event", "")
        
        # ── Handle board events channel ──
        if channel == "autodarts.boards" and ".events" in topic:
            # Normalize board event names to our internal format
            normalized = {
                "Started": "board-ready",       # Board ready to detect (fires after each takeout)
                "Stopped": "board-stopped",
                "Throw detected": "throw",
                "Takeout started": "takeout-started",
                "Takeout finished": "takeout-finished",
                "Manual reset": "manual-reset",
                "Calibration started": "calibration-started",
                "Calibration finished": "calibration-finished",
            }.get(event_type, event_type)
            
            # For throws: build payload from throw data
            if normalized == "throw":
                throw_data = inner.get("throw", {})
                segment = throw_data.get("segment", {})
                throw_number = inner.get("throwNumber", 0)
                dart_score = segment.get("number", 0) * segment.get("multiplier", 0)
                payload = {
                    "segment": segment,
                    "number": segment.get("number", 0),
                    "multiplier": segment.get("multiplier", 0),
                    "ring": segment.get("bed", ""),
                    "points": dart_score,
                    "dartIndex": throw_number - 1 if throw_number > 0 else None,
                }
                self._turn_score += dart_score
                self._darts_in_turn += 1
                events = self._map_events(normalized, payload)
                logger.info(f"Board '{self.name}' DART #{self._darts_in_turn}: "
                           f"{segment.get('name','')} = {dart_score}pts (turn total: {self._turn_score})")
                # Caller: broadcast single dart sound
                await self._broadcast_caller("throw", payload)
                # Broadcast throw data for display overlay
                await self._broadcast_display_state({
                    "type": "throw",
                    "throw_text": segment.get("name", f"{dart_score}"),
                    "points": dart_score,
                    "turn_score": self._turn_score,
                    "darts_in_turn": self._darts_in_turn,
                })
                
                # Detect "my" player index: first throw in a match = me
                # When a dart physically hits MY board, the current player MUST be me
                if self._last_player_index >= 0:
                    if self._my_player_index < 0:
                        self._my_player_index = self._last_player_index
                        logger.info(f"Board '{self.name}': Spieler-Erkennung (Dart) -> Ich bin Player #{self._my_player_index}")
                    # Physical dart on my board in online match → confirm this is my player
                    if not self._is_local_match and self._my_player_index != self._last_player_index:
                        old = self._my_player_index
                        self._my_player_index = self._last_player_index
                        logger.info(f"Board '{self.name}': Dart-Korrektur → Ich bin Player #{self._my_player_index} (war: #{old})")
                
                # Fire my_turn on dart hit (a physical dart on this board = this player is active here)
                is_bot_active = self._last_player_index in self._bot_player_indices
                if not is_bot_active:
                    await self._trigger_event("my_turn")
                    await self._broadcast_display_state({
                        "type": "turn_update",
                        "is_my_turn": True,
                        "is_local": self._is_local_match,
                        "has_bot": len(self._bot_player_indices) > 0,
                        "my_player_index": self._my_player_index,
                    })
                
                # ── After 3rd dart: schedule score announcement ──
                # Short delay lets match-state bust-detection fire first
                if self._darts_in_turn >= 3 and not self._score_announced:
                    if self._announce_task and not self._announce_task.done():
                        self._announce_task.cancel()
                    self._announce_task = asyncio.create_task(
                        self._delayed_score_announcement(self._turn_score)
                    )
            else:
                events = self._map_events(normalized, inner)
                if events:
                    logger.info(f"Board '{self.name}' TRIGGER: {normalized} -> {events}")
                # Caller: broadcast board events (takeout, ready, etc.)
                caller_map = {
                    "takeout-started": "takeout_start",
                    "takeout-finished": "takeout_finished",
                    "board-ready": "board_ready",
                    "board-stopped": "board_stopped",
                }
                if normalized in caller_map:
                    if normalized == "takeout-finished":
                        # ── Takeout = turn definitely over ──
                        # Cancel any pending delayed announcement
                        if self._announce_task and not self._announce_task.done():
                            self._announce_task.cancel()
                        
                        if not self._score_announced and self._darts_in_turn > 0:
                            # Score not yet announced — 3-dart trigger didn't fire
                            if self._busted:
                                logger.info(f"Board '{self.name}' TAKEOUT: Bust → nur 'busted' Sound")
                                await self._broadcast_caller("busted")
                                await self._trigger_event("busted")
                            else:
                                logger.info(f"Board '{self.name}' TAKEOUT: Score-Backup → {self._turn_score} "
                                           f"({self._darts_in_turn} Darts)")
                                await self._broadcast_caller("player_change", {"round_score": self._turn_score})
                                # LED effect for score range
                                score_events = self._map_events("turn-score", {"points": self._turn_score})
                                for ev in score_events:
                                    m = self.event_mappings.get(ev)
                                    if m and m.get("enabled", True):
                                        await self._trigger_event(ev)
                        elif self._score_announced:
                            logger.debug(f"Board '{self.name}' TAKEOUT: Score bereits angesagt, skip")
                        
                        # Reset turn state
                        self._turn_score = 0
                        self._darts_in_turn = 0
                        self._busted = False
                        self._score_announced = False
                    
                    await self._broadcast_caller(caller_map[normalized])
            
            if events:
                await self._dispatch_events(normalized, events)
            return
        
        # ── Handle match start/finish from .matches channel ──
        if channel == "autodarts.boards" and ".matches" in topic:
            match_id = inner.get("id", "")
            if event_type == "start" and match_id:
                logger.info(f"Board '{self.name}': Match gestartet ({match_id[:12]}...), subscribe to match state...")
                self._current_match_id = match_id
                self._last_game_scores = None
                self._last_turn_player = None
                try:
                    await self._ws.send_json({
                        "channel": "autodarts.matches",
                        "type": "subscribe",
                        "topic": f"{match_id}.state"
                    })
                except Exception as e:
                    logger.error(f"Board '{self.name}': Match subscribe fehlgeschlagen: {e}")
                
                # ── Try to detect my player index from match data ──
                self._turn_score = 0
                self._darts_in_turn = 0
                self._last_player_index = -1
                self._last_scores = None
                self._busted = False
                self._score_announced = False
                self._my_player_index = -1
                self._is_local_match = True  # Assume local until proven online
                self._bot_player_indices = set()
                self._match_player_names = []
                self._last_activated_player = ""
                
                # Log full match data for debugging
                logger.info(f"Board '{self.name}' MATCH DATA: {json.dumps(inner)[:1200]}")
                
                # Detect local vs online + player index + bots from players array
                players = inner.get("players", inner.get("participants", []))
                board_ids_in_match = set()
                if isinstance(players, list) and len(players) > 0:
                    for idx, p in enumerate(players):
                        if isinstance(p, dict):
                            # Extract player name (try ALL known Autodarts field names)
                            p_name = (p.get("name") or p.get("displayName") or 
                                     p.get("userName") or p.get("username") or 
                                     p.get("userId") or p.get("id") or "")
                            if not p_name:
                                p_name = f"Player {idx+1}"
                            self._match_player_names.append(str(p_name))
                            
                            # Detect bot/CPU players
                            is_bot = False
                            if p.get("cpuPPR") is not None or p.get("cpu") is not None:
                                is_bot = True
                            if p.get("isBot") or p.get("isCpu") or p.get("bot"):
                                is_bot = True
                            # Check name patterns for bot
                            name_lower = str(p_name).lower()
                            if any(b in name_lower for b in ("bot", "cpu", "computer", "ki ")):
                                is_bot = True
                            # No boardId often means it's a bot
                            p_board = p.get("boardId", p.get("board_id", p.get("board", "")))
                            if is_bot:
                                self._bot_player_indices.add(idx)
                                logger.info(f"Board '{self.name}': Spieler #{idx} '{p_name}' ist ein BOT")
                            
                            if p_board:
                                board_ids_in_match.add(p_board)
                                if p_board == self.board_id:
                                    self._my_player_index = idx
                                    logger.info(f"Board '{self.name}': Spieler #{idx} '{p_name}' → MEIN Board (boardId match)")
                        elif isinstance(p, str):
                            self._match_player_names.append(p)
                    
                    logger.info(f"Board '{self.name}': Match-Spieler: {self._match_player_names}, Bots: {self._bot_player_indices}")
                    
                    # Determine local vs online:
                    # Online = multiple different board IDs in the match
                    # Local = all players on same board (or no board IDs)
                    if len(board_ids_in_match) > 1:
                        self._is_local_match = False
                        logger.info(f"Board '{self.name}': ONLINE Match ({len(board_ids_in_match)} Boards)")
                    else:
                        self._is_local_match = True
                        has_bots = len(self._bot_player_indices) > 0
                        logger.info(f"Board '{self.name}': LOKALES Match ({len(players)} Spieler, Bots={has_bots})")
                
                # For local matches: detect my index
                if self._is_local_match and self._my_player_index < 0 and self._match_player_names:
                    # I'm the first non-bot player
                    for idx in range(len(self._match_player_names)):
                        if idx not in self._bot_player_indices:
                            self._my_player_index = idx
                            break
                    if self._my_player_index < 0:
                        self._my_player_index = 0
                    logger.info(f"Board '{self.name}': Lokales Match → Ich bin Player #{self._my_player_index}")
                elif not self._match_player_names:
                    # No player data at match start → will be detected from first state update
                    logger.info(f"Board '{self.name}': Keine Spieler-Daten im Match-Start, warte auf State...")
                
                # Fallback for online: try hostBoardId
                if not self._is_local_match and self._my_player_index < 0:
                    host_board = inner.get("hostBoardId", inner.get("creatorBoardId", ""))
                    if host_board == self.board_id:
                        self._my_player_index = 0
                        logger.info(f"Board '{self.name}': Spieler aus Host-Board erkannt -> Player #0 (Host)")
                
                if self._my_player_index < 0:
                    logger.info(f"Board '{self.name}': Spieler-Index noch unbekannt, wird beim ersten Wurf erkannt")
                
                # Trigger game_on
                events = self._map_events("game-started", inner)
                if events:
                    logger.info(f"Board '{self.name}' TRIGGER: match-start -> {events}")
                    await self._dispatch_events("game-started", events)
                await self._broadcast_caller("game_on")
                
                # Immediately show green → will be corrected to red on opponent board
                # when first state update arrives with player/board data
                await self._trigger_event("my_turn")
                logger.info(f"Board '{self.name}': Match-Start → my_turn (grün) als Standard")
                
                # Auto-activate first player with walk-on sound
                if self._match_player_names:
                    first_player = self._match_player_names[0]
                    self._last_activated_player = first_player
                    try:
                        from main import auto_activate_player_by_name
                        await auto_activate_player_by_name(first_player, play_walk_on=True)
                    except Exception as e:
                        logger.debug(f"Board '{self.name}': Walk-On Aktivierung: {e}")
            elif event_type == "finish" and match_id:
                logger.info(f"Board '{self.name}': Match beendet ({match_id[:12]}...)")
                events = self._map_events("match-won", inner)
                if events:
                    logger.info(f"Board '{self.name}' TRIGGER: match-finish -> {events}")
                    await self._dispatch_events("match-won", events)
                await self._broadcast_caller("match_won")
                # Back to idle
                await self._trigger_event("idle")
            return
        
        # ── Handle match state updates from .state channel ──
        if channel == "autodarts.matches" and ".state" in topic:
            await self._handle_match_state(inner)
            return
        
        # ── Fallback: direct event handling ──
        if event_type:
            events = self._map_events(event_type, inner)
            if events:
                logger.info(f"Board '{self.name}' TRIGGER: {event_type} -> {events}")
                await self._dispatch_events(event_type, events)

    async def _handle_match_state(self, state: dict):
        """Process match state updates.
        Used for:
        1. Bust detection → immediate announcement (cancels delayed score)
        2. Game/Match won → immediate (cancels delayed score)
        3. Turn indicator (my_turn / opponent_turn LED events)
        4. Checkout possible announcement
        Score announcements: 3rd dart trigger (primary) + takeout-finished (backup).
        """
        if not isinstance(state, dict):
            return
        
        # ── Detect players, board IDs, local/online from EVERY state update ──
        players = state.get("players", state.get("participants", []))
        if isinstance(players, list) and len(players) > 0:
            board_ids_in_state = set()
            my_idx_from_board = -1
            names_were_empty = not self._match_player_names
            
            for idx, p in enumerate(players):
                if isinstance(p, dict):
                    # Extract names if we don't have them yet
                    if idx >= len(self._match_player_names):
                        p_name = (p.get("name") or p.get("displayName") or 
                                 p.get("userName") or p.get("username") or
                                 p.get("userId") or p.get("id") or f"Player {idx+1}")
                        self._match_player_names.append(str(p_name))
                        logger.info(f"Board '{self.name}': Spieler #{idx} Name aus State: '{p_name}'")
                    
                    # Detect bots from state data
                    if idx not in self._bot_player_indices:
                        is_bot = (p.get("cpuPPR") is not None or p.get("cpu") is not None
                                 or p.get("isBot") or p.get("isCpu") or p.get("bot"))
                        if is_bot:
                            self._bot_player_indices.add(idx)
                            logger.info(f"Board '{self.name}': Spieler #{idx} als BOT erkannt (aus State)")
                    
                    # Collect board IDs from ALL players
                    p_board = p.get("boardId", p.get("board_id", p.get("board", "")))
                    if p_board:
                        board_ids_in_state.add(p_board)
                        if p_board == self.board_id:
                            my_idx_from_board = idx
            
            # Re-evaluate local vs online when we have board ID data
            if len(board_ids_in_state) > 1 and self._is_local_match:
                self._is_local_match = False
                logger.info(f"Board '{self.name}': ★ ONLINE Match erkannt! ({len(board_ids_in_state)} Boards in State-Daten)")
            
            # Assign my_player_index from board ID (override local fallback)
            if my_idx_from_board >= 0 and my_idx_from_board != self._my_player_index:
                old = self._my_player_index
                self._my_player_index = my_idx_from_board
                logger.info(f"Board '{self.name}': ★ Spieler aus Board-ID erkannt → Player #{my_idx_from_board} (war: #{old})")
        
        # ── Parse state (try multiple field names for API compatibility) ──
        game_finished = (state.get("gameFinished") or state.get("finished") 
                        or state.get("isFinished") or False)
        match_finished = state.get("matchFinished") or state.get("finished") or False
        game_winner = state.get("gameWinner", -1)
        
        player_index = -1
        for key in ("player", "currentPlayer", "activePlayer", "turn"):
            val = state.get(key, -1)
            if isinstance(val, int) and val >= 0:
                player_index = val
                break
        
        game_scores = []
        for key in ("gameScores", "scores", "playerScores", "remainingScores"):
            val = state.get(key, [])
            if isinstance(val, list) and len(val) > 0:
                game_scores = val
                break
        
        logger.debug(f"Board '{self.name}' STATE: player={player_index} scores={game_scores} "
                     f"finished={game_finished} my={self._my_player_index} last={self._last_player_index}")
        
        # ── Detect game won / match won ──
        if game_finished and game_winner >= 0:
            if not self._last_game_finished:
                self._last_game_finished = True
                # Cancel pending score announcement — game won supersedes
                if self._announce_task and not self._announce_task.done():
                    self._announce_task.cancel()
                self._score_announced = True
                
                if match_finished:
                    logger.info(f"Board '{self.name}' STATE: >>> MATCH WON (winner: {game_winner}) <<<")
                    await self._trigger_event("match_won")
                    await self._broadcast_caller("match_won")
                else:
                    logger.info(f"Board '{self.name}' STATE: >>> GAME WON (winner: {game_winner}) <<<")
                    await self._trigger_event("game_won")
                    await self._broadcast_caller("game_won")
        elif not game_finished:
            if self._last_game_finished:
                # ── New leg/game starting! Reset turn tracking ──
                logger.info(f"Board '{self.name}' STATE: Neues Leg startet → Turn-Tracking Reset")
                self._last_player_index = -1
                self._turn_score = 0
                self._darts_in_turn = 0
                self._busted = False
                self._score_announced = False
            self._last_game_finished = False
        
        # ── Detect BUST via score comparison ──
        if (player_index >= 0 and self._last_player_index >= 0 
                and player_index != self._last_player_index 
                and self._last_scores and game_scores):
            prev = self._last_player_index
            if prev < len(game_scores) and prev < len(self._last_scores):
                old_score = self._last_scores[prev]
                new_score = game_scores[prev]
                if old_score == new_score and self._turn_score > 0:
                    # Score unchanged but darts were thrown → BUST!
                    self._busted = True
                    logger.info(f"Board '{self.name}' STATE: BUST! Player {prev} "
                               f"score bleibt {old_score} (turn={self._turn_score})")
                    
                    # Announce bust immediately — cancel any pending score
                    if not self._score_announced:
                        if self._announce_task and not self._announce_task.done():
                            self._announce_task.cancel()
                        self._score_announced = True
                        await self._broadcast_caller("busted")
                        await self._trigger_event("busted")
                        logger.info(f"Board '{self.name}' STATE: Bust sofort angesagt")
                else:
                    logger.debug(f"Board '{self.name}' STATE: Player {prev}: "
                                f"{old_score} → {new_score} (diff={old_score - new_score})")
        
        # ── Detect player change → Turn indicator + Auto-Profile ──
        if player_index >= 0 and player_index != self._last_player_index:
            # Get active player name from match data
            active_player_name = ""
            if player_index < len(self._match_player_names):
                active_player_name = self._match_player_names[player_index]
            
            is_bot_turn = player_index in self._bot_player_indices
            has_bots = len(self._bot_player_indices) > 0
            is_first_turn = self._last_player_index < 0
            
            logger.info(f"Board '{self.name}' STATE: {'Erster Spieler' if is_first_turn else 'Spielerwechsel'} "
                       f"{self._last_player_index} → {player_index} "
                       f"('{active_player_name}', local={self._is_local_match}, bot_turn={is_bot_turn}, has_bots={has_bots}, my={self._my_player_index})")
            
            if self._is_local_match and not has_bots:
                # LOCAL 2 HUMANS: Both at same board → always green
                logger.info(f"Board '{self.name}': LOKAL 2 Spieler → {active_player_name} ist dran → my_turn (grün)")
                await self._trigger_event("my_turn")
                await self._broadcast_display_state({
                    "type": "turn_update",
                    "is_my_turn": True,
                    "is_local": True,
                    "has_bot": False,
                    "active_player_index": player_index,
                    "active_player_name": active_player_name,
                })
            elif self._is_local_match and has_bots:
                # LOCAL VS BOT: green when human, red when bot
                if is_bot_turn:
                    logger.info(f"Board '{self.name}': BOT '{active_player_name}' ist dran → opponent_turn (rot)")
                    await self._trigger_event("opponent_turn")
                else:
                    logger.info(f"Board '{self.name}': ICH bin dran (vs Bot) → my_turn (grün)")
                    await self._trigger_event("my_turn")
                await self._broadcast_display_state({
                    "type": "turn_update",
                    "is_my_turn": not is_bot_turn,
                    "is_local": True,
                    "has_bot": True,
                    "active_player_index": player_index,
                    "active_player_name": active_player_name,
                })
            elif self._my_player_index >= 0:
                # ONLINE: Distinguish my turn vs opponent
                is_my = player_index == self._my_player_index
                if is_my:
                    logger.info(f"Board '{self.name}': ONLINE → ICH BIN DRAN → my_turn (grün)")
                    await self._trigger_event("my_turn")
                else:
                    logger.info(f"Board '{self.name}': ONLINE → GEGNER DRAN → opponent_turn (rot)")
                    await self._trigger_event("opponent_turn")
                await self._broadcast_display_state({
                    "type": "turn_update",
                    "is_my_turn": is_my,
                    "is_local": False,
                    "has_bot": False,
                    "my_player_index": self._my_player_index,
                    "active_player_index": player_index,
                    "active_player_name": active_player_name,
                })
            else:
                # Player index not yet known — still fire a display update
                logger.info(f"Board '{self.name}': Spieler-Index unbekannt, nur Display-Update")
                await self._broadcast_display_state({
                    "type": "turn_update",
                    "is_my_turn": None,
                    "active_player_index": player_index,
                    "active_player_name": active_player_name,
                })
            
            # ── Auto-activate matching player profile ──
            if active_player_name and active_player_name != self._last_activated_player:
                self._last_activated_player = active_player_name
                try:
                    from main import auto_activate_player_by_name
                    logger.info(f"Board '{self.name}': Auto-Profil Suche für '{active_player_name}'...")
                    await auto_activate_player_by_name(active_player_name)
                except Exception as e:
                    logger.warning(f"Board '{self.name}': Auto-Profil Fehler für '{active_player_name}': {e}")
            
            self._last_player_index = player_index
        
        # ── Detect checkout possible ──
        if (not game_finished and game_scores 
                and player_index >= 0 and player_index < len(game_scores)):
            remaining = game_scores[player_index]
            if 2 <= remaining <= 170:
                if player_index != self._last_player_index:
                    await self._broadcast_caller("checkout_possible", {"rest": remaining})
        
        # ── Update score tracking ──
        if game_scores:
            self._last_scores = list(game_scores)
            # Determine my remaining score
            my_remaining = None
            if self._my_player_index >= 0 and self._my_player_index < len(game_scores):
                my_remaining = game_scores[self._my_player_index]
            # Active player's remaining
            active_remaining = None
            if player_index >= 0 and player_index < len(game_scores):
                active_remaining = game_scores[player_index]
            # Use my score if known, otherwise active player's
            remaining = my_remaining if my_remaining is not None else active_remaining
            # Determine if it's my turn
            is_my_turn = None
            has_bots = len(self._bot_player_indices) > 0
            if self._is_local_match and not has_bots:
                is_my_turn = True  # Local 2 humans: always green
            elif self._is_local_match and has_bots:
                is_my_turn = player_index not in self._bot_player_indices  # Green for human, red for bot
            elif self._my_player_index >= 0:
                is_my_turn = (player_index == self._my_player_index)  # Online
            
            active_name = ""
            if player_index < len(self._match_player_names):
                active_name = self._match_player_names[player_index]
            
            await self._broadcast_display_state({
                "type": "state_update",
                "remaining": remaining,
                "player_index": player_index,
                "my_player_index": self._my_player_index,
                "is_my_turn": is_my_turn,
                "is_local": self._is_local_match,
                "has_bot": has_bots,
                "scores": game_scores,
                "active_player_name": active_name,
            })

    async def _dispatch_events(self, event_type: str, events: list):
        """Dispatch mapped events based on event type logic."""
        if event_type in ("throw", "darts-thrown", "dart-thrown"):
            throw_events = [e for e in events if e.startswith("throw_")]
            dart_events = [e for e in events if e.startswith("dart_")]
            
            for ev in throw_events:
                mapping = self.event_mappings.get(ev)
                if mapping and mapping.get("enabled", True):
                    await self._trigger_event(ev)
                    break
            
            for ev in dart_events:
                mapping = self.event_mappings.get(ev)
                if mapping and mapping.get("enabled", True):
                    await self._trigger_event(ev)
                    break
        
        elif event_type in ("turn-score", "darts-pulled", "round-score"):
            for ev in events:
                mapping = self.event_mappings.get(ev)
                if mapping and mapping.get("enabled", True):
                    await self._trigger_event(ev)
        
        else:
            for ev in events:
                mapping = self.event_mappings.get(ev)
                if mapping and mapping.get("enabled", True):
                    await self._trigger_event(ev)
                    break

    def _map_events(self, event_type: str, payload: dict) -> list:
        """Map Autodarts API event to internal event name(s).
        Returns list because one event can trigger multiple effects (e.g. specific + general).
        Most specific enabled event wins.
        """
        results = []

        # ── Game lifecycle ──
        simple = {
            "game-started": "game_on",
            "checkout-possible": "checkout_possible",
            "next-to-throw": "next_throw",
            "turn-change": "player_change",
            "legs.player-change": "player_change",
            "takeout-started": "takeout_start",
            "takeout-finished": "takeout_finished",
        }
        if event_type in simple:
            return [simple[event_type]]

        # ── Game/Match won ──
        if event_type in ("game-won", "leg-won", "checkout"):
            game = payload.get("game", {})
            finish_score = payload.get("dartsThrownValue", 0) or payload.get("finishScore", 0)

            # Check if this is a match win or leg win
            is_match_won = payload.get("isMatchWon", False) or payload.get("matchFinished", False)
            if is_match_won:
                results.append("match_won")
            else:
                results.append("game_won")

            # High finish check
            if finish_score >= 100:
                results.append("high_finish")
            else:
                results.append("checkout_hit")

            return results

        if event_type == "match-won":
            return ["match_won"]

        if event_type == "game-ended":
            return ["game_ended"]

        # ── Busted ──
        if event_type == "busted":
            return ["busted"]

        # ── Single dart thrown ──
        if event_type in ("throw", "darts-thrown", "dart-thrown"):
            segment = payload.get("segment", {})
            number = segment.get("number", 0) or payload.get("number", 0)
            multiplier = segment.get("multiplier", 1) or payload.get("multiplier", 1)
            ring = segment.get("bed", "") or payload.get("ring", "")
            total = payload.get("points", 0) or payload.get("score", 0)
            dart_index = payload.get("dartIndex", None) or payload.get("throwIndex", None)

            # 1) Most specific: Bullseye/Bull/Miss or specific number (throw_t20)
            # 2) General segment type (throw_triple)
            # 3) Dart position (dart_1)
            if ring in ("DBull", "D-Bull", "D25") or (number == 25 and multiplier == 2):
                results.append("throw_bullseye")
            elif ring in ("SBull", "S-Bull", "S25", "Bull") or (number == 25 and multiplier == 1):
                results.append("throw_bull")
            elif total == 0 or ring in ("Miss", "Outside", "Bounce", "M"):
                results.append("throw_miss")
            else:
                # Specific number first (e.g. throw_t20, throw_d16)
                prefix = {1: "s", 2: "d", 3: "t"}.get(multiplier, "s")
                results.append(f"throw_{prefix}{number}")
                # General segment type as fallback
                general = {1: "throw_single", 2: "throw_double", 3: "throw_triple"}.get(multiplier, "throw_single")
                results.append(general)

            # Dart position (1st, 2nd, 3rd) — separate category, handled concurrently
            if dart_index is not None:
                results.append(f"dart_{dart_index + 1}")

            return results

        if event_type in ("dart1-thrown", "dart2-thrown", "dart3-thrown"):
            idx = {"dart1-thrown": 1, "dart2-thrown": 2, "dart3-thrown": 3}[event_type]
            return [f"dart_{idx}"]

        # ── Round score (Aufnahme / Darts gezogen) ──
        if event_type in ("turn-score", "darts-pulled", "round-score"):
            points = payload.get("points", 0) or payload.get("score", 0)

            # Check busted
            if payload.get("busted", False):
                return ["busted"]

            # Player change
            results.append("player_change")

            # Score area triggers (most specific first)
            if points == 26:
                results.append("score_26")  # Bed & Breakfast special
            if points >= 180:
                results.append("score_180")
            elif points >= 171:
                results.append("score_171_179")
            elif points >= 150:
                results.append("score_150_170")
            elif points >= 140:
                results.append("score_140_149")
            elif points >= 120:
                results.append("score_120_139")
            elif points >= 100:
                results.append("score_100_119")
            elif points >= 80:
                results.append("score_80_99")
            elif points >= 60:
                results.append("score_60_79")
            elif points >= 40:
                results.append("score_40_59")
            elif points >= 20:
                results.append("score_20_39")
            elif points >= 1:
                results.append("score_1_19")
            else:
                results.append("score_0")

            return results

        # ── Cricket events ──
        if event_type == "cricket-hit":
            return ["cricket_hit"]
        if event_type == "cricket-closed":
            return ["cricket_closed"]
        if event_type == "cricket-miss":
            return ["cricket_miss"]

        return results

    async def _trigger_event(self, event_name: str):
        """Trigger LED effect ONLY on this board's assigned devices.
        Supports single effects and effect chains (sequence of effects)."""
        mapping = self.event_mappings.get(event_name)
        if not mapping or not mapping.get("enabled", True):
            return

        logger.info(f"Board '{self.name}' -> {event_name} ({mapping.get('label', '')}) -> {self.assigned_devices}")

        # Log event for UI
        if self.event_callback:
            try:
                await self.event_callback(event_name, self.name, {
                    "label": mapping.get("label", ""),
                    "devices": self.assigned_devices,
                    "fx": mapping.get("effect", {}).get("fx", 0),
                })
            except Exception:
                pass

        if self._active_effect_task and not self._active_effect_task.done():
            self._active_effect_task.cancel()

        if not self.assigned_devices:
            logger.warning(f"Board '{self.name}': Keine Geraete zugewiesen!")
            return

        # Check for effect chain
        chain = mapping.get("chain", None)
        if chain and len(chain) > 0:
            self._active_effect_task = asyncio.create_task(self._run_chain(chain))
        else:
            # Single effect (backward compatible)
            effect = mapping.get("effect", {})
            duration = mapping.get("duration", 0)
            await self._send_effect(effect)
            if duration > 0:
                self._active_effect_task = asyncio.create_task(self._revert_after(duration))

    async def _send_effect(self, effect: dict):
        """Send a single effect to all assigned devices."""
        state = {"on": True}
        seg = {}
        for key in ("fx", "sx", "ix", "pal", "col"):
            if key in effect:
                seg[key] = effect[key]
        if seg:
            state["seg"] = [seg]
        if "bri" in effect:
            state["bri"] = effect["bri"]
        for device_id in self.assigned_devices:
            await self.device_manager.set_device_state(device_id, state)

    async def _run_chain(self, chain: list):
        """Run a sequence of effects (effect chain)."""
        try:
            for step in chain:
                effect = step.get("effect", {})
                duration = step.get("duration", 1.0)
                await self._send_effect(effect)
                if duration > 0:
                    await asyncio.sleep(duration)
            # After chain completes, revert to idle
            await self._trigger_event("idle")
        except asyncio.CancelledError:
            pass

    async def _revert_after(self, seconds: float):
        await asyncio.sleep(seconds)
        await self._trigger_event("idle")

    async def simulate_event(self, event_name: str):
        logger.info(f"Board '{self.name}' Simulation: {event_name}")
        await self._trigger_event(event_name)

    # ── Caller Sound System ──────────────────────────────────────────────────

    async def _delayed_score_announcement(self, score: int):
        """Announce round score after a short delay.
        The delay allows match-state bust detection to fire first.
        If bust is detected during the delay, only 'busted' is announced.
        """
        try:
            await asyncio.sleep(0.2)  # Wait 200ms for bust detection from match state
            
            if self._score_announced:
                return  # Already announced (by match state bust or game won)
            
            self._score_announced = True
            
            if self._busted:
                logger.info(f"Board '{self.name}' 3-DART: Bust erkannt → 'busted' Sound")
                await self._broadcast_caller("busted")
                await self._trigger_event("busted")
            else:
                logger.info(f"Board '{self.name}' 3-DART: Score {score} ansagen")
                await self._broadcast_caller("player_change", {"round_score": score})
                # LED effect for score range
                score_events = self._map_events("turn-score", {"points": score})
                for ev in score_events:
                    m = self.event_mappings.get(ev)
                    if m and m.get("enabled", True):
                        await self._trigger_event(ev)
        except asyncio.CancelledError:
            pass  # Takeout handler or game_won took over

    async def _broadcast_caller(self, event_type: str, payload: dict = None):
        """Determine and broadcast caller sounds based on event type."""
        if not self.caller_callback:
            return
        payload = payload or {}
        sounds = self._determine_caller_sounds(event_type, payload)
        if sounds:
            try:
                await self.caller_callback(sounds, event_type, payload)
            except Exception as e:
                logger.debug(f"Caller broadcast error: {e}")

    async def _broadcast_display_state(self, data: dict):
        """Broadcast game state to display overlay via WebSocket."""
        if not self.caller_callback:
            return
        try:
            # Use the same broadcast mechanism — caller_callback's parent has broadcast_ws
            from main import broadcast_ws
            await broadcast_ws({"type": "display_state", "data": data})
        except Exception:
            pass  # Display broadcasting is optional

    def _determine_caller_sounds(self, event_type: str, payload: dict) -> list:
        """Map game event to list of caller sound keys to play.
        Returns list of dicts: [{key, priority}]  (frontend resolves to filenames)
        """
        sounds = []

        # ── Game lifecycle ──
        if event_type == "game_on":
            sounds.append({"key": "caller_game_on", "priority": 1})

        elif event_type == "game_won":
            sounds.append({"key": "caller_game_won", "priority": 1})
            sounds.append({"key": "caller_ambient_gameshot", "priority": 2})

        elif event_type == "match_won":
            sounds.append({"key": "caller_match_won", "priority": 1})
            sounds.append({"key": "caller_ambient_matchshot", "priority": 2})

        elif event_type == "busted":
            sounds.append({"key": "caller_busted", "priority": 1})
            sounds.append({"key": "caller_ambient_busted", "priority": 2})

        elif event_type == "game_ended":
            sounds.append({"key": "caller_game_ended", "priority": 1})

        # ── Player change / round score ──
        elif event_type == "player_change":
            score = payload.get("round_score", 0)
            if score is not None and score >= 0:
                # Individual score calling (0-180)
                score_key = f"caller_score_{min(score, 180)}"
                sounds.append({"key": score_key, "priority": 1})
                # Ambient for special scores
                if score >= 180:
                    sounds.append({"key": "caller_ambient_180", "priority": 2})
                elif score >= 140:
                    sounds.append({"key": "caller_ambient_140_plus", "priority": 2})
                elif score >= 100:
                    sounds.append({"key": "caller_ambient_ton_plus", "priority": 2})
                elif score == 26:
                    sounds.append({"key": "caller_ambient_score_26", "priority": 2})
                elif score < 20 and score > 0:
                    sounds.append({"key": "caller_ambient_low_score", "priority": 2})
                elif score == 0:
                    sounds.append({"key": "caller_ambient_score_0", "priority": 2})
            # Player change ambient
            sounds.append({"key": "caller_player_change", "priority": 3})

        # ── Single dart thrown ──
        elif event_type == "throw":
            segment = payload.get("segment", {})
            number = segment.get("number", 0) or payload.get("number", 0)
            multiplier = segment.get("multiplier", 1) or payload.get("multiplier", 1)
            ring = segment.get("bed", "") or payload.get("ring", "")
            dart_score = payload.get("points", 0) or (number * multiplier)

            # Determine field name key
            if ring in ("DBull", "D-Bull", "D25") or (number == 25 and multiplier == 2):
                field_key = "caller_bullseye"
                effect_key = "caller_effect_bullseye"
                generic_key = "caller_double"
            elif ring in ("SBull", "S-Bull", "S25", "Bull") or (number == 25 and multiplier == 1):
                field_key = "caller_bull"
                effect_key = "caller_effect_bull"
                generic_key = "caller_single"
            elif dart_score == 0 or ring in ("Miss", "Outside", "Bounce", "M"):
                field_key = "caller_miss"
                effect_key = "caller_effect_miss"
                generic_key = None
            else:
                prefix = {1: "s", 2: "d", 3: "t"}.get(multiplier, "s")
                field_key = f"caller_{prefix}{number}"
                effect_key = f"caller_effect_{prefix}{number}"
                gen_name = {1: "single", 2: "double", 3: "triple"}.get(multiplier, "single")
                generic_key = f"caller_{gen_name}"

            # Single dart name/score/effect sounds (frontend picks based on call_every_dart mode)
            sounds.append({"key": field_key, "priority": 1, "type": "dart_name"})
            if generic_key:
                sounds.append({"key": generic_key, "priority": 2, "type": "dart_name_fallback"})
            sounds.append({"key": effect_key, "priority": 1, "type": "dart_effect"})
            if generic_key:
                gen_effect = f"caller_effect_{generic_key.split('_')[-1]}" if generic_key else None
                if gen_effect:
                    sounds.append({"key": gen_effect, "priority": 2, "type": "dart_effect_fallback"})

            # Dart score as number (for call_every_dart=1 mode)
            if dart_score >= 0:
                sounds.append({"key": f"caller_score_{min(dart_score, 180)}", "priority": 1, "type": "dart_score"})

            # Store for round accumulation
            payload["dart_score"] = dart_score

        # ── Checkout ──
        elif event_type == "checkout_possible":
            rest = payload.get("rest", 0) or payload.get("remaining", 0)
            if rest and 2 <= rest <= 170:
                sounds.append({"key": "caller_you_require", "priority": 1})
                sounds.append({"key": f"caller_checkout_{rest}", "priority": 2})
            sounds.append({"key": "caller_ambient_checkout_possible", "priority": 3})

        elif event_type in ("checkout_hit", "high_finish"):
            sounds.append({"key": "caller_ambient_high_finish", "priority": 2})

        # ── Takeout / Board ──
        elif event_type == "takeout_start":
            sounds.append({"key": "caller_takeout_start", "priority": 1})
        elif event_type == "takeout_finished":
            sounds.append({"key": "caller_takeout_finished", "priority": 1})
        elif event_type == "board_ready":
            sounds.append({"key": "caller_board_ready", "priority": 1})

        # ── Cricket ──
        elif event_type == "cricket_hit":
            sounds.append({"key": "caller_cricket_hit", "priority": 1})
        elif event_type == "cricket_closed":
            sounds.append({"key": "caller_cricket_closed", "priority": 1})
        elif event_type == "cricket_miss":
            sounds.append({"key": "caller_cricket_miss", "priority": 1})

        return sounds

    def to_dict(self) -> dict:
        return {
            "board_id": self.board_id,
            "name": self.name,
            "account_username": self.account_username,
            "assigned_devices": self.assigned_devices,
            "enabled": self.enabled,
            "connected": self.connected,
            "authenticated": bool(self._access_token),
        }


class AutodartsClient:
    """Manages multiple Autodarts board connections simultaneously."""

    # Event defaults are in event_defaults.py (no external deps)
    DEFAULT_EVENT_MAPPINGS = DEFAULT_EVENT_MAPPINGS  # re-export for backward compat

    def __init__(self, config: ConfigManager, device_manager):
        self.config = config
        self.device_manager = device_manager
        self.boards: dict[str, AutodartsBoardConnection] = {}
        self._connect_tasks: dict[str, asyncio.Task] = {}
        self.event_callback = None  # async fn(event_name, board_name, details)
        self.caller_callback = None  # async fn(sounds, event_name, data)

    @property
    def connected(self) -> bool:
        return any(b.connected for b in self.boards.values())

    def _get_merged_mappings(self) -> dict:
        """Get event mappings: defaults + saved overrides merged."""
        from event_defaults import get_merged_events
        saved = self.config.get("event_mappings", {})
        return get_merged_events(saved)

    def reload_mappings(self):
        mappings = self._get_merged_mappings()
        for board in self.boards.values():
            board.event_mappings = mappings

    async def connect_all(self):
        """Connect all enabled boards."""
        boards = self.config.get("boards", [])
        mappings = self._get_merged_mappings()
        for bc in boards:
            if bc.get("enabled", True):
                await self.connect_board(bc, mappings)

    async def connect_board(self, board_config: dict, mappings: dict = None):
        board_id = board_config.get("board_id", "")
        if not board_id:
            return

        if mappings is None:
            mappings = self._get_merged_mappings()

        if board_id in self.boards:
            await self.boards[board_id].disconnect()

        conn = AutodartsBoardConnection(board_config, self.device_manager, mappings)
        conn.event_callback = self.event_callback
        conn.caller_callback = self.caller_callback
        self.boards[board_id] = conn

        async def connect_loop():
            while True:
                await conn.connect()
                if not board_config.get("auto_reconnect", True):
                    break
                await asyncio.sleep(5)
                fresh = self.config.get("boards", [])
                cfg = next((b for b in fresh if b.get("board_id") == board_id), None)
                if not cfg or not cfg.get("enabled", True):
                    break

        self._connect_tasks[board_id] = asyncio.create_task(connect_loop())

    async def disconnect_board(self, board_id: str):
        if board_id in self._connect_tasks:
            self._connect_tasks[board_id].cancel()
            del self._connect_tasks[board_id]
        if board_id in self.boards:
            await self.boards[board_id].disconnect()
            del self.boards[board_id]

    async def disconnect(self):
        for bid in list(self.boards.keys()):
            await self.disconnect_board(bid)

    def get_all_boards_status(self) -> list:
        boards = self.config.get("boards", [])
        result = []
        for bc in boards:
            bid = bc.get("board_id", "")
            conn = self.boards.get(bid)
            has_pw = bool(bc.get("account_password", ""))
            logger.debug(f"Board status {bid[:8]}...: keys={list(bc.keys())}, password_set={has_pw}")
            result.append({
                "board_id": bid,
                "name": bc.get("name", ""),
                "account_username": bc.get("account_username", "") or bc.get("account_email", ""),
                "assigned_devices": bc.get("assigned_devices", []),
                "enabled": bc.get("enabled", True),
                "auto_reconnect": bc.get("auto_reconnect", True),
                "connected": conn.connected if conn else False,
                "authenticated": conn._access_token is not None if conn else False,
                "password_set": has_pw,
            })
        return result

    async def simulate_event(self, event_name: str, board_id: str = None):
        if board_id and board_id in self.boards:
            await self.boards[board_id].simulate_event(event_name)
        else:
            for board in self.boards.values():
                await board.simulate_event(event_name)
