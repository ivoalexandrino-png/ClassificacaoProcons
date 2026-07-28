"""Testes de cadastro de PA standalone e heurística CIP↔PA."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.email.parser import (
    protocol_from_pa_admin_segment,
)
from classificacao_procons.interaction_pipeline import (
    ConsumerInteractionPipelineOptions,
    process_consumer_interactions,
)
from classificacao_procons.models import ProconNotificationEmail
from classificacao_procons.monday.client import MondayClientError
from classificacao_procons.monday.item_lookup import (
    find_related_cip_by_pa_conversion_heuristic,
)
from classificacao_procons.pa_standalone_registry import (
    ensure_pa_monday_item_for_protocol,
)


class TestProtocolFromPaAdminSegment:
    def test_should_build_protocol_from_admin_number(self) -> None:
        assert (
            protocol_from_pa_admin_segment(
                admin_number="35.001.003.26.1681159",
                year=2026,
            )
            == "1681159/2026"
        )

    def test_should_raise_when_segment_not_numeric(self) -> None:
        with pytest.raises(ValueError, match="inválido"):
            protocol_from_pa_admin_segment(admin_number="35.001.003.26.ABC", year=2026)


class TestPaConversionHeuristic:
  @patch("classificacao_procons.monday.item_lookup._graphql_request")
  @patch("classificacao_procons.monday.item_lookup.load_board_metadata")
  def test_should_match_single_cip_when_pa_opened_after_complaint(
      self,
      metadata_mock: MagicMock,
      graphql_mock: MagicMock,
  ) -> None:
      from classificacao_procons.monday.mapping import (
          FIELD_COMPLAINT_DATE,
          FIELD_CPF,
          FIELD_PA_GENERATED,
          FIELD_PROTOCOL,
          MondayColumn,
      )

      metadata_mock.return_value = MagicMock(
          board_id="board-1",
          columns=[
              MondayColumn(id="proto", title="Protocolo", column_type="text"),
              MondayColumn(id="cpf", title="CPF", column_type="text"),
              MondayColumn(id="pa", title="Gerou PA", column_type="status"),
              MondayColumn(id="dt", title="Data da Reclamação", column_type="date"),
          ],
      )

      def fake_find_column(columns, field):
          mapping = {
              FIELD_PROTOCOL: MondayColumn(id="proto", title="Protocolo", column_type="text"),
              FIELD_CPF: MondayColumn(id="cpf", title="CPF", column_type="text"),
              FIELD_PA_GENERATED: MondayColumn(id="pa", title="Gerou PA", column_type="status"),
              FIELD_COMPLAINT_DATE: MondayColumn(
                  id="dt",
                  title="Data da Reclamação",
                  column_type="date",
              ),
          }
          return mapping.get(field)

      with patch(
          "classificacao_procons.monday.item_lookup.find_column_by_field",
          side_effect=fake_find_column,
      ), patch(
          "classificacao_procons.monday.item_lookup.find_protocol_column",
          return_value=MondayColumn(id="proto", title="Protocolo", column_type="text"),
      ):
          graphql_mock.return_value = {
              "boards": [
                  {
                      "items_page": {
                          "items": [
                              {
                                  "id": "12455122069",
                                  "column_values": [
                                      {"id": "proto", "text": "1624924/2026"},
                                      {"id": "cpf", "text": "44668552852"},
                                      {"id": "pa", "text": "Sim"},
                                      {"id": "dt", "text": "10/07/2026"},
                                  ],
                              },
                              {
                                  "id": "other",
                                  "column_values": [
                                      {"id": "proto", "text": "1653213/2026"},
                                      {"id": "cpf", "text": "45826236892"},
                                      {"id": "pa", "text": "Sim"},
                                      {"id": "dt", "text": "2026-07-24"},
                                  ],
                              },
                          ],
                      },
                  },
              ],
          }
          match = find_related_cip_by_pa_conversion_heuristic(
              api_token="token",
              pa_protocol="1681159/2026",
              pa_opened_on=date(2026, 7, 22),
          )
      assert match == ("12455122069", "1624924/2026")


@patch("classificacao_procons.interaction_pipeline.GmailProconFetcher.from_credentials")
@patch("classificacao_procons.interaction_pipeline._post_monday_interaction")
@patch("classificacao_procons.pa_standalone_registry.ensure_pa_monday_item_for_protocol")
def test_process_interactions_should_register_pa_then_post_update(
    ensure_pa_mock: MagicMock,
    post_monday_mock: MagicMock,
    fetcher_factory_mock: MagicMock,
    tmp_path,
) -> None:
    from datetime import UTC, datetime

    post_monday_mock.side_effect = [
        MondayClientError("Item Monday não encontrado para o protocolo 1681159/2026."),
        "pa-item-99",
    ]
    ensure_pa_mock.return_value = MagicMock(item_id="pa-item-99", skipped_duplicate=False)

    fetcher = MagicMock()
    fetcher.list_unread_consumer_interactions.return_value = [
        ProconNotificationEmail(
            message_id="msg-pa",
            subject="Interação do Consumidor",
            sender="procon.naoresponder15@procon.sp.gov.br",
            received_at=datetime(2026, 7, 22, tzinfo=UTC),
            portal_url="",
            source_id="sp",
            protocol_number="1681159/2026",
            notification_type="interacao_consumidor",
        ),
    ]
    fetcher.fetch_message_payload.return_value = {"parts": []}
    fetcher_factory_mock.return_value = fetcher

    options = ConsumerInteractionPipelineOptions(
        state_path=tmp_path / "state.json",
        fetch_portal=False,
        monday_api_token="token",
    )

    with patch(
        "classificacao_procons.interaction_pipeline.has_gmail_modify_access",
        return_value=False,
    ):
        results = process_consumer_interactions(options)

    assert results[0].status == "success"
    assert results[0].monday_item_id == "pa-item-99"
    ensure_pa_mock.assert_called_once()
    assert ensure_pa_mock.call_args.kwargs["pa_protocol"] == "1681159/2026"
    assert post_monday_mock.call_count == 2


@patch("classificacao_procons.pa_standalone_registry.register_standalone_pa_complaint")
@patch("classificacao_procons.pa_standalone_registry.load_monday_item_snapshot")
@patch("classificacao_procons.pa_standalone_registry.resolve_related_cip_item")
@patch("classificacao_procons.pa_standalone_registry.find_item_id_by_protocol")
def test_ensure_pa_should_reuse_drive_from_related_cip(
    find_protocol_mock: MagicMock,
    resolve_cip_mock: MagicMock,
    snapshot_mock: MagicMock,
    register_mock: MagicMock,
) -> None:
    from classificacao_procons.monday.item_lookup import MondayItemSnapshot
    from classificacao_procons.pa_standalone_registry import RelatedCipMatch

    find_protocol_mock.return_value = None
    resolve_cip_mock.return_value = RelatedCipMatch(
        item_id="12455122069",
        protocol_number="1624924/2026",
        consumer_name="SILVIA RAFAELA DE PAULA CAMARGO",
        consumer_cpf="44668552852",
        same_consumer_verified=True,
        verification_source="pa_conversion_heuristic",
    )
    snapshot_mock.return_value = MondayItemSnapshot(
        consumer_name="SILVIA RAFAELA DE PAULA CAMARGO",
        consumer_cpf="44668552852",
        protocol_number="1624924/2026",
        complaint_date=date(2026, 7, 10),
        cause="Assinatura",
        state="SP",
        pdf_url="https://drive/pdf",
        drive_folder_url="https://drive/folder/cip",
    )
    register_mock.return_value = MagicMock(item_id="new-pa-item", skipped_duplicate=False)

    with patch(
        "classificacao_procons.pa_standalone_registry.create_item_update",
    ) as update_mock:
        result = ensure_pa_monday_item_for_protocol(
            pa_protocol="1681159/2026",
            api_token="token",
            fetcher=None,
        )

    assert result.item_id == "new-pa-item"
    complaint = register_mock.call_args[0][0]
    assert complaint.protocol_number == "1681159/2026"
    assert complaint.drive_folder_url == "https://drive/folder/cip"
    assert update_mock.call_count == 2
