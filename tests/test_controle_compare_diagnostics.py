"""Diagnóstico read-only compare-controle (expected tracks, escopo, ações propostas)."""

from unittest.mock import patch

import pytest

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_LINK_TRACK_JAN,
    CONTROLE_LINK_TRACK_LUCIANO,
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_ASSINADO,
    SIGNER_DISPLAY_NAME_LUCIANO,
    SIGNER_EMAIL_JAN,
    SIGNER_EMAIL_LUCIANO,
)
from classificacao_procons.contratos.controle_compare_diagnostics import (
    ControleProposedAction,
    build_controle_compare_diagnostics,
    diagnose_controle_document,
    summarize_controle_compare_diagnostics,
)
from classificacao_procons.contratos.controle_scope import ControleScopeClassification
from classificacao_procons.contratos.controle_sync import sync_controle_from_autentique
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def _track_link(document_id: str, track: str) -> str:
    marker = CONTROLE_LINK_TRACK_JAN if track == "jan" else CONTROLE_LINK_TRACK_LUCIANO
    return f"Autentique ID: {document_id}\n{marker}"


def _index(
    document_id: str,
    *items: ControleAssinaturasItem,
    legacy_title: str | None = None,
) -> ControleAssinaturasIndex:
    doc_key = document_id.casefold().strip()
    pairs = tuple((doc_key, item) for item in items)
    exact = frozenset()
    if legacy_title:
        exact = frozenset({legacy_title.casefold()})
    return ControleAssinaturasIndex(
        document_ids=frozenset({doc_key}) if items else frozenset(),
        exact_names=exact,
        items_by_document_id=pairs,
        all_items=items,
    )


def _jan_signer(*, signed: bool = False) -> AutentiqueSigner:
    return AutentiqueSigner(
        public_id="jan-1",
        name="Jan Riehle",
        email=SIGNER_EMAIL_JAN,
        short_link="https://assina.ae/jan",
        signed_at="2026-07-20T10:00:00Z" if signed else None,
    )


def _luciano_signer(*, signed: bool = False) -> AutentiqueSigner:
    return AutentiqueSigner(
        public_id="luc-1",
        name=SIGNER_DISPLAY_NAME_LUCIANO,
        email=SIGNER_EMAIL_LUCIANO,
        short_link="https://assina.ae/luc",
        signed_at="2026-07-16T10:00:00Z" if signed else None,
    )


def _b2b_doc(
    *,
    document_id: str,
    name: str,
    signatures: tuple[AutentiqueSigner, ...],
    signed_pdf_url: str | None = None,
) -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id=document_id,
        name=name,
        created_at="2026-01-01",
        signed_pdf_url=signed_pdf_url,
        signatures=signatures,
    )


class TestControleCompareDiagnostics:
    def test_should_expect_jan_only_pending(self) -> None:
        document = _b2b_doc(
            document_id="d-jan",
            name="Contrato B2B - Fornecedor A",
            signatures=(_jan_signer(signed=False),),
        )
        row = diagnose_controle_document(document=document, index=_index("d-jan"))
        assert row.expected_tracks == frozenset({"jan"})
        assert row.missing_tracks == frozenset({"jan"})
        assert row.proposed_action == ControleProposedAction.MISSING_TRACK.value

    def test_should_expect_luciano_only_pending(self) -> None:
        document = _b2b_doc(
            document_id="d-luc",
            name="Contrato B2B - Fornecedor B",
            signatures=(_luciano_signer(signed=False),),
        )
        row = diagnose_controle_document(document=document, index=_index("d-luc"))
        assert row.expected_tracks == frozenset({"luciano"})

    def test_should_expect_both_tracks_when_both_signers_pending(self) -> None:
        document = _b2b_doc(
            document_id="d-both",
            name="Contrato B2B - Parceiro",
            signatures=(_jan_signer(), _luciano_signer()),
        )
        row = diagnose_controle_document(document=document, index=_index("d-both"))
        assert row.expected_tracks == frozenset({"jan", "luciano"})
        assert row.missing_tracks == frozenset({"jan", "luciano"})

    def test_should_mark_jan_assinado_and_luciano_aguardando(self) -> None:
        document = _b2b_doc(
            document_id="d-part",
            name="Contrato B2B - Mix",
            signatures=(_jan_signer(signed=True), _luciano_signer(signed=False)),
        )
        row = diagnose_controle_document(document=document, index=_index("d-part"))
        assert row.status_expected_by_track["jan"] == CONTROLE_STATUS_ASSINADO
        assert row.status_expected_by_track["luciano"] == CONTROLE_STATUS_AGUARDANDO_ASSINATURA

    def test_should_mark_luciano_assinado_and_jan_aguardando(self) -> None:
        document = _b2b_doc(
            document_id="d-part2",
            name="Contrato B2B - Mix 2",
            signatures=(_jan_signer(signed=False), _luciano_signer(signed=True)),
        )
        row = diagnose_controle_document(document=document, index=_index("d-part2"))
        assert row.status_expected_by_track["luciano"] == CONTROLE_STATUS_ASSINADO
        assert row.status_expected_by_track["jan"] == CONTROLE_STATUS_AGUARDANDO_ASSINATURA

    def test_should_mark_both_assinado_when_both_signed(self) -> None:
        document = _b2b_doc(
            document_id="d-done",
            name="Contrato B2B - Fechado",
            signatures=(_jan_signer(signed=True), _luciano_signer(signed=True)),
        )
        row = diagnose_controle_document(document=document, index=_index("d-done"))
        assert row.status_expected_by_track["jan"] == CONTROLE_STATUS_ASSINADO
        assert row.status_expected_by_track["luciano"] == CONTROLE_STATUS_ASSINADO

    def test_should_expect_no_tracks_without_internal_signers(self) -> None:
        document = _b2b_doc(
            document_id="d-ext",
            name="Contrato B2B - Só fornecedor",
            signatures=(
                AutentiqueSigner(
                    public_id="ext",
                    name="Fornecedor",
                    email="ext@vendor.com",
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )
        row = diagnose_controle_document(document=document, index=_index("d-ext"))
        assert row.expected_tracks == frozenset()
        assert row.scope_classification == ControleScopeClassification.INELIGIBLE.value

    def test_should_ignore_ferias_document(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="d-ferias",
            name="Solicitação de Férias - Maria",
            created_at=None,
            signed_pdf_url=None,
            signatures=(_jan_signer(),),
        )
        row = diagnose_controle_document(document=document, index=_index("d-ferias"))
        assert row.proposed_action == ControleProposedAction.IGNORED_NON_CONTRACT.value

    def test_should_ignore_rescisao_document(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="d-res",
            name="Termo de Rescisão - João",
            created_at=None,
            signed_pdf_url=None,
            signatures=(_luciano_signer(),),
        )
        row = diagnose_controle_document(document=document, index=_index("d-res"))
        assert row.scope_reason == "hr_non_contract_domain"

    def test_should_manual_review_for_declaracao(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="d-decl",
            name="Declaração de vínculo empregatício",
            created_at=None,
            signed_pdf_url=None,
            signatures=(_jan_signer(),),
        )
        row = diagnose_controle_document(document=document, index=_index("d-decl"))
        assert row.proposed_action == ControleProposedAction.IGNORED_NON_CONTRACT.value

    def test_should_manual_review_when_signer_unknown(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="d-unk",
            name="Contrato B2B - Mistério",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="u1",
                    name="Representante Legal",
                    email="outro@empresa.com",
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )
        row = diagnose_controle_document(document=document, index=_index("d-unk"))
        assert row.expected_tracks == frozenset()
        assert row.scope_classification == ControleScopeClassification.INELIGIBLE.value
        assert row.proposed_action == ControleProposedAction.IGNORED_NON_CONTRACT.value

    def test_should_eligible_supplemental_procuracao_jan_only(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="d-proc",
            name="Procuração B4A - Fornecedor X",
            created_at=None,
            signed_pdf_url=None,
            signatures=(_jan_signer(),),
        )
        row = diagnose_controle_document(document=document, index=_index("d-proc"))
        assert row.scope_classification == ControleScopeClassification.ELIGIBLE.value
        assert row.scope_reason == "supplemental_document"
        assert row.expected_tracks == frozenset({"jan"})

    def test_should_detect_existing_tracks_by_autentique_id(self) -> None:
        document = _b2b_doc(
            document_id="d-linked",
            name="Contrato B2B - Já no Monday",
            signatures=(_jan_signer(), _luciano_signer()),
        )
        jan_item = ControleAssinaturasItem(
            item_id="jan-99",
            name=document.name,
            status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo="B2B",
            signature_link=_track_link("d-linked", "jan"),
            group_id="group-jan",
        )
        luc_item = ControleAssinaturasItem(
            item_id="luc-99",
            name=document.name,
            status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo=None,
            signature_link=_track_link("d-linked", "luciano"),
            group_id="group-luciano",
        )
        row = diagnose_controle_document(
            document=document,
            index=_index("d-linked", jan_item, luc_item),
        )
        assert row.existing_tracks == frozenset({"jan", "luciano"})
        assert row.missing_tracks == frozenset()
        assert row.proposed_action == ControleProposedAction.NONE.value

    def test_should_surface_legacy_without_autentique_id(self) -> None:
        title = "Contrato B2B - Legado"
        document = _b2b_doc(
            document_id="d-new-id",
            name=title,
            signatures=(_jan_signer(),),
        )
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name=title,
            status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo="B2B",
            signature_link="https://assina.ae/old",
        )
        row = diagnose_controle_document(
            document=document,
            index=ControleAssinaturasIndex(
                document_ids=frozenset(),
                exact_names=frozenset({title.casefold()}),
                all_items=(legacy,),
            ),
        )
        assert row.legacy_items_without_autentique_id == (("legacy-1", title),)

    def test_should_be_stable_on_consecutive_diagnosis(self) -> None:
        document = _b2b_doc(
            document_id="d-stable",
            name="Contrato B2B - Estável",
            signatures=(_jan_signer(),),
        )
        index = _index("d-stable")
        first = diagnose_controle_document(document=document, index=index)
        second = diagnose_controle_document(document=document, index=index)
        assert first == second

    def test_should_flag_unexpected_track_on_monday(self) -> None:
        document = _b2b_doc(
            document_id="d-luc-only",
            name="Contrato B2B - Só Luciano",
            signatures=(_luciano_signer(),),
        )
        jan_stray = ControleAssinaturasItem(
            item_id="stray-jan",
            name=document.name,
            status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo="B2B",
            signature_link=_track_link("d-luc-only", "jan"),
            group_id="group-jan",
        )
        luc_item = ControleAssinaturasItem(
            item_id="luc-1",
            name=document.name,
            status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo=None,
            signature_link=_track_link("d-luc-only", "luciano"),
            group_id="group-luciano",
        )
        row = diagnose_controle_document(
            document=document,
            index=_index("d-luc-only", jan_stray, luc_item),
        )
        assert row.unexpected_tracks == frozenset({"jan"})
        assert row.proposed_action == ControleProposedAction.UNEXPECTED_TRACK.value

    def test_should_summarize_track_counts(self) -> None:
        documents = (
            _b2b_doc(document_id="a", name="Contrato B2B - A", signatures=(_jan_signer(),)),
            _b2b_doc(document_id="b", name="Contrato B2B - B", signatures=(_luciano_signer(),)),
            _b2b_doc(
                document_id="c",
                name="Contrato B2B - C",
                signatures=(_jan_signer(), _luciano_signer()),
            ),
        )
        rows = build_controle_compare_diagnostics(
            documents=documents,
            index=ControleAssinaturasIndex(
                document_ids=frozenset(),
                exact_names=frozenset(),
            ),
        )
        summary = summarize_controle_compare_diagnostics(rows)
        assert summary.expected_tracks_jan_only == 1
        assert summary.expected_tracks_luciano_only == 1
        assert summary.expected_tracks_both == 1


class TestMondayCreateIdempotencyOnRetry:
    @patch("classificacao_procons.monday.client.urllib.request.urlopen")
    def test_should_send_idempotency_key_header(
        self,
        urlopen_mock: object,
    ) -> None:
        import json
        import urllib.request

        from classificacao_procons.monday.client import _graphql_request

        class _Resp:
            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"data": {"create_item": {"id": "1"}}}).encode()

        urlopen_mock.return_value = _Resp()
        captured_headers: list[dict[str, str]] = {}
        original_request = urllib.request.Request

        def _wrap_request(*args, **kwargs):  # type: ignore[no-untyped-def]
            req = original_request(*args, **kwargs)
            captured_headers.update(dict(req.header_items()))
            return req

        with patch("urllib.request.Request", side_effect=_wrap_request):
            data = _graphql_request(
                api_token="token",
                query="mutation { create_item { id } }",
                idempotency_key="controle:doc-1:jan",
            )

        assert data["create_item"]["id"] == "1"
        assert captured_headers.get("Idempotency-key") == "controle:doc-1:jan"


class TestSyncPausedNeverCallsCreate:
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_never_create_item_when_pause_default(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        create_item_mock,
        auto_link_mock,
        find_items_mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from classificacao_procons.contratos.controle_link_suggestions import LegacyAutoLinkResult

        def _empty_legacy_link() -> LegacyAutoLinkResult:
            return LegacyAutoLinkResult(
                applied=0,
                would_apply=0,
                ambiguous_skipped=0,
                failed=0,
                dry_run=False,
                items=(),
            )

        monkeypatch.delenv("CONTROLE_PAUSE_CREATE", raising=False)
        find_items_mock.return_value = ()
        auto_link_mock.return_value = _empty_legacy_link()
        document = _b2b_doc(
            document_id="doc-pause",
            name="Contrato B2B - Pausado",
            signatures=(_jan_signer(), _luciano_signer()),
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
        )

        create_item_mock.assert_not_called()
