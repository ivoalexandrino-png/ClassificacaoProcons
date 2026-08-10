"""Tracks Jan/Luciano conforme signatários no Autentique."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import SIGNER_EMAIL_JAN, SIGNER_EMAIL_LUCIANO
from classificacao_procons.contratos.controle_required_tracks import (
    document_required_controle_tracks,
)
from classificacao_procons.contratos.controle_sync import _create_controle_track_pair
from classificacao_procons.contratos.controle_track_repair import (
    controle_dual_tracks_satisfied_for_items,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem


class TestDocumentRequiredControleTracks:
    def test_should_require_both_tracks_when_jan_and_luciano_sign(self) -> None:
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
                ),
                AutentiqueSigner(
                    public_id="2",
                    name="Luciano",
                    email=SIGNER_EMAIL_LUCIANO,
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )

        assert document_required_controle_tracks(document) == frozenset({"jan", "luciano"})

    def test_should_require_only_luciano_for_bruno_distrato_like_doc(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-bruno",
            name="Distrato Bruno Santos de Castro - 25.06.2026 (2)",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="b4a",
                    name="Beauty For All",
                    email=None,
                    short_link=None,
                    signed_at="2026-08-06T14:38:00Z",
                ),
                AutentiqueSigner(
                    public_id="bruno",
                    name="Bruno Santos De Castro",
                    email=None,
                    short_link=None,
                    signed_at="2026-08-06T14:38:00Z",
                ),
                AutentiqueSigner(
                    public_id="isa",
                    name="Isadora Feitosa Maso",
                    email=None,
                    short_link=None,
                    signed_at="2026-08-06T14:38:00Z",
                ),
            ),
        )

        assert document_required_controle_tracks(document) == frozenset({"luciano"})

    def test_should_require_only_jan_when_only_jan_signs(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-jan",
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
        )
        assert document_required_controle_tracks(document) == frozenset({"jan"})

    def test_should_return_empty_tracks_when_no_internal_signer(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-none",
            name="Contrato",
            created_at=None,
            signed_pdf_url=None,
            signatures=(),
        )
        assert document_required_controle_tracks(document) == frozenset()

class TestControleDualTracksSatisfied:
    def test_should_be_satisfied_when_both_tracks_present(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-1",
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
                AutentiqueSigner(
                    public_id="2",
                    name="Luciano",
                    email=SIGNER_EMAIL_LUCIANO,
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )
        items = (
            ControleAssinaturasItem(
                item_id="j",
                name="Contrato",
                status=None,
                tipo="B2B",
                signature_link="controle_track: jan",
            ),
            ControleAssinaturasItem(
                item_id="l",
                name="Contrato",
                status=None,
                tipo=None,
                signature_link="controle_track: luciano",
            ),
        )

        assert controle_dual_tracks_satisfied_for_items(document, items) is True


class TestCreateControleTrackPairRequiredTracks:
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    def test_should_create_only_luciano_track_when_jan_not_on_document(
        self,
        create_mock: object,
    ) -> None:
        create_mock.return_value = ("luc-1", "https://monday/luc-1")
        document = AutentiqueDocumentSummary(
            document_id="doc-bruno",
            name="Distrato Bruno Santos de Castro - 25.06.2026 (2)",
            created_at="2026-06-30",
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="b4a",
                    name="Beauty For All",
                    email=None,
                    short_link="https://assina.ae/b4a",
                    signed_at=None,
                ),
                AutentiqueSigner(
                    public_id="bruno",
                    name="Bruno Santos De Castro",
                    email=None,
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )
        groups = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        primary_id, _url, mirror_id = _create_controle_track_pair(
            api_token="token",
            autentique_api_token=None,
            document=document,
            groups=groups,
            tipo_label="RH",
        )

        assert primary_id == "luc-1"
        assert mirror_id is None
        create_mock.assert_called_once()
        assert create_mock.call_args.kwargs["group_id"] == "g-luciano"
