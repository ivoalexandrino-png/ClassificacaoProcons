"""Unit tests for Etapa 2.1 consistency audit helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from classificacao_procons.contratos.models import ControleAssinaturasItem

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_controle_consistency_audit.py"
_spec = importlib.util.spec_from_file_location("build_controle_consistency_audit", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


class _FakeIndex:
    def __init__(self, doc_ids: set[str] | None = None) -> None:
        self.items_by_document_id = tuple(
            (doc_id, type("X", (), {"item_id": "1"})())
            for doc_id in (doc_ids or set())
        )


def _item(**kwargs) -> ControleAssinaturasItem:
    defaults = {
        "item_id": "100",
        "name": "Férias colaborador",
        "status": "Assinado",
        "tipo": None,
        "signature_link": None,
        "group_id": "g1",
    }
    defaults.update(kwargs)
    return ControleAssinaturasItem(**defaults)


def test_should_classify_title_pattern_only_when_only_hr_regex_matches() -> None:
    ev = _mod._archive_evidence(
        _item(name="Rescisão contrato", signature_link=""),
        _FakeIndex(),
        etapa2_reason="hr_non_contract_title",
    )
    assert ev["evidence_type"] == "title_pattern_only"
    assert ev["executable_archive"] is False
    assert ev["plan_classification_v2"] == "PROBABLE_ARCHIVE_REVIEW"


def test_should_not_allow_executable_archive_for_autentique_url_only() -> None:
    ev = _mod._archive_evidence(
        _item(
            name="Rescisão colaborador",
            signature_link="https://assina.ae/s/abc",
        ),
        _FakeIndex(),
        etapa2_reason="hr_non_contract_title",
    )
    assert ev["evidence_type"] == "autentique_url_confirmed"
    assert ev["executable_archive"] is False
    assert ev["plan_classification_v2"] == "PROBABLE_ARCHIVE_REVIEW"


def test_should_use_metadata_confirmed_when_tipo_indicates_rh() -> None:
    ev = _mod._archive_evidence(
        _item(name="Doc genérico", tipo="RH - Férias", signature_link=""),
        _FakeIndex(),
        etapa2_reason="hr_non_contract_title",
    )
    assert ev["evidence_type"] == "metadata_confirmed"
    assert ev["executable_archive"] is False


def test_should_detect_valid_multi_track_jan_luciano_pair() -> None:
    index = type(
        "Idx",
        (),
        {
            "all_items": [
                _item(
                    item_id="1",
                    name="Contrato X",
                    signature_link="Autentique ID: aaa\ncontrole_track: jan",
                ),
                _item(
                    item_id="2",
                    name="Contrato X",
                    signature_link="Autentique ID: aaa\ncontrole_track: luciano",
                ),
            ],
        },
    )()
    gtype, rows = _mod._classify_duplicate_group(
        "contrato x",
        (("1", "Contrato X"), ("2", "Contrato X")),
        index,
    )
    assert gtype == "VALID_MULTI_TRACK"
    assert len(rows) == 2
