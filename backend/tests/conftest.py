"""Locate the reference files.

They contain real student names, roll numbers and Drive links, so they are gitignored.
Tests that need them skip themselves when they are absent (a fresh clone, or CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

AIML_XLSX = FIXTURES / "AIML.xlsx"
SIGNATURE_XLSX = FIXTURES / "Signature.xlsx"
REFERENCE_PDF = FIXTURES / "Abhisha Banerjee.pdf"


def _require(path: Path) -> bytes:
    if not path.exists():
        pytest.skip(f"reference file not available: {path.name}")
    return path.read_bytes()


@pytest.fixture(scope="session")
def aiml_bytes() -> bytes:
    return _require(AIML_XLSX)


@pytest.fixture(scope="session")
def signature_bytes() -> bytes:
    return _require(SIGNATURE_XLSX)
