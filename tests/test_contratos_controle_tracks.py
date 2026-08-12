"""Testes das duas filas Jan/Luciano no Controle Assinaturas."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_LINK_TRACK_JAN,
    CONTROLE_LINK_TRACK_LUCIANO,
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_ASSINADO,
    SIGNER_EMAIL_JAN,
    SIGNER_EMAIL_LUCIANO,
)
from classificacao_procons.contratos.controle_sync import (
    _resolve_controle_group_id,
    reconcile_controle_from_document,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    infer_controle_signer_track,
    pick_canonical_controle_item,
)


def _groups() -> dict[str, str]:
    return {
        "assinados": "g-assinados",
        "contratos pendentes de assinatura jan": "g-jan",
        "contratos pendentes de assinatura luciano": "g-luciano",
    }


class TestControleSignerTracks:
    def test_should_start_in_luciano_group_when_nobody_signed(self) -> None:
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

        group_id = _resolve_controle_group_id(document=document, groups=_groups())

        assert group_id == "g-luciano"

    def test_should_move_to_jan_group_when_only_luciano_signed(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-2",
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
                    signed_at="2026-07-16T10:00:00Z",
                ),
            ),
        )

        group_id = _resolve_controle_group_id(document=document, groups=_groups())

        assert group_id == "g-jan"

    def test_should_pick_jan_track_as_canonical_for_contratos(self) -> None:
        jan_item = ControleAssinaturasItem(
            item_id="1",
            name="Contrato",
            status=None,
            tipo="Contratos B2B",
            signature_link=f"Autentique ID: abc\n{CONTROLE_LINK_TRACK_JAN}",
        )
        luciano_item = ControleAssinaturasItem(
            item_id="2",
            name="Contrato",
            status=None,
            tipo=None,
            signature_link=f"Autentique ID: abc\n{CONTROLE_LINK_TRACK_LUCIANO}",
        )

        canonical = pick_canonical_controle_item((luciano_item, jan_item))

        assert canonical.item_id == "1"
        assert infer_controle_signer_track(jan_item) == "jan"
        assert infer_controle_signer_track(luciano_item) == "luciano"

    @patch("classificacao_procons.contratos.controle_sync.update_controle_item_progress")
    def test_should_update_both_tracks_on_partial_signature(self, update_mock) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-3",
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
                    signed_at="2026-07-16T10:00:00Z",
                ),
            ),
        )
        items = (
            ControleAssinaturasItem(
                item_id="jan-1",
                name="Contrato",
                status="Aguardando outros",
                tipo="Contratos B2B",
                signature_link=f"id\n{CONTROLE_LINK_TRACK_JAN}",
                group_id="g-jan",
            ),
            ControleAssinaturasItem(
                item_id="luc-1",
                name="Contrato",
                status="Aguardando Assinatura",
                tipo=None,
                signature_link=f"id\n{CONTROLE_LINK_TRACK_LUCIANO}",
                group_id="g-luciano",
            ),
        )

        result = reconcile_controle_from_document(
            document=document,
            controle_items=items,
            api_token="token",
            groups=_groups(),
        )

        assert result.updated is True
        assert update_mock.call_count == 2
        by_item = {call.kwargs["item_id"]: call.kwargs for call in update_mock.call_args_list}
        assert by_item["jan-1"]["status_label"] == CONTROLE_STATUS_AGUARDANDO_ASSINATURA
        assert by_item["jan-1"]["signed_at"] is None
        assert by_item["luc-1"]["status_label"] == CONTROLE_STATUS_ASSINADO
