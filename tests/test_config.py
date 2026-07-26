import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class TestEnvLookup:
    def test_empty_env_value_uses_default(self, monkeypatch):
        monkeypatch.setenv("AI_MODEL", "")

        assert config._env("AI_MODEL", "default-model") == "default-model"

    def test_strips_env_value(self, monkeypatch):
        monkeypatch.setenv("AI_MODEL", "  model-name  ")

        assert config._env("AI_MODEL", "default-model") == "model-name"


class TestNumericEnvParsing:
    def test_env_int_parses_valid_value(self, monkeypatch):
        monkeypatch.setenv("MAX_ENTRIES", " 42 ")

        assert config._env_int("MAX_ENTRIES", 100) == 42

    def test_env_int_malformed_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("AI_TIMEOUT", "180s")

        assert config._env_int("AI_TIMEOUT", 180) == 180

    def test_env_int_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("HTTP_RETRIES", raising=False)

        assert config._env_int("HTTP_RETRIES", 3) == 3

    def test_env_float_parses_valid_value(self, monkeypatch):
        monkeypatch.setenv("AI_TEMPERATURE", "0.7")

        assert config._env_float("AI_TEMPERATURE", 0.5) == 0.7

    def test_env_float_malformed_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("AI_TEMPERATURE", "warm")

        assert config._env_float("AI_TEMPERATURE", 0.5) == 0.5
