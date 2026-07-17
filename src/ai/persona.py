"""Per-mascot persona.

The character the pet plays now follows the selected mascot: each mascot folder
may carry a `persona.json` (name, LLM persona, and canned greeting / idle lines).
A mascot without one falls back to the global .env persona (Config.PET_NAME /
PET_PERSONA), so the default pack keeps its Ribbit personality unchanged.

Personas are cached per mascot; switching mascots just loads the other one.
"""
import os
import json
from typing import Dict

from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("Persona")


class Persona:
    def __init__(self, name: str, persona: str, greeting: str = "", idle_quip: str = ""):
        self.name = name
        self.persona = persona
        self.greeting = greeting        # shown on greet (startup / double-click wave)
        self.idle_quip = idle_quip      # shown when the user goes idle


_cache: Dict[str, Persona] = {}


def get_active_persona() -> Persona:
    """The persona for the currently selected mascot (Config.SELECTED_MASCOT)."""
    mascot = Config.SELECTED_MASCOT
    if mascot in _cache:
        return _cache[mascot]
    persona = _load_file(mascot)
    if persona is not None:
        _cache[mascot] = persona
        return persona
    # No per-mascot persona: use the global .env persona (Ribbit by default).
    # Not cached — PET_NAME/PET_PERSONA can change at runtime and must stay live.
    return Persona(Config.PET_NAME, Config.PET_PERSONA)


def _load_file(mascot: str):
    """Returns a Persona from the mascot's persona.json, or None if absent/bad."""
    path = os.path.join("assets", "sprites", mascot, "persona.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        logger.info(f"Loaded persona for mascot '{mascot}': {d.get('name')}")
        return Persona(
            d.get("name") or Config.PET_NAME,
            d.get("persona") or Config.PET_PERSONA,
            d.get("greeting", ""),
            d.get("idle_quip", ""),
        )
    except Exception as e:
        logger.error(f"Bad persona.json for '{mascot}': {e}. Using default persona.")
        return None


def invalidate():
    """Drop the cache (e.g. after editing a persona.json at runtime)."""
    _cache.clear()
