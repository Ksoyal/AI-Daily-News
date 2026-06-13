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
