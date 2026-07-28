"""Leitura da aba Interações & Respostas no portal Procon-SP."""

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright

from classificacao_procons.models import ComplaintKind
from classificacao_procons.portal.client import (
    PortalFetchOptions,
    ProconPortalError,
    _open_complaint_with_code,
)

_INTERACTIONS_TAB_NAMES = (
    "Interações & Respostas",
    "Interacoes & Respostas",
    "Interações e Respostas",
)

_IGNORED_AUTHORS = frozenset(
    {
        "procon",
        "fundação procon",
        "fundacao procon",
        "procon-sp",
        "empresa",
        "fornecedor",
        "b4a",
        "beauty for all",
        "mmkt",
    },
)

_CONSUMER_AUTHOR_MARKERS = frozenset({"consumidor", "consumidora", "reclamante"})


@dataclass(frozen=True)
class ConsumerInteractionMessage:
    author_label: str
    body: str


@dataclass(frozen=True)
class PortalConsumerInteractions:
    protocol_number: str
    messages: tuple[ConsumerInteractionMessage, ...]
    attachment_labels: tuple[str, ...]


def _normalize_author(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def _is_consumer_author(author_label: str) -> bool:
    normalized = _normalize_author(author_label)
    if not normalized:
        return False
    if any(marker in normalized for marker in _CONSUMER_AUTHOR_MARKERS):
        return True
    if any(ignored in normalized for ignored in _IGNORED_AUTHORS):
        return False
    return False


def parse_consumer_interactions_from_tab_text(
    text: str,
    *,
    protocol_number: str | None = None,
) -> PortalConsumerInteractions:
    """
    Extrai blocos do consumidor a partir do texto da aba de interações.

    Formato esperado (variações): rótulo de autor em linha isolada seguido do texto.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    messages: list[ConsumerInteractionMessage] = []
    attachment_labels: list[str] = []

    author_pattern = re.compile(
        r"^(consumidor(?:a)?|reclamante|empresa|fornecedor|procon.*)$",
        re.IGNORECASE,
    )

    current_author: str | None = None
    current_body: list[str] = []

    def flush_message() -> None:
        nonlocal current_author, current_body
        if current_author is None:
            current_body = []
            return
        body = "\n".join(current_body).strip()
        if body and _is_consumer_author(current_author):
            messages.append(
                ConsumerInteractionMessage(author_label=current_author, body=body),
            )
        current_author = None
        current_body = []

    for line in lines:
        lower = line.lower()
        if lower.startswith("anexo") or lower.endswith((".png", ".jpg", ".jpeg", ".pdf")):
            if re.search(r"\.(png|jpe?g|pdf)$", lower) or "anexo" in lower:
                attachment_labels.append(line)
            continue

        if author_pattern.match(line):
            flush_message()
            current_author = line
            continue

        if current_author is not None:
            current_body.append(line)

    flush_message()

    resolved_protocol = protocol_number or ""
    if not resolved_protocol:
        for line in lines:
            match = re.search(r"protocolo\s*(\d+/\d+)", line, re.IGNORECASE)
            if match:
                resolved_protocol = match.group(1)
                break

    return PortalConsumerInteractions(
        protocol_number=resolved_protocol,
        messages=tuple(messages),
        attachment_labels=tuple(attachment_labels),
    )


def _open_interactions_tab(page: Page) -> None:
    for tab_name in _INTERACTIONS_TAB_NAMES:
        tab = page.get_by_role("tab", name=tab_name)
        if tab.count():
            tab.first.click()
            page.wait_for_timeout(2000)
            return
    raise ProconPortalError("Aba Interações & Respostas não encontrada no portal.")


def fetch_consumer_interactions(
    options: PortalFetchOptions,
    *,
    protocol_hint: str | None = None,
    complaint_kind: ComplaintKind = "reclamacao",
) -> PortalConsumerInteractions:
    """Abre a reclamação no portal e lê interações publicadas pelo consumidor."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=options.headless)
        page = browser.new_page()
        try:
            _open_complaint_with_code(
                page,
                options.access_code,
                complaint_kind=complaint_kind,
            )
            _open_interactions_tab(page)
            body_text = page.inner_text("body")
            parsed = parse_consumer_interactions_from_tab_text(
                body_text,
                protocol_number=protocol_hint,
            )
            if not parsed.protocol_number and protocol_hint:
                return PortalConsumerInteractions(
                    protocol_number=protocol_hint,
                    messages=parsed.messages,
                    attachment_labels=parsed.attachment_labels,
                )
            return parsed
        finally:
            browser.close()
