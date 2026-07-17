"""Tests for the Modi mascot pack and per-mascot base_scale.

The pet transitions through a fixed set of animation states; a mascot that omits
one falls back to idle. These lock in that Modi covers every state, that its
frames are in-bounds and non-blank, and that base_scale keeps the render size
consistent with the window size the UI computes.
"""
import json
import os

import pytest
from src.constants import PetState


MODI_DIR = os.path.join("assets", "sprites", "modi")


def _modi_meta():
    with open(os.path.join(MODI_DIR, "metadata.json"), encoding="utf-8") as f:
        return json.load(f)


def _modi_map():
    with open(os.path.join(MODI_DIR, "mascot_spritesheet_map.json"), encoding="utf-8") as f:
        return json.load(f)


# Every state the state machine can drive the pet into.
REQUIRED_STATES = {
    PetState.IDLE, PetState.WALK, PetState.WAVE, PetState.TALK, PetState.THINK,
    PetState.LISTEN, PetState.SLEEP, PetState.SIT, PetState.DRAGGED,
    PetState.CROUCH, PetState.LAUNCH, PetState.FALL, PetState.LANDING,
}


def test_modi_pack_files_exist():
    assert os.path.exists(os.path.join(MODI_DIR, "metadata.json"))
    assert os.path.exists(os.path.join(MODI_DIR, "spritesheet.png"))


def test_modi_covers_every_engine_state():
    anims = set(_modi_meta()["animations"])
    missing = REQUIRED_STATES - anims
    assert not missing, f"Modi is missing states (would fall back to idle): {missing}"


def test_modi_frames_are_in_bounds():
    """Every frame rect must lie inside the sheet — an out-of-bounds crop renders
    blank, exactly the failure mode we hit with screen capture. Sheet size is
    read from the map so this survives a re-export at different dimensions."""
    meta = _modi_meta()
    grid = _modi_map()["grid"]
    sheet_w, sheet_h = grid["sheet_width"], grid["sheet_height"]
    for name, anim in meta["animations"].items():
        for fr in anim["frames"]:
            assert fr["x"] + fr["w"] <= sheet_w, f"{name} frame exceeds sheet width"
            assert fr["y"] + fr["h"] <= sheet_h, f"{name} frame exceeds sheet height"


def test_base_scale_shrinks_reported_frame_size(qapp, monkeypatch):
    """base_scale must fold into BOTH the render scale and the frame_width/height
    the window sizes to, or the window and the sprite would mismatch."""
    from src.config import Config
    from src.animation.sprite_loader import SpriteLoader

    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    monkeypatch.setattr(Config, "ANIMATION_SCALE", 1.0)
    loader = SpriteLoader()

    assert loader.base_scale == pytest.approx(0.40)
    # native cells (from the map) shrink by base_scale
    grid = _modi_map()["grid"]
    assert loader.frame_width == int(grid["cell_width"] * 0.40)
    assert loader.frame_height == int(grid["cell_height"] * 0.40)
    # Rendered frame matches the reported window size (scale_factor == base here)
    frames = loader.get_animation_frames("idle")
    assert frames and frames[0].height() == loader.frame_height


def test_default_mascot_has_no_base_scale(qapp, monkeypatch):
    """Sanity: the default pack (no base_scale field) renders 1:1 as before."""
    from src.config import Config
    from src.animation.sprite_loader import SpriteLoader

    monkeypatch.setattr(Config, "SELECTED_MASCOT", "default")
    loader = SpriteLoader()
    assert loader.base_scale == 1.0
    assert loader.frame_width == 138  # unchanged from the original pack
