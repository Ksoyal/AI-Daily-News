import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class TestEnvLookup:
    def test_empty_ai_model_uses_stable_default(self, monkeypatch):
        monkeypatch.setenv("AI_MODEL", "")

        reloaded_config = importlib.reload(config)

        assert reloaded_config.AI_MODEL == "gemini-3.6-flash"

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


class TestFallbackConfig:
    def _load_isolated_config(self, monkeypatch):
        # Exercise the real module defaults without changing other tests' imports
        # or reading a developer's local .env file.
        import dotenv
        monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
        spec = importlib.util.spec_from_file_location("isolated_config", config.__file__)
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)
        return isolated

    def test_fallback_is_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("AI_FALLBACK_MODEL", raising=False)
        assert self._load_isolated_config(monkeypatch).AI_FALLBACK_MODEL == ""

    def test_empty_fallback_stays_disabled(self, monkeypatch):
        monkeypatch.setenv("AI_FALLBACK_MODEL", "   ")
        assert self._load_isolated_config(monkeypatch).AI_FALLBACK_MODEL == ""

    def test_explicit_fallback_model_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("AI_FALLBACK_MODEL", " gemini-3.5-flash-lite ")
        assert self._load_isolated_config(monkeypatch).AI_FALLBACK_MODEL == "gemini-3.5-flash-lite"
