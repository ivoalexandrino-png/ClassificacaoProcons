"""Envio de alertas fiscais por e-mail (Gmail API) para o time fiscal/contábil."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classificacao_procons.google_auth import load_credentials
from classificacao_procons.questor.models import FiscalIssue, QuestorAnalysis

_SEVERITY_LABEL = {
    "critical": "CRÍTICO",
    "warning": "Atenção",
    "info": "Informativo",
}


class GmailSenderError(RuntimeError):
    """Erro ao enviar e-mail pela API do Gmail."""


@dataclass(frozen=True)
class BuiltEmail:
    """E-mail pronto para envio (assunto + corpos)."""

    subject: str
    text_body: str
    html_body: str
    to: tuple[str, ...]
    cc: tuple[str, ...] = ()


def _empresa_label(analysis: QuestorAnalysis) -> str:
    snapshot = analysis.snapshot
    parts = [part for part in (snapshot.empresa, snapshot.cnpj) if part]
    return " — ".join(parts) if parts else "empresa"


def build_alert_subject(analysis: QuestorAnalysis) -> str:
    empresa = _empresa_label(analysis)
    criticos = len(analysis.critical_issues)
    total = len(analysis.issues)
    prefixo = "[Questor] Pendência fiscal"
    if criticos:
        return f"{prefixo} CRÍTICA ({criticos}/{total}) — {empresa}"
    return f"{prefixo} ({total}) — {empresa}"


def _issue_line(issue: FiscalIssue) -> str:
    label = _SEVERITY_LABEL.get(issue.severity, issue.severity)
    prazo = f" | prazo: {issue.due_date.strftime('%d/%m/%Y')}" if issue.due_date else ""
    return f"[{label}] {issue.title}{prazo}\n    {issue.detail}"


def build_alert_bodies(
    analysis: QuestorAnalysis,
    *,
    extra_note: str | None = None,
) -> tuple[str, str]:
    """Monta (texto puro, HTML) do e-mail a partir das pendências."""
    empresa = _empresa_label(analysis)
    captured = analysis.snapshot.captured_at.strftime("%d/%m/%Y %H:%M")

    text_lines = [
        f"Análise automática do Questor — {empresa}",
        f"Coletado em: {captured}",
        "",
        f"Foram encontradas {len(analysis.issues)} pendência(s):",
        "",
    ]
    for issue in analysis.issues:
        text_lines.append(_issue_line(issue))
        if issue.source_url:
            text_lines.append(f"    Link: {issue.source_url}")
        text_lines.append("")
    if extra_note:
        text_lines.append(extra_note)
        text_lines.append("")
    text_lines.append(
        "Favor providenciar a regularização junto ao time fiscal e de contabilidade.",
    )
    text_body = "\n".join(text_lines)

    html_items = []
    for issue in analysis.issues:
        label = escape(_SEVERITY_LABEL.get(issue.severity, issue.severity))
        prazo = (
            f" &middot; <strong>prazo:</strong> {issue.due_date.strftime('%d/%m/%Y')}"
            if issue.due_date
            else ""
        )
        link = (
            f'<br><a href="{escape(issue.source_url, quote=True)}">Abrir no Questor</a>'
            if issue.source_url
            else ""
        )
        html_items.append(
            f"<li><strong>[{label}]</strong> {escape(issue.title)}{prazo}"
            f"<br>{escape(issue.detail)}{link}</li>"
        )
    note_html = f"<p><em>{escape(extra_note)}</em></p>" if extra_note else ""
    html_body = (
        f"<p>Análise automática do Questor — <strong>{escape(empresa)}</strong><br>"
        f"Coletado em: {escape(captured)}</p>"
        f"<p>Foram encontradas <strong>{len(analysis.issues)}</strong> pendência(s):</p>"
        f"<ul>{''.join(html_items)}</ul>"
        f"{note_html}"
        "<p>Favor providenciar a regularização junto ao time fiscal e de contabilidade.</p>"
    )
    return text_body, html_body


def build_alert_email(
    analysis: QuestorAnalysis,
    *,
    to: list[str],
    cc: list[str] | None = None,
    extra_note: str | None = None,
) -> BuiltEmail:
    """Monta o e-mail de alerta completo (assunto + corpos + destinatários)."""
    text_body, html_body = build_alert_bodies(analysis, extra_note=extra_note)
    return BuiltEmail(
        subject=build_alert_subject(analysis),
        text_body=text_body,
        html_body=html_body,
        to=tuple(to),
        cc=tuple(cc or ()),
    )


def _encode_raw(email: BuiltEmail, *, sender: str | None) -> str:
    message = EmailMessage()
    message["To"] = ", ".join(email.to)
    if email.cc:
        message["Cc"] = ", ".join(email.cc)
    if sender:
        message["From"] = sender
    message["Subject"] = email.subject
    message.set_content(email.text_body)
    message.add_alternative(email.html_body, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


class GmailSender:
    """Envia e-mails pela API do Gmail (escopo ``gmail.send`` ou ``gmail.modify``)."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_credentials(cls, *, token_path: str) -> GmailSender:
        credentials = load_credentials(token_path)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return cls(service)

    def send(self, email: BuiltEmail, *, sender: str | None = None) -> str:
        """Envia o e-mail e devolve o ``id`` da mensagem criada."""
        if not email.to:
            raise GmailSenderError("Nenhum destinatário informado para o alerta.")
        raw = _encode_raw(email, sender=sender)
        try:
            response = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except HttpError as exc:
            raise GmailSenderError(f"Falha ao enviar e-mail: {exc}") from exc
        return str(response.get("id", ""))
