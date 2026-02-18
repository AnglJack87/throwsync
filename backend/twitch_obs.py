"""
ThrowSync — Twitch & OBS Integration
Send stream alerts to Twitch chat and OBS browser sources.

Features:
- OBS Browser Source overlay URL with real-time WebSocket events
- Twitch chat bot that posts game events
- Custom alert messages per event
"""
MODULE_VERSION = "1.0.0"

import logging
import asyncio

logger = logging.getLogger("twitch-obs")

DEFAULT_TWITCH_CONFIG = {
    "enabled": False,
    "channel": "",
    "bot_name": "ThrowSyncBot",
    "oauth_token": "",  # user provides their own
    "alerts": {
        "180": "\U0001F525 180!!! {player} wirft das Maximum! \U0001F525",
        "match_won": "\U0001F3C6 {player} gewinnt das Match! GG!",
        "game_won": "\u2705 {player} gewinnt das Leg!",
        "busted": "\U0001F4A5 {player} hat sich überworfen!",
        "high_score": "\U0001F4AA {player} mit {score} Punkten!",
        "bullseye": "\U0001F3AF BULLSEYE von {player}!",
        "achievement": "\U0001F3C5 {player} hat Achievement freigeschaltet: {achievement}!",
    },
    "min_high_score": 100,
    "post_scores": True,
    "post_achievements": True,
}

# OBS overlay is already handled by /display endpoint
# This module adds Twitch chat integration

class TwitchBot:
    """Simple Twitch IRC chat bot."""

    def __init__(self):
        self.reader = None
        self.writer = None
        self.connected = False
        self.channel = ""

    async def connect(self, channel: str, oauth_token: str, bot_name: str = "ThrowSyncBot"):
        """Connect to Twitch IRC."""
        try:
            self.reader, self.writer = await asyncio.open_connection('irc.chat.twitch.tv', 6667)
            self.writer.write(f"PASS oauth:{oauth_token}\r\n".encode())
            self.writer.write(f"NICK {bot_name.lower()}\r\n".encode())
            self.writer.write(f"JOIN #{channel.lower()}\r\n".encode())
            await self.writer.drain()
            self.connected = True
            self.channel = channel.lower()
            logger.info(f"Twitch bot connected to #{channel}")
            # Start PING handler
            asyncio.create_task(self._ping_handler())
            return True
        except Exception as e:
            logger.error(f"Twitch connection failed: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from Twitch IRC."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.connected = False
        self.reader = None
        self.writer = None
        logger.info("Twitch bot disconnected")

    async def send_message(self, message: str):
        """Send a message to the Twitch channel."""
        if not self.connected or not self.writer:
            return False
        try:
            self.writer.write(f"PRIVMSG #{self.channel} :{message}\r\n".encode())
            await self.writer.drain()
            return True
        except Exception as e:
            logger.error(f"Twitch send failed: {e}")
            self.connected = False
            return False

    async def _ping_handler(self):
        """Respond to Twitch PING to stay connected."""
        while self.connected and self.reader:
            try:
                data = await asyncio.wait_for(self.reader.readline(), timeout=300)
                line = data.decode('utf-8', errors='ignore').strip()
                if line.startswith('PING'):
                    self.writer.write("PONG :tmi.twitch.tv\r\n".encode())
                    await self.writer.drain()
            except asyncio.TimeoutError:
                # Send our own PING
                if self.writer:
                    self.writer.write("PING :tmi.twitch.tv\r\n".encode())
                    await self.writer.drain()
            except Exception:
                self.connected = False
                break


def format_alert(template: str, player: str = "", score: int = 0, achievement: str = "") -> str:
    """Format an alert message template with game data."""
    return template.format(
        player=player or "Spieler",
        score=score,
        achievement=achievement,
    )


# Global bot instance
twitch_bot = TwitchBot()
