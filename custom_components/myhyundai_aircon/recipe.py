"""Recipe loading and validation for the myhyundai_aircon integration.

A recipe is data, not code (spec §8.1): the JSON file describes the
tap sequences that drive the MyHyundai widget, so an app update means
editing the file and calling the reload_recipe service — never
touching Python. This module parses the file, validates it against
the spec §8 schema, and flags sequences that still carry placeholder
values so the executor can refuse to run them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import voluptuous as vol

from .const import PLACEHOLDER_MARKER

_PACKAGE_NAME = vol.Match(r"^[A-Za-z][A-Za-z0-9_.]*$")
_KEYEVENT_NAME = vol.Match(r"^[A-Z0-9_]+$")
_RATIO = vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0))
_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0))
_PIXELS = vol.All(vol.Coerce(int), vol.Range(min=0))

_MATCH_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("resource_id"): str,
            vol.Optional("text"): str,
            vol.Optional("text_contains"): str,
            vol.Optional("content_desc"): str,
            vol.Optional("class"): str,
            vol.Optional("package"): str,
            vol.Optional("index"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        }
    ),
    vol.Length(min=1),
)

# Per-action parameter schemas from the spec §8.3 table. The common
# "optional" flag is handled by _STEP_SCHEMA below.
_ACTION_SCHEMAS: dict[str, vol.Schema] = {
    "keyevent": vol.Schema({vol.Required("key"): _KEYEVENT_NAME}),
    "wake": vol.Schema({}),
    "home": vol.Schema({}),
    "launch_app": vol.Schema({vol.Required("package"): _PACKAGE_NAME}),
    "stop_app": vol.Schema({vol.Required("package"): _PACKAGE_NAME}),
    "wait_focus": vol.Schema(
        {
            vol.Required("pattern"): str,
            vol.Optional("timeout", default=10): _SECONDS,
        }
    ),
    "wait_node": vol.Schema(
        {
            vol.Required("match"): _MATCH_SCHEMA,
            vol.Optional("timeout", default=10): _SECONDS,
        }
    ),
    "tap_node": vol.Schema(
        {
            vol.Required("match"): _MATCH_SCHEMA,
            vol.Optional("timeout", default=5): _SECONDS,
        }
    ),
    "tap_ratio": vol.Schema(
        {vol.Required("x"): _RATIO, vol.Required("y"): _RATIO}
    ),
    "swipe": vol.Schema(
        {
            vol.Required("x1"): _PIXELS,
            vol.Required("y1"): _PIXELS,
            vol.Required("x2"): _PIXELS,
            vol.Required("y2"): _PIXELS,
            vol.Optional("duration", default=300): vol.All(
                vol.Coerce(int), vol.Range(min=1)
            ),
        }
    ),
    "sleep": vol.Schema({vol.Required("seconds"): _SECONDS}),
    "assert_screen": vol.Schema({}),
    "await_notification": vol.Schema(
        {
            vol.Required("success_contains"): [str],
            vol.Optional("failure_contains", default=[]): [str],
            vol.Optional("timeout", default=60): _SECONDS,
        }
    ),
}

_STEP_SCHEMA = vol.Schema(
    {
        vol.Required("action"): vol.In(_ACTION_SCHEMAS),
        vol.Optional("optional", default=False): bool,
    },
    extra=vol.ALLOW_EXTRA,
)

_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required("version"): 1,
        vol.Required("baseline_screen"): str,
        vol.Required("package"): _PACKAGE_NAME,
        vol.Optional("login_markers", default=[]): [str],
        vol.Required("sequences"): {
            str: vol.Schema(
                {
                    vol.Optional("description", default=""): str,
                    vol.Required("steps"): [dict],
                }
            )
        },
    }
)


class RecipeError(Exception):
    """The recipe file is missing, unreadable, or violates the schema."""


@dataclass(frozen=True)
class Step:
    """One validated executor instruction."""

    action: str
    params: dict[str, Any]
    optional: bool


@dataclass(frozen=True)
class Sequence:
    """A named list of steps, flagged if placeholders remain."""

    description: str
    steps: tuple[Step, ...]
    has_placeholders: bool


@dataclass(frozen=True)
class Recipe:
    """A fully validated recipe file."""

    baseline_screen: str
    package: str
    login_markers: tuple[str, ...] = ()
    sequences: dict[str, Sequence] = field(default_factory=dict)


def _contains_placeholder(value: Any) -> bool:
    """Recursively look for the placeholder marker in string values."""
    if isinstance(value, str):
        return PLACEHOLDER_MARKER in value
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def _build_step(raw_step: dict[str, Any], where: str) -> Step:
    """Validate one raw step dict against its action schema.

    Args:
        raw_step: The step object from the JSON file.
        where: Human-readable location for error messages.

    Raises:
        RecipeError: On an unknown action or bad parameters.
    """
    try:
        common = _STEP_SCHEMA(raw_step)
        params = {
            key: value
            for key, value in raw_step.items()
            if key not in ("action", "optional")
        }
        params = _ACTION_SCHEMAS[common["action"]](params)
    except vol.Invalid as err:
        raise RecipeError(f"invalid step in {where}: {err}") from err
    return Step(
        action=common["action"],
        params=params,
        optional=common["optional"],
    )


def load_recipe(path: Path) -> Recipe:
    """Load and validate a recipe JSON file.

    Blocking file I/O — call through an executor job from within
    Home Assistant.

    Args:
        path: Location of the recipe JSON file.

    Returns:
        The validated recipe with per-sequence placeholder flags.

    Raises:
        RecipeError: If the file is missing, not valid JSON, or
            violates the spec §8 schema.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise RecipeError(f"recipe file not found: {path}") from err
    except (OSError, json.JSONDecodeError) as err:
        raise RecipeError(f"cannot read recipe {path}: {err}") from err
    try:
        data = _RECIPE_SCHEMA(raw)
    except vol.Invalid as err:
        raise RecipeError(f"recipe {path.name} invalid: {err}") from err

    sequences: dict[str, Sequence] = {}
    for name, raw_sequence in data["sequences"].items():
        steps = tuple(
            _build_step(raw_step, f"sequence {name!r} step {index}")
            for index, raw_step in enumerate(raw_sequence["steps"])
        )
        sequences[name] = Sequence(
            description=raw_sequence["description"],
            steps=steps,
            has_placeholders=_contains_placeholder(raw_sequence),
        )
    return Recipe(
        baseline_screen=data["baseline_screen"],
        package=data["package"],
        login_markers=tuple(data["login_markers"]),
        sequences=sequences,
    )
