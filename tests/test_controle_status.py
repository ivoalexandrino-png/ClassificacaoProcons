"""Testes de status Controle por fila Jan/Luciano."""

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
    SIGNER_DISPLAY_NAME_LUCIANO,
    SIGNER_EMAIL_JAN,
)
from classificacao_procons.contratos.controle_status import (
    resolve_controle_status_for_track,
    resolve_signed_at_for_track,
)


def _doc(*, luciano_signed: bool, jan_signed: bool = False) -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id="doc-1",
        name="Contrato",
        created_at=None,
        signed_pdf_url=None,
        signatures=(
            AutentiqueSigner(
                public_id="1",
                name="Jan Riehle",
                email=SIGNER_EMAIL_JAN,
                short_link=None,
                signed_at="2026-07-20T10:00:00Z" if jan_signed else None,
            ),
            AutentiqueSigner(
                public_id="2",
                name=SIGNER_DISPLAY_NAME_LUCIANO,
                email=None,
                short_link=None,
                signed_at="2026-07-16T10:00:00Z" if luciano_signed else None,
            ),
            AutentiqueSigner(
                public_id="3",
                name="Fornecedor",
                email="ext@example.com",
                short_link=None,
                signed_at="2026-07-15T10:00:00Z",
            ),
        ),
    )


class TestControleStatusPerTrack:
    def test_should_show_aguardando_assinatura_for_jan_when_only_luciano_and_externals_signed(
        self,
    ) -> None:
        document = _doc(luciano_signed=True, jan_signed=False)

        assert resolve_controle_status_for_track(document, track="jan") == (
            CONTROLE_STATUS_AGUARDANDO_ASSINATURA
        )
        assert resolve_signed_at_for_track(document, track="jan") is None
        assert resolve_controle_status_for_track(document, track="luciano") == (
            CONTROLE_STATUS_AGUARDANDO_OUTROS
        )
        assert resolve_signed_at_for_track(document, track="luciano") is not None

    def test_should_mark_assinado_when_all_signatures_complete(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-2",
            name="Ok",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="1",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link=None,
                    signed_at="2026-07-20T10:00:00Z",
                ),
                AutentiqueSigner(
                    public_id="2",
                    name="Luciano",
                    email=None,
                    short_link=None,
                    signed_at="2026-07-19T10:00:00Z",
                ),
            ),
        )

        assert resolve_controle_status_for_track(document, track="jan") == CONTROLE_STATUS_ASSINADO
        assert resolve_controle_status_for_track(document, track="luciano") == (
            CONTROLE_STATUS_ASSINADO
        )
