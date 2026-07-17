"""Tests for the per-mascot persona system (name, LLM persona, canned lines)."""
from src.config import Config
from src.ai import persona as persona_mod
from src.ai.persona import get_active_persona
from src.ai.prompts import build_system_prompt

_CTX = {"active_window": "VS Code", "current_time": "9pm", "pet_active_state": "idle"}


def test_modi_persona_loads_lines(monkeypatch):
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    persona_mod.invalidate()
    p = get_active_persona()
    assert p.name == "Modi"
    assert p.greeting == "Mitroonn...."
    assert p.idle_quip == "Anti-National h kya???"


def test_prompt_follows_selected_mascot(monkeypatch):
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    persona_mod.invalidate()
    prompt = build_system_prompt(_CTX, {}, conversational=True)
    assert "Modi" in prompt and "Mitron" in prompt


def test_default_mascot_falls_back_to_env_persona(monkeypatch):
    """No persona.json for the default pack -> global .env persona (Ribbit),
    read live so PET_NAME changes still take effect."""
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "default")
    monkeypatch.setattr(Config, "PET_NAME", "Ribbit")
    persona_mod.invalidate()
    p = get_active_persona()
    assert p.name == "Ribbit"
    assert p.greeting == ""      # default pack has no canned greeting
    assert p.idle_quip == ""


def test_env_fallback_is_live_not_cached(monkeypatch):
    """Changing PET_NAME must be reflected without a mascot switch."""
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "default")
    persona_mod.invalidate()
    monkeypatch.setattr(Config, "PET_NAME", "Zorp")
    assert get_active_persona().name == "Zorp"
    monkeypatch.setattr(Config, "PET_NAME", "Blorp")
    assert get_active_persona().name == "Blorp"
