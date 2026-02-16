"""
Configuration Manager - Handles persistent configuration storage.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
import copy

logger = logging.getLogger("config-manager")

DEFAULT_CONFIG = {
    "devices": [],
    "autodarts": {
        "board_id": "",
        "api_key": "",
        "auto_connect": False,
    },
    "event_mappings": {},  # Will be populated with defaults on first load
    "presets": [],
    "settings": {
        "poll_interval": 10,
        "default_brightness": 128,
        "transition_time": 7,
        "theme": "dark",
        "language": "de",
    },
}


class ConfigManager:
    """Manages application configuration with JSON persistence."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self._config: dict = copy.deepcopy(DEFAULT_CONFIG)

    def load(self):
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge with defaults (keep new defaults, override with saved values)
                self._config = self._deep_merge(copy.deepcopy(DEFAULT_CONFIG), loaded)
                logger.info(f"Configuration loaded from {self.config_path}")
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                self._config = copy.deepcopy(DEFAULT_CONFIG)
        else:
            logger.info("No config file found, using defaults")
            self._config = copy.deepcopy(DEFAULT_CONFIG)
            self.save()

    def save(self):
        """Save configuration to file."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.debug("Configuration saved")
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """Set a configuration value."""
        self._config[key] = value

    def get_all(self) -> dict:
        """Get all configuration."""
        return copy.deepcopy(self._config)

    def import_config(self, data: dict):
        """Import configuration from a dict (e.g., from a file)."""
        self._config = self._deep_merge(copy.deepcopy(DEFAULT_CONFIG), data)
        self.save()
        logger.info("Configuration imported")

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deep merge override into base."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
