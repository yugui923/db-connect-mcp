"""Tests for release metadata validation."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/verify_release_metadata.py"
SPEC = importlib.util.spec_from_file_location("verify_release_metadata", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("could not load release metadata verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_release_metadata_is_synchronized() -> None:
    assert MODULE.verify_release_metadata() == "0.7.1"


def test_release_tag_must_match_metadata() -> None:
    with pytest.raises(ValueError, match="does not match"):
        MODULE.verify_release_metadata("v9.9.9")
