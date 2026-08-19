"""Tests for release metadata validation."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/verify_release_metadata.py"
SPEC = importlib.util.spec_from_file_location("verify_release_metadata", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - importlib invariant
    raise RuntimeError("could not load release metadata verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_release_metadata_is_synchronized() -> None:
    assert MODULE.verify_release_metadata() == "0.9.1"


def test_release_tag_must_match_metadata() -> None:
    with pytest.raises(ValueError, match="does not match"):
        MODULE.verify_release_metadata("v9.9.9")


def test_release_metadata_uses_tomli_when_tomllib_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "tomllib", None)
    fallback_spec = importlib.util.spec_from_file_location(
        "verify_release_metadata_fallback", SCRIPT_PATH
    )
    assert fallback_spec is not None
    assert fallback_spec.loader is not None
    fallback_module = importlib.util.module_from_spec(fallback_spec)
    fallback_spec.loader.exec_module(fallback_module)

    assert fallback_module.verify_release_metadata() == (
        MODULE.verify_release_metadata()
    )
