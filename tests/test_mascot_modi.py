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


def test_modi_free_will_variants_declared():
    """Modi's free-will variety: IDLE is a still stand or a chai sip; WALK is
    plain or with the jhola. All four backing animations must exist."""
    meta = _modi_meta()
    variants = meta.get("state_variants", {})
    assert variants.get("idle") == ["idle", "drink_tea"]
    assert variants.get("walk") == ["walk", "walk_bag"]
    for a in ("idle", "drink_tea", "walk", "walk_bag"):
        assert a in meta["animations"], f"variant animation '{a}' missing"


def test_modi_idle_variant_is_stationary_not_walking():
    """The IDLE state never translates the window, so no idle variant may use a
    walk cycle (that was the moonwalk). Stand + sip only."""
    meta = _modi_meta()
    mp = _modi_map()
    walk_ys = {mp["animations"]["walk"]["frames"][0]["y"],
               mp["animations"]["walk_bag"]["frames"][0]["y"]}
    for variant in meta["state_variants"]["idle"]:
        ys = {f["y"] for f in meta["animations"][variant]["frames"]}
        assert not (ys & walk_ys), f"idle variant '{variant}' uses walk frames (moonwalk)"


def test_modi_walk_variants_map_to_plain_and_bag_rows():
    meta = _modi_meta()
    mp = _modi_map()
    assert meta["animations"]["walk"]["frames"][0]["y"] == mp["animations"]["walk"]["frames"][0]["y"]
    assert meta["animations"]["walk_bag"]["frames"][0]["y"] == mp["animations"]["walk_bag"]["frames"][0]["y"]


def test_pick_animation_returns_declared_variants(qapp, monkeypatch):
    """pick_animation must only ever return a declared variant (or the state
    name when none) — a stray name would render blank/idle-fallback."""
    from src.config import Config
    from src.animation.sprite_loader import SpriteLoader
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    loader = SpriteLoader()
    assert {loader.pick_animation("idle") for _ in range(60)} == {"idle", "drink_tea"}
    assert {loader.pick_animation("walk") for _ in range(60)} == {"walk", "walk_bag"}
    assert loader.pick_animation("wave") == "wave"  # no variants -> state name


def test_modi_wave_is_the_namaste_row():
    """Modi greets with a namaste, not a Western hand-wave — the WAVE animation
    must come from the namaste row (this is what the greeting shows)."""
    meta = _modi_meta()
    namaste_y = _modi_map()["animations"]["namaste_a"]["frames"][0]["y"]
    assert meta["animations"]["wave"]["frames"][0]["y"] == namaste_y


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
