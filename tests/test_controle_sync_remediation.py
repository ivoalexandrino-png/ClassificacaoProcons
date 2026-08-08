"""Testes de proteção contra criação duplicada e remediação."""

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
)
from classificacao_procons.contratos.controle_legacy_guard import (
    find_legacy_signed_name_matches,
    should_block_create_for_signed_autentique,
)
from classificacao_procons.contratos.controle_sync_remediation import (
    find_erroneous_sync_duplicate_items,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def _signed_doc() -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id="a" * 48,
        name="Declaração de Férias Antecipadas - Tobias Lima Fonseca",
        created_at="2026-07-01",
        signed_pdf_url="https://example.com/s.pdf",
        signatures=(),
    )


class TestControleLegacyGuard:
    def test_should_block_create_when_legacy_assinado_exists(self) -> None:
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name="Declaração de Férias Antecipadas - Tobias Lima Fonseca",
            status=CONTROLE_STATUS_ASSINADO,
            tipo=None,
            signature_link=None,
        )
        assert should_block_create_for_signed_autentique(
            document_name=_signed_doc().name,
            is_fully_signed=True,
            items=(legacy,),
        )

    def test_should_find_legacy_signed_match(self) -> None:
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name="Declaração de Férias Antecipadas - Tobias Lima Fonseca",
            status=CONTROLE_STATUS_ASSINADO,
            tipo=None,
            signature_link=None,
        )
        matches = find_legacy_signed_name_matches(
            document_name=_signed_doc().name,
            items=(legacy,),
        )
        assert matches == (legacy,)


class TestErroneousSyncRemediation:
    def test_should_flag_pending_duplicate_when_legacy_assinado_exists(self) -> None:
        doc = _signed_doc()
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name=doc.name,
            status=CONTROLE_STATUS_ASSINADO,
            tipo=None,
            signature_link=None,
        )
        duplicate = ControleAssinaturasItem(
            item_id="dup-1",
            name=doc.name,
            status=CONTROLE_STATUS_AGUARDANDO_OUTROS,
            tipo=None,
            signature_link=f"Autentique ID: {doc.document_id}\ncontrole_track: luciano",
            group_id="group-luciano",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({doc.document_id}),
            exact_names=frozenset(),
            all_items=(legacy, duplicate),
            pending_track_items=(duplicate,),
        )
        documents_by_id = {doc.document_id.casefold(): doc}

        rows = find_erroneous_sync_duplicate_items(
            index=index,
            documents_by_id=documents_by_id,
        )

        assert len(rows) == 1
        assert rows[0].item_id == "dup-1"
        assert rows[0].legacy_assinado_item_id == "legacy-1"
