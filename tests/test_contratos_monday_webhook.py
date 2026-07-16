"""Testes do webhook Monday para Contratos."""

import json

from classificacao_procons.contratos.monday_webhook import (
    build_challenge_response,
    is_contratos_item_created_event,
    parse_monday_webhook,
)


class TestMondayWebhook:
    def test_should_parse_challenge_payload(self) -> None:
        raw = json.dumps({"challenge": "abc123"}).encode("utf-8")
        event = parse_monday_webhook(raw)

        assert event.event_type == "challenge"
        assert event.challenge == "abc123"
        assert build_challenge_response(event) == {"challenge": "abc123"}

    def test_should_parse_create_pulse_event(self) -> None:
        raw = json.dumps(
            {
                "event": {
                    "type": "create_pulse",
                    "boardId": 5385471914,
                    "pulseId": 999,
                    "pulseName": "Contrato B2B - Empresa",
                }
            }
        ).encode("utf-8")
        event = parse_monday_webhook(raw)

        assert event.item_id == "999"
        assert event.board_id == "5385471914"
        assert is_contratos_item_created_event(event) is True
