"""Webhook Monday.com para enriquecer itens criados no quadro Contratos."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from classificacao_procons.contratos.constants import MONDAY_CONTRATOS_BOARD_ID


class MondayWebhookError(RuntimeError):
    """Erro ao processar webhook do Monday."""


@dataclass(frozen=True)
class MondayWebhookEvent:
    event_type: str
    board_id: str | None
    item_id: str | None
    item_name: str | None
    challenge: str | None = None


def parse_monday_webhook(raw_body: bytes) -> MondayWebhookEvent:
    """Interpreta payload do webhook do Monday (challenge ou evento)."""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MondayWebhookError("Payload do webhook Monday inválido.") from exc

    if not isinstance(payload, dict):
        raise MondayWebhookError("Payload do webhook Monday deve ser objeto JSON.")

    challenge = payload.get("challenge")
    if isinstance(challenge, str) and challenge.strip():
        return MondayWebhookEvent(
            event_type="challenge",
            board_id=None,
            item_id=None,
            item_name=None,
            challenge=challenge.strip(),
        )

    event = payload.get("event")
    if not isinstance(event, dict):
        raise MondayWebhookError("Evento ausente no webhook Monday.")

    return MondayWebhookEvent(
        event_type=str(event.get("type") or event.get("eventType") or ""),
        board_id=_as_id(event.get("boardId")),
        item_id=_as_id(event.get("pulseId") or event.get("itemId")),
        item_name=_nullable_str(event.get("pulseName") or event.get("itemName")),
    )


def build_challenge_response(event: MondayWebhookEvent) -> dict[str, str]:
    """Resposta exigida pelo Monday na verificação do webhook."""
    if not event.challenge:
        raise MondayWebhookError("Challenge ausente.")
    return {"challenge": event.challenge}


def is_contratos_item_created_event(event: MondayWebhookEvent) -> bool:
    """Indica criação de item no quadro Contratos (automação Monday)."""
    if event.board_id != MONDAY_CONTRATOS_BOARD_ID:
        return False
    normalized = event.event_type.casefold().replace("_", "")
    return normalized in {"createpulse", "itemcreated", "createitem"}


def _as_id(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
