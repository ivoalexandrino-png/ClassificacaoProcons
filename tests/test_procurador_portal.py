"""Testes do portal procurador (storage state + reclamação por protocolo)."""

from __future__ import annotations

import json
from pathlib import Path

from classificacao_procons.portal.procurador import (
    resolve_storage_state_path,
    validate_storage_state_file,
)


def test_should_resolve_storage_state_from_configured_path(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "session.json"
    storage.write_text(json.dumps({"cookies": []}), encoding="utf-8")
    monkeypatch.setenv("PROCON_SP_STORAGE_STATE_PATH", str(storage))
    assert resolve_storage_state_path() == str(storage)


def test_should_materialize_storage_state_from_json_env(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "credentials" / "procon-sp-storage.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROCON_SP_STORAGE_STATE_PATH", raising=False)
    monkeypatch.setenv("PROCON_SP_STORAGE_STATE_JSON", json.dumps({"cookies": [{"name": "x"}]}))
    resolved = resolve_storage_state_path()
    assert resolved is not None
    assert Path(resolved).resolve() == target.resolve()
    assert target.is_file()
    assert validate_storage_state_file(resolved)


def test_should_return_none_when_storage_state_missing(monkeypatch) -> None:
    monkeypatch.delenv("PROCON_SP_STORAGE_STATE_PATH", raising=False)
    monkeypatch.delenv("PROCON_SP_STORAGE_STATE_JSON", raising=False)
    assert resolve_storage_state_path() is None
