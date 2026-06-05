"""Tests for SkillPool config module."""

from __future__ import annotations

import os
from pathlib import Path

from skillpool.config import get_data_dir, get_host, get_log_level, get_port


class TestGetDataDir:
    def test_default_is_home_skillpool(self):
        os.environ.pop("SKILLPOOL_DATA_DIR", None)
        result = get_data_dir()
        assert result == Path.home() / ".skillpool"

    def test_env_override(self, tmp_path):
        os.environ["SKILLPOOL_DATA_DIR"] = str(tmp_path)
        result = get_data_dir()
        assert result == tmp_path
        del os.environ["SKILLPOOL_DATA_DIR"]


class TestGetLogLevel:
    def test_default_is_info(self):
        os.environ.pop("SKILLPOOL_LOG_LEVEL", None)
        assert get_log_level() == "INFO"

    def test_env_override(self):
        os.environ["SKILLPOOL_LOG_LEVEL"] = "debug"
        assert get_log_level() == "DEBUG"
        del os.environ["SKILLPOOL_LOG_LEVEL"]

    def test_uppercased(self):
        os.environ["SKILLPOOL_LOG_LEVEL"] = "warning"
        assert get_log_level() == "WARNING"
        del os.environ["SKILLPOOL_LOG_LEVEL"]


class TestGetHost:
    def test_default(self):
        os.environ.pop("SKILLPOOL_HOST", None)
        assert get_host() == "127.0.0.1"

    def test_env_override(self):
        os.environ["SKILLPOOL_HOST"] = "0.0.0.0"
        assert get_host() == "0.0.0.0"
        del os.environ["SKILLPOOL_HOST"]


class TestGetPort:
    def test_default(self):
        os.environ.pop("SKILLPOOL_PORT", None)
        assert get_port() == 8101

    def test_env_override(self):
        os.environ["SKILLPOOL_PORT"] = "9000"
        assert get_port() == 9000
        del os.environ["SKILLPOOL_PORT"]
