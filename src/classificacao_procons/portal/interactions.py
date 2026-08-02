"""Leitura da aba Interações & Respostas no portal Procon-SP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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

_CONSUMER_AUTHOR_MARKERS = frozenset({"consumidor", "consumidora", "reclamante"})

_COMPANY_AUTHOR_MARKERS = frozenset(
    {
        "empresa",
        "fornecedor",
        "b4a",
        "beauty for all",
        "mmkt",
    },
)

_PROCON_AUTHOR_MARKERS = frozenset(
    {
        "procon",
        "fundação procon",
        "fundacao procon",
        "procon-sp",
    },
)

_ROLE_LABEL_PATTERN = re.compile(
    r"^(consumidor(?:a)?|reclamante|empresa|fornecedor|procon.*)$",
    re.IGNORECASE,
)

_TIMESTAMP_LINE = re.compile(r"^\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?")

_ATTACHMENT_LINE = re.compile(r"\.(png|jpe?g|pdf)$", re.IGNORECASE)


AuthorRole = Literal["consumer", "company", "procon"]


@dataclass(frozen=True)
class ConsumerInteractionMessage:
    author_label: str
    body: str


@dataclass(frozen=True)
class PortalConsumerInteractions:
    protocol_number: str
    messages: tuple[ConsumerInteractionMessage, ...]
    attachment_labels: tuple[str, ...]
    procon_notices: tuple[str, ...] = ()


def _normalize_author(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def _is_procon_author(author_label: str) -> bool:
    normalized = _normalize_author(author_label)
    if not normalized:
        return False
    if normalized.startswith("procon"):
        return True
    return any(marker in normalized for marker in _PROCON_AUTHOR_MARKERS)


def _is_company_author(author_label: str) -> bool:
    normalized = _normalize_author(author_label)
    if not normalized:
        return False
    if any(marker in normalized for marker in _COMPANY_AUTHOR_MARKERS):
        return True
    if " s.a" in normalized or normalized.endswith(" s.a.") or " ltda" in normalized:
        return True
    if "serviços de tecnologia" in normalized or "servicos de tecnologia" in normalized:
        return True
    if "comércio" in normalized and " s." in normalized:
        return True
    return False


def _has_consumer_marker(author_label: str) -> bool:
    normalized = _normalize_author(author_label)
    return any(marker in normalized for marker in _CONSUMER_AUTHOR_MARKERS)


_NAME_STOPWORDS = frozenset(
    {
        "a",
        "ao",
        "com",
        "da",
        "de",
        "do",
        "dos",
        "das",
        "e",
        "em",
        "na",
        "no",
        "nos",
        "nas",
        "o",
        "os",
        "para",
        "por",
        "que",
        "sem",
        "um",
        "uma",
        "automática",
        "automatica",
        "atendimento",
        "convertido",
        "processo",
        "administrativo",
        "prezados",
        "prezado",
        "prezada",
    },
)


def _looks_like_person_name(author_label: str) -> bool:
    """Nome completo do consumidor (comum após conversão em PA)."""
    line = " ".join(author_label.split()).strip()
    if len(line) < 5 or _TIMESTAMP_LINE.match(line):
        return False
    if _is_procon_author(line) or _is_company_author(line):
        return False
    if _ROLE_LABEL_PATTERN.match(line):
        return False
    if any(char in line for char in ".:;,!?"):
        return False
    if "@" in line or "http" in line.lower():
        return False
    if _ATTACHMENT_LINE.search(line.lower()):
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 8:
        return False
    if any(word.lower() in _NAME_STOPWORDS for word in words):
        return False
    letter_words = 0
    for word in words:
        alpha = sum(1 for char in word if char.isalpha())
        if alpha >= max(2, len(word) // 2):
            letter_words += 1
    return letter_words >= 2


def _author_role(author_label: str) -> AuthorRole | None:
    if _is_procon_author(author_label):
        return "procon"
    if _has_consumer_marker(author_label):
        return "consumer"
    if _is_company_author(author_label):
        return "company"
    if _ROLE_LABEL_PATTERN.match(author_label):
        lowered = _normalize_author(author_label)
        if lowered.startswith("procon"):
            return "procon"
        if lowered in ("empresa", "fornecedor"):
            return "company"
        return "consumer"
    if _looks_like_person_name(author_label):
        return "consumer"
    return None


def _is_noise_line(line: str) -> bool:
    lower = line.lower()
    if lower in {"interações & respostas", "interacoes & respostas", "interações e respostas"}:
        return True
    if _TIMESTAMP_LINE.match(line):
        return True
    return False


def _is_attachment_line(line: str) -> bool:
    lower = line.lower()
    if lower.startswith("anexo"):
        return True
    return bool(_ATTACHMENT_LINE.search(lower))


def parse_consumer_interactions_from_tab_text(
    text: str,
    *,
    protocol_number: str | None = None,
) -> PortalConsumerInteractions:
    """
    Extrai blocos do consumidor a partir do texto da aba de interações.

    Suporta rótulos ``Consumidor`` e nomes completos após conversão em PA.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    messages: list[ConsumerInteractionMessage] = []
    procon_notices: list[str] = []
    attachment_labels: list[str] = []

    current_author: str | None = None
    current_role: AuthorRole | None = None
    current_body: list[str] = []

    def flush_message() -> None:
        nonlocal current_author, current_role, current_body
        if current_author is None or current_role is None:
            current_author = None
            current_role = None
            current_body = []
            return
        body = "\n".join(current_body).strip()
        if body:
            if current_role == "consumer":
                messages.append(
                    ConsumerInteractionMessage(author_label=current_author, body=body),
                )
            elif current_role == "procon":
                procon_notices.append(body)
        current_author = None
        current_role = None
        current_body = []

    for line in lines:
        if _is_attachment_line(line):
            attachment_labels.append(line)
            continue
        if _is_noise_line(line):
            continue

        role = _author_role(line)
        if role is not None:
            flush_message()
            current_author = line
            current_role = role
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
        procon_notices=tuple(procon_notices),
    )


def _open_interactions_tab(page: Page) -> None:
    for tab_name in _INTERACTIONS_TAB_NAMES:
        tab = page.get_by_role("tab", name=tab_name)
        if tab.count():
            tab.first.click()
            page.wait_for_timeout(2000)
            return
    raise ProconPortalError("Aba Interações & Respostas não encontrada no portal.")


def _fetch_consumer_interactions_for_kind(
    options: PortalFetchOptions,
    *,
    protocol_hint: str | None,
    complaint_kind: ComplaintKind,
) -> PortalConsumerInteractions:
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
                    procon_notices=parsed.procon_notices,
                )
            return parsed
        finally:
            browser.close()


def fetch_consumer_interactions(
    options: PortalFetchOptions,
    *,
    protocol_hint: str | None = None,
    complaint_kind: ComplaintKind | None = None,
) -> PortalConsumerInteractions:
    """Abre a reclamação no portal e lê interações publicadas pelo consumidor."""
    primary_kind = complaint_kind or options.complaint_kind
    fallback_kind: ComplaintKind = (
        "processo_administrativo" if primary_kind == "reclamacao" else "reclamacao"
    )
    kinds: list[ComplaintKind] = [primary_kind]
    if fallback_kind != primary_kind:
        kinds.append(fallback_kind)

    last_error: ProconPortalError | None = None
    for kind in kinds:
        try:
            return _fetch_consumer_interactions_for_kind(
                options,
                protocol_hint=protocol_hint,
                complaint_kind=kind,
            )
        except ProconPortalError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ProconPortalError("Não foi possível ler interações no portal.")
