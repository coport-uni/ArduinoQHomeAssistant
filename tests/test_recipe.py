"""Unit tests for the myhyundai_aircon recipe loader."""

import json
from pathlib import Path

import pytest

from custom_components.myhyundai_aircon.recipe import (
    RecipeError,
    load_recipe,
)

COMPONENT_DIR = (
    Path(__file__).parent.parent / "custom_components" / "myhyundai_aircon"
)

MINIMAL_RECIPE = {
    "version": 1,
    "baseline_screen": "840x2289",
    "package": "com.hyundai.oneapp.kr",
    "sequences": {
        "demo": {
            "description": "test",
            "steps": [
                {"action": "wake"},
                {"action": "tap_node", "match": {"text": "켜기"}},
            ],
        }
    },
}


def _write_recipe(tmp_path: Path, data: dict) -> Path:
    """Serialize a recipe dict to a file for load_recipe."""
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_default_recipe_flags_placeholders() -> None:
    """The shipped default.json validates but is marked incomplete."""
    recipe = load_recipe(COMPONENT_DIR / "recipes" / "default.json")
    assert recipe.package == "com.hyundai.oneapp.kr"
    assert recipe.sequences["aircon_on"].has_placeholders
    assert not recipe.sequences["aircon_off"].steps
    assert recipe.login_markers


def test_minimal_recipe_loads_with_defaults(tmp_path: Path) -> None:
    """Optional fields get their documented defaults."""
    recipe = load_recipe(_write_recipe(tmp_path, MINIMAL_RECIPE))
    sequence = recipe.sequences["demo"]
    assert not sequence.has_placeholders
    tap = sequence.steps[1]
    assert tap.action == "tap_node"
    assert tap.params["timeout"] == 5
    assert tap.optional is False


def test_unknown_action_rejected(tmp_path: Path) -> None:
    """An action outside the spec §8.3 table fails validation."""
    bad = json.loads(json.dumps(MINIMAL_RECIPE))
    bad["sequences"]["demo"]["steps"][0] = {"action": "explode"}
    with pytest.raises(RecipeError):
        load_recipe(_write_recipe(tmp_path, bad))


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    """tap_node without a match object fails validation."""
    bad = json.loads(json.dumps(MINIMAL_RECIPE))
    bad["sequences"]["demo"]["steps"][1] = {"action": "tap_node"}
    with pytest.raises(RecipeError):
        load_recipe(_write_recipe(tmp_path, bad))


def test_empty_match_rejected(tmp_path: Path) -> None:
    """A match object needs at least one condition."""
    bad = json.loads(json.dumps(MINIMAL_RECIPE))
    bad["sequences"]["demo"]["steps"][1] = {
        "action": "tap_node",
        "match": {},
    }
    with pytest.raises(RecipeError):
        load_recipe(_write_recipe(tmp_path, bad))


def test_shell_hostile_package_rejected(tmp_path: Path) -> None:
    """Package names that could smuggle shell syntax are refused."""
    bad = json.loads(json.dumps(MINIMAL_RECIPE))
    bad["package"] = "com.evil; rm -rf /"
    with pytest.raises(RecipeError):
        load_recipe(_write_recipe(tmp_path, bad))


def test_missing_file_rejected(tmp_path: Path) -> None:
    """A nonexistent path raises RecipeError, not FileNotFoundError."""
    with pytest.raises(RecipeError):
        load_recipe(tmp_path / "nope.json")
