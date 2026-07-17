"""Identificação e extração de intimações judiciais recebidas por e-mail/push."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime
from typing import Final

from classificacao_procons.email.parser import _html_to_text, normalize_email_address
from classificacao_procons.juridico.cnj import extract_process_number, tribunal_acronym
from classificacao_procons.juridico.models import (
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_DECISAO,
    NOTIFICATION_TYPE_INTIMACAO,
    NOTIFICATION_TYPE_SENTENCA,
    ParsedIntimacao,
)

JUDICIAL_SENDER_DOMAIN: Final = ".jus.br"

ENV_FORWARDER_EMAILS: Final = "JURIDICO_FORWARDER_EMAILS"

# E-mails pessoais que encaminham intimações para a caixa corporativa.
DEFAULT_FORWARDER_EMAILS: Final[tuple[str, ...]] = (
    "ivo.alexandrino@hotmail.com",
    "adv.ialexandrino@gmail.com",
    "adv.ivoalexandrino@gmail.com",
)

# Remetente oficial do Domicílio Judicial Eletrônico (já coberto por .jus.br).
DJE_SENDER: Final = "domicilio.comunicacoes@cnj.jus.br"

JUDICIAL_SUBJECT_KEYWORDS: Final[tuple[str, ...]] = (
    "intimacao",
    "citacao",
    "audiencia",
    "expediente",
    "publicacao",
    "movimentacao processual",
    "andamento processual",
    "diario de justica",
    "domicilio judicial",
    "comunicacao processual",
    "teor da comunicacao",
    "push",
)

JUDICIAL_BODY_KEYWORDS: Final[tuple[str, ...]] = JUDICIAL_SUBJECT_KEYWORDS + (
    "vara",
    "juizado",
    "tribunal",
    "poder judiciario",
    "prazo",
    "sentenca",
    "despacho",
)

_FORWARDED_SENDER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:de|from)\s*:\s*[^\n<]*<?([\w.+-]+@[\w.-]+\.jus\.br)>?",
    re.IGNORECASE,
)

_SUMMARY_MAX_LENGTH: Final = 600

_DEADLINE_DAYS_PATTERN = re.compile(
    r"prazo\s*(?:de|:)?\s*(\d{1,3})\s*(?:\([^)]*\)\s*)?dias?(?:\s*(uteis|corridos))?",
)

_DEADLINE_DATE_PATTERN = re.compile(
    r"prazo\s+(?:final|fatal)?\s*(?:para[^.\n]*?)?(?:ate|e|em)\s*(?:o\s+dia\s+)?"
    r"(\d{2}[/-]\d{2}[/-]\d{4})",
)

_HEARING_SECTION_PATTERN = re.compile(r"audiencia[^.]{0,200}")

_DATE_PATTERN = re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})")
_TIME_PATTERN = re.compile(r"as\s+(\d{1,2})[:h](\d{2})?")

_COURT_UNIT_PATTERN = re.compile(
    r"((?:\d+\s*[ao]?\s+)?(?:vara|juizado(?:\s+especial)?|foro|comarca)[^\n;,]{0,80})",
    re.IGNORECASE,
)

_NOTIFICATION_TYPE_KEYWORDS: Final[tuple[tuple[str, str], ...]] = (
    ("citacao", NOTIFICATION_TYPE_CITACAO),
    ("citado", NOTIFICATION_TYPE_CITACAO),
    ("audiencia", NOTIFICATION_TYPE_AUDIENCIA),
    ("sentenca", NOTIFICATION_TYPE_SENTENCA),
    ("decisao", NOTIFICATION_TYPE_DECISAO),
    ("despacho", NOTIFICATION_TYPE_DECISAO),
)


class IntimacaoParseError(ValueError):
    """E-mail reconhecido como judicial, mas sem dados extraíveis."""


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(value).casefold()).strip()


def get_forwarder_emails_from_env() -> tuple[str, ...]:
    """E-mails pessoais autorizados a encaminhar intimações (separados por vírgula)."""
    raw = os.environ.get(ENV_FORWARDER_EMAILS, "")
    configured = tuple(
        address.strip().lower() for address in raw.split(",") if address.strip()
    )
    return configured or DEFAULT_FORWARDER_EMAILS


def _has_judicial_signals(*, normalized_subject: str, body: str | None) -> bool:
    if any(keyword in normalized_subject for keyword in JUDICIAL_SUBJECT_KEYWORDS):
        return True
    if not body:
        return False
    if extract_process_number(body) is None:
        return False
    normalized_body = _normalize(body)
    return any(keyword in normalized_body for keyword in JUDICIAL_BODY_KEYWORDS)


def is_judicial_notification(
    *,
    subject: str,
    sender: str,
    body: str | None = None,
) -> bool:
    """
    Retorna True para intimações judiciais recebidas por três caminhos:

    - e-mail direto de tribunal/CNJ (remetente ``.jus.br``, inclui o
      Domicílio Judicial Eletrônico);
    - encaminhamento do e-mail pessoal cadastrado em ``JURIDICO_FORWARDER_EMAILS``
      (qualquer conteúdo com sinais judiciais no assunto/corpo);
    - qualquer remetente, desde que assunto ou corpo tenham sinais judiciais
      claros (número CNJ + termos processuais, "Fwd:/Enc:" incluídos).
    """
    sender_address = normalize_email_address(sender)
    if sender_address.endswith(JUDICIAL_SENDER_DOMAIN):
        return True

    normalized_subject = _normalize(subject)
    if sender_address in get_forwarder_emails_from_env():
        return _has_judicial_signals(normalized_subject=normalized_subject, body=body)

    if body and _FORWARDED_SENDER_PATTERN.search(body):
        return True

    return _has_judicial_signals(normalized_subject=normalized_subject, body=body)


def _detect_notification_type(normalized_text: str) -> str:
    for keyword, notification_type in _NOTIFICATION_TYPE_KEYWORDS:
        if keyword in normalized_text:
            return notification_type
    return NOTIFICATION_TYPE_INTIMACAO


def _extract_deadline_days(normalized_text: str) -> tuple[int | None, bool]:
    match = _DEADLINE_DAYS_PATTERN.search(normalized_text)
    if not match:
        return None, True
    days = int(match.group(1))
    qualifier = match.group(2) or "uteis"
    return days, qualifier != "corridos"


def _parse_date(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _extract_deadline_date(normalized_text: str) -> date | None:
    match = _DEADLINE_DATE_PATTERN.search(normalized_text)
    if not match:
        return None
    date_match = _DATE_PATTERN.fullmatch(match.group(1))
    if not date_match:
        return None
    return _parse_date(*date_match.groups())


def _extract_hearing_datetime(normalized_text: str) -> datetime | None:
    for section_match in _HEARING_SECTION_PATTERN.finditer(normalized_text):
        section = section_match.group(0)
        date_match = _DATE_PATTERN.search(section)
        if not date_match:
            continue
        hearing_date = _parse_date(*date_match.groups())
        if hearing_date is None:
            continue
        hour, minute = 0, 0
        time_match = _TIME_PATTERN.search(section)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            if hour > 23 or minute > 59:
                hour, minute = 0, 0
        return datetime(
            hearing_date.year,
            hearing_date.month,
            hearing_date.day,
            hour,
            minute,
        )
    return None


def _extract_court_unit(text: str) -> str | None:
    match = _COURT_UNIT_PATTERN.search(_strip_accents(text))
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip().rstrip(".") or None


def _build_summary(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= _SUMMARY_MAX_LENGTH:
        return collapsed
    return collapsed[: _SUMMARY_MAX_LENGTH - 1].rstrip() + "…"


def parse_judicial_notification_body(
    *,
    html: str | None = None,
    text: str | None = None,
    subject: str = "",
) -> ParsedIntimacao:
    """
    Extrai número CNJ, tipo, prazo, audiência e vara do corpo da intimação.

    Pelo menos um de `html` ou `text` deve ser informado.
    """
    if not html and not text:
        raise IntimacaoParseError("Corpo do e-mail vazio.")

    full_text = text or ""
    if html:
        full_text = f"{full_text}\n{_html_to_text(html)}".strip()

    searchable = f"{subject}\n{full_text}"
    process_number = extract_process_number(searchable)
    if not process_number:
        raise IntimacaoParseError("Número de processo (CNJ) não encontrado no e-mail.")

    normalized_text = _normalize(searchable)
    deadline_days, in_business_days = _extract_deadline_days(normalized_text)

    return ParsedIntimacao(
        process_number=process_number,
        notification_type=_detect_notification_type(normalized_text),
        tribunal=tribunal_acronym(process_number),
        court_unit=_extract_court_unit(full_text),
        deadline_days=deadline_days,
        deadline_in_business_days=in_business_days,
        deadline_date=_extract_deadline_date(normalized_text),
        hearing_datetime=_extract_hearing_datetime(normalized_text),
        summary=_build_summary(full_text),
    )
