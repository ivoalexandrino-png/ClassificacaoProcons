"""Status Recusado / bloqueio no Autentique."""

from datetime import UTC, datetime, timedelta

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_BLOQUEADO,
    CONTROLE_STATUS_RECUSADO,
    SIGNER_EMAIL_JAN,
)
from classificacao_procons.contratos.controle_status import resolve_controle_status_for_track


class TestControleRefusedOrBlocked:
    def test_should_mark_recusado_when_signer_rejected(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-r",
            name="Contrato",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="1",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link=None,
                    signed_at=None,
                    rejected_at="2026-08-06T10:00:00Z",
                ),
            ),
        )
        assert resolve_controle_status_for_track(document, track="jan") == CONTROLE_STATUS_RECUSADO

    def test_should_prefer_recusado_over_bloqueado_when_both(self) -> None:
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        document = AutentiqueDocumentSummary(
            document_id="doc-both",
            name="Contrato",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="1",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link=None,
                    signed_at=None,
                    rejected_at="2026-08-06T10:00:00Z",
                ),
            ),
            deadline_at=past,
        )
        assert resolve_controle_status_for_track(document, track="jan") == CONTROLE_STATUS_RECUSADO

    def test_should_mark_bloqueado_when_deadline_passed(self) -> None:
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        document = AutentiqueDocumentSummary(
            document_id="doc-b",
            name="Contrato",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="1",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link=None,
                    signed_at=None,
                ),
            ),
            deadline_at=past,
        )
        assert document.is_signing_blocked is True
        assert resolve_controle_status_for_track(document, track="jan") == CONTROLE_STATUS_BLOQUEADO

    def test_should_keep_aguardando_when_still_open(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        document = AutentiqueDocumentSummary(
            document_id="doc-open",
            name="Contrato",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="1",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link=None,
                    signed_at=None,
                ),
            ),
            deadline_at=future,
        )
        assert resolve_controle_status_for_track(document, track="jan") == (
            CONTROLE_STATUS_AGUARDANDO_ASSINATURA
        )
