"""SkillPool configuration — single source of truth for all paths and settings.

Environment variables:
  SKILLPOOL_DATA_DIR  — Base data directory (default: ~/.skillpool)
  SKILLPOOL_LOG_LEVEL — Log level (default: INFO)
  SKILLPOOL_HOST      — Server host (default: 127.0.0.1)
  SKILLPOOL_PORT      — Server port (default: 8101)
"""
from __future__ import annotations

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Return the SkillPool data directory, respecting SKILLPOOL_DATA_DIR env var."""
    env = os.environ.get("SKILLPOOL_DATA_DIR")
    return Path(env) if env else Path.home() / ".skillpool"


def get_log_level() -> str:
    """Return the log level, respecting SKILLPOOL_LOG_LEVEL env var."""
    return os.environ.get("SKILLPOOL_LOG_LEVEL", "INFO").upper()


def get_host() -> str:
    """Return the server host, respecting SKILLPOOL_HOST env var."""
    return os.environ.get("SKILLPOOL_HOST", "127.0.0.1")


def get_port() -> int:
    """Return the server port, respecting SKILLPOOL_PORT env var."""
    return int(os.environ.get("SKILLPOOL_PORT", "8101"))
