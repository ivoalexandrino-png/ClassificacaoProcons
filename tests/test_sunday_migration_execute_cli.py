"""Tests for sunday_migration_execute CLI helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from classificacao_procons.migration.executor import ExecutorAbort

_spec = importlib.util.spec_from_file_location(
    "sunday_migration_execute",
    Path(__file__).resolve().parents[1] / "scripts" / "sunday_migration_execute.py",
)
_sme = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_sme)
_parse_requested_item_ids = _sme._parse_requested_item_ids


def test_parse_item_ids_rejects_duplicate_csv_values():
    with pytest.raises(ExecutorAbort, match="duplicados"):
        _parse_requested_item_ids(None, "1,2,1")


def test_parse_item_ids_normalizes_unique_csv_values():
    parsed = _parse_requested_item_ids(None, "2,3")
    assert parsed == frozenset({"2", "3"})
