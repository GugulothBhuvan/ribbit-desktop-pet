"""Regression tests for Phase 5 (AI hardening — see MVP_PLAN.md)."""
from src.config import Config
from src.ai.prompts import build_system_prompt
from src.ai.orchestrator import clamp_stream_text
from src.constants import MAX_CHARACTERS, MAX_CHARACTERS_CONVERSATION


# --- Persona is config-driven + two-tier reply length ------------------------

_BASE_CTX = {
    "active_window": "VS Code",
    "current_time": "10:00 AM",
    "pet_active_state": "idle",
    "battery_percent": None,
    "git_available": False,
    "test_outcome": "unknown",
}


def test_prompt_uses_configured_persona():
    """Name and persona come from Config, not a hardcoded string."""
    orig_name, orig_persona = Config.PET_NAME, Config.PET_PERSONA
    try:
        Config.PET_NAME = "Zorp"
        Config.PET_PERSONA = "You are Zorp, a grumpy space slug."
        prompt = build_system_prompt(_BASE_CTX, {})
        assert "Zorp" in prompt
        assert "grumpy space slug" in prompt
    finally:
        Config.PET_NAME, Config.PET_PERSONA = orig_name, orig_persona


def test_default_persona_is_ribbit():
    prompt = build_system_prompt(_BASE_CTX, {})
    assert "Ribbit" in prompt


def test_mode_selects_response_rules():
    """Ambient asides stay terse; conversation unlocks the back-and-forth rules."""
    ambient = build_system_prompt(_BASE_CTX, {}, conversational=False)
    chat = build_system_prompt(_BASE_CTX, {}, conversational=True)

    assert "150 characters" in ambient
    assert "quick aside" in ambient
    assert "150 characters" not in chat
    assert "have a conversation" in chat
    assert "450 characters" in chat


def test_conversation_cap_is_larger_than_ambient():
    assert MAX_CHARACTERS_CONVERSATION > MAX_CHARACTERS


def test_clamp_respects_conversation_budget():
    """A chunk that overflows the ambient cap but fits conversation must survive
    when the conversational limit is passed."""
    text = "x" * (MAX_CHARACTERS + 50)  # over ambient, under conversation
    out, final = clamp_stream_text(0, text, MAX_CHARACTERS_CONVERSATION)
    assert out == text
    assert final is False
    # Same chunk under the ambient cap gets cut
    out2, final2 = clamp_stream_text(0, text, MAX_CHARACTERS)
    assert final2 is True
    assert out2.endswith("…")


# --- 5.3: system prompt omits unavailable telemetry --------------------------

def test_prompt_omits_unavailable_fields():
    context = {
        "active_window": "VS Code",
        "current_time": "10:00 AM",
        "pet_active_state": "idle",
        "battery_percent": None,       # desktop: unknown
        "git_available": False,        # no watched project
        "test_outcome": "unknown",
    }
    prompt = build_system_prompt(context, {})
    assert "Battery" not in prompt
    assert "Git status" not in prompt
    assert "Pytest" not in prompt
    assert "VS Code" in prompt

def test_prompt_includes_available_fields_and_fact_bullets():
    context = {
        "active_window": "PyCharm",
        "current_time": "10:00 AM",
        "pet_active_state": "idle",
        "battery_percent": 42,
        "git_available": True,
        "git_uncommitted_count": 3,
        "git_last_commit": "fix bug",
        "test_outcome": "failed",
        "test_failed_count": 2,
    }
    prompt = build_system_prompt(context, {"user_name": "Bhuvan"})
    assert "Battery level: 42%" in prompt
    assert "3 uncommitted files" in prompt
    assert "failed (2 failed tests)" in prompt
    assert "- user_name: Bhuvan" in prompt
    # Never a raw dict repr of memories
    assert "{'user_name'" not in prompt


# --- 5.1: Krutrim vision payload & model gating -------------------------------

def test_krutrim_vision_payload_attaches_image():
    from src.ai.providers.krutrim import KrutrimProvider
    original = Config.KRUTRIM_MODEL
    try:
        Config.KRUTRIM_MODEL = "gemma-4-E4B-it"
        provider = KrutrimProvider()
        assert provider.supports_vision() is True

        payload = provider._build_payload("What's on screen?", {
            "system_prompt": "sys",
            "screenshot_bytes": b"fake-jpeg",
        })
        user_msg = payload["messages"][-1]
        assert isinstance(user_msg["content"], list)
        kinds = {part["type"] for part in user_msg["content"]}
        assert kinds == {"text", "image_url"}
        image_part = next(p for p in user_msg["content"] if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    finally:
        Config.KRUTRIM_MODEL = original

def test_krutrim_text_only_model_never_gets_image():
    from src.ai.providers.krutrim import KrutrimProvider
    original = Config.KRUTRIM_MODEL
    try:
        Config.KRUTRIM_MODEL = "gpt-oss-20b"
        provider = KrutrimProvider()
        assert provider.supports_vision() is False

        payload = provider._build_payload("hi", {"screenshot_bytes": b"fake"})
        assert isinstance(payload["messages"][-1]["content"], str)
    finally:
        Config.KRUTRIM_MODEL = original


# --- 5.1: screenshot downscale + JPEG on worker side --------------------------

def test_process_capture_downscales_and_encodes_jpeg(qapp):
    from PyQt6.QtGui import QImage, QColor
    from src.ai.vision import process_capture, MAX_DIMENSION

    big = QImage(2560, 1440, QImage.Format.Format_RGB32)
    big.fill(QColor(120, 80, 200))

    data = process_capture(big)
    assert len(data) > 0
    assert data[:2] == b"\xff\xd8", "output must be JPEG (SOI marker)"

    round_trip = QImage.fromData(data)
    assert max(round_trip.width(), round_trip.height()) <= MAX_DIMENSION


# --- 5.5: IDE probes disabled without a watched project ----------------------

def test_git_context_disabled_without_watch_dir():
    from src.ai.context_engine import ContextEngine
    original = Config.WATCH_PROJECT_DIR
    try:
        Config.WATCH_PROJECT_DIR = ""
        engine = ContextEngine()
        assert engine.get_git_context()["git_available"] is False
        assert engine.get_test_context()["recent_test_run_outcome"] == "unknown"
    finally:
        Config.WATCH_PROJECT_DIR = original

def test_git_context_targets_watch_dir():
    import os
    from src.ai.context_engine import ContextEngine
    original = Config.WATCH_PROJECT_DIR
    try:
        # This repo IS a git repo now — point the watcher at it explicitly
        Config.WATCH_PROJECT_DIR = os.getcwd()
        engine = ContextEngine()
        ctx = engine.get_git_context()
        assert ctx["git_available"] is True
        assert ctx["last_commit_message"] != "unknown"
    finally:
        Config.WATCH_PROJECT_DIR = original
