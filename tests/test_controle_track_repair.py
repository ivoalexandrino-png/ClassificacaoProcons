"""Testes de reparo das filas Jan/Luciano no Controle."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_track_repair import (
    classify_controle_item_track,
    ensure_controle_dual_tracks_for_document,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem


class TestClassifyControleItemTrack:
    def test_should_classify_item_with_tipo_as_jan_even_in_luciano_group(self) -> None:
        item = ControleAssinaturasItem(
            item_id="1",
            name="4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="Autentique ID: abc",
            group_id="g-luciano",
        )

        track = classify_controle_item_track(
            item,
            jan_group_id="g-jan",
            luciano_group_id="g-luciano",
        )

        assert track == "jan"

    def test_should_classify_item_without_tipo_in_luciano_group_as_luciano(self) -> None:
        item = ControleAssinaturasItem(
            item_id="2",
            name="4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="Autentique ID: abc",
            group_id="g-luciano",
        )

        track = classify_controle_item_track(
            item,
            jan_group_id="g-jan",
            luciano_group_id="g-luciano",
        )

        assert track == "luciano"


class TestEnsureControleDualTracks:
    @patch("classificacao_procons.contratos.controle_track_repair.update_controle_item_fields")
    @patch("classificacao_procons.contratos.controle_track_repair.archive_controle_item")
    @patch("classificacao_procons.contratos.controle_track_repair.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_track_repair.find_controle_items_by_autentique_id")
    def test_should_archive_duplicate_in_same_track(
        self,
        mock_find: object,
        _mock_create: object,
        mock_archive: object,
        _mock_update: object,
    ) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-ge",
            name="GE Beauty",
            created_at="2026-07-31T12:00:00+00:00",
            signed_pdf_url=None,
            signatures=(),
        )
        duplicate = ControleAssinaturasItem(
            item_id="dup",
            name="GE Beauty",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="Autentique ID: doc-ge",
            group_id="g-luciano",
        )
        canonical = ControleAssinaturasItem(
            item_id="keep",
            name="GE Beauty",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="Autentique ID: doc-ge",
            group_id="g-luciano",
        )
        mock_find.return_value = (canonical, duplicate)

        result = ensure_controle_dual_tracks_for_document(
            api_token="token",
            document=document,
            jan_group_id="g-jan",
            luciano_group_id="g-luciano",
            tipo_label="Contratos B2B",
            status_label="Aguardando Assinatura",
            signed_at=None,
            build_track_link=lambda **_: "link",
        )

        mock_archive.assert_called_once_with(api_token="token", item_id="dup")
        assert result.archived_duplicates == 1
        assert result.duplicate_tracks_remaining == 0

    @patch("classificacao_procons.contratos.controle_track_repair.update_controle_item_fields")
    @patch("classificacao_procons.contratos.controle_track_repair.archive_controle_item")
    @patch("classificacao_procons.contratos.controle_track_repair.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_track_repair.find_controle_items_by_autentique_id")
    def test_should_archive_jan_item_when_jan_not_signer_on_document(
        self,
        mock_find: object,
        mock_create: object,
        mock_archive: object,
        _mock_update: object,
    ) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-bruno",
            name="Distrato Bruno",
            created_at="2026-07-31T12:00:00+00:00",
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="b4a",
                    name="Beauty For All",
                    email=None,
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )
        stray_jan = ControleAssinaturasItem(
            item_id="jan-wrong",
            name="Distrato Bruno",
            status="Aguardando Assinatura",
            tipo="RH",
            signature_link="Autentique ID: doc-bruno",
            group_id="g-jan",
        )
        mock_find.return_value = (stray_jan,)

        result = ensure_controle_dual_tracks_for_document(
            api_token="token",
            document=document,
            jan_group_id="g-jan",
            luciano_group_id="g-luciano",
            tipo_label="RH",
            status_label="Aguardando Assinatura",
            signed_at=None,
            build_track_link=lambda **_: "link",
        )

        mock_archive.assert_called_once_with(api_token="token", item_id="jan-wrong")
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["group_id"] == "g-luciano"
        assert result.archived_duplicates == 1
        assert result.created_jan is False
        assert result.created_luciano is True
