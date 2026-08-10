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


def build_alert_subject(analysis: QuestorAnalysis, *, weekly: bool = False) -> str:
    empresa = _empresa_label(analysis)
    criticos = len(analysis.critical_issues)
    total = len(analysis.issues)
    prefixo = "[Questor] Resumo semanal" if weekly else "[Questor] Pendência fiscal"
    if criticos:
        return f"{prefixo} — CRÍTICA ({criticos}/{total}) — {empresa}"
    return f"{prefixo} ({total}) — {empresa}"


FRESHNESS_NOTE = (
    "Observação: a situação reflete a última captura do Questor e pode não "
    "considerar emissões, pagamentos ou baixas recentes. Em caso de dúvida, "
    "reconfirme diretamente no órgão (e-CAC/Receita, PGFN, SEFAZ, etc.)."
)


def _fmt_date(value) -> str | None:
    return value.strftime("%d/%m/%Y") if value else None


_PROTOCOLO_STATUS_WORDS = (
    "aguard",
    "conferen",
    "habilitad",
    "ativo",
    "restri",
    "falha",
    "erro",
    "pendente",
)


def _meaningful_protocolo(protocolo: str | None) -> str | None:
    """Mostra o protocolo só quando é um status legível (não um código/hash)."""
    if not protocolo:
        return None
    lowered = protocolo.casefold()
    if any(word in lowered for word in _PROTOCOLO_STATUS_WORDS):
        return protocolo
    return None


def _issue_meta_lines(issue: FiscalIssue) -> list[str]:
    """Linhas de metadados/contexto de uma pendência (texto puro)."""
    lines: list[str] = []
    if issue.empresa:
        empresa = issue.empresa + (f" (CNPJ/CPF {issue.cnpj})" if issue.cnpj else "")
        lines.append(f"Empresa/Titular: {empresa}")
    orgao = issue.orgao + (f" / {issue.uf}" if issue.uf else "")
    lines.append(f"Órgão: {orgao}")
    status = _meaningful_protocolo(issue.protocolo)
    if status:
        lines.append(f"Situação no Questor: {status}")
    if issue.remetente:
        lines.append(f"Remetente: {issue.remetente}")
    datas = []
    if issue.data_emissao:
        datas.append(f"emissão {_fmt_date(issue.data_emissao)}")
    if issue.data_referencia:
        datas.append(f"envio {_fmt_date(issue.data_referencia)}")
    if issue.due_date:
        rotulo = "prazo" if issue.kind.startswith("prazo") else "vencimento"
        datas.append(f"{rotulo} {_fmt_date(issue.due_date)}")
    if datas:
        lines.append("Datas: " + " · ".join(datas))
    return lines


def _issue_block(issue: FiscalIssue) -> str:
    label = _SEVERITY_LABEL.get(issue.severity, issue.severity)
    lines = [f"[{label}] {issue.title}", f"    {issue.detail}"]
    for meta in _issue_meta_lines(issue):
        lines.append(f"    {meta}")
    if issue.orientacao:
        lines.append(f"    O que fazer: {issue.orientacao}")
    if issue.source_url:
        lines.append(f"    Link: {issue.source_url}")
    return "\n".join(lines)


def build_alert_bodies(
    analysis: QuestorAnalysis,
    *,
    extra_note: str | None = None,
    weekly: bool = False,
) -> tuple[str, str]:
    """Monta (texto puro, HTML) do e-mail a partir das pendências."""
    empresa = _empresa_label(analysis)
    captured = analysis.snapshot.captured_at.strftime("%d/%m/%Y %H:%M")
    criticos = len(analysis.critical_issues)
    titulo = (
        "Resumo semanal consolidado do Questor"
        if weekly
        else "Análise automática do Questor"
    )
    intro = (
        f"{len(analysis.issues)} pendência(s) ainda em aberto "
        f"({criticos} crítica(s)) — inclui itens já avisados:"
        if weekly
        else f"Foram encontradas {len(analysis.issues)} pendência(s) "
        f"({criticos} crítica(s)):"
    )

    text_lines = [
        f"{titulo} — {empresa}",
        f"Coletado em: {captured}",
        "",
        intro,
        "",
    ]
    for issue in analysis.issues:
        text_lines.append(_issue_block(issue))
        text_lines.append("")
    if extra_note:
        text_lines.append(extra_note)
        text_lines.append("")
    text_lines.append(FRESHNESS_NOTE)
    text_lines.append("")
    text_lines.append(
        "Favor providenciar a regularização junto ao time fiscal e de contabilidade.",
    )
    text_body = "\n".join(text_lines)

    html_items = []
    for issue in analysis.issues:
        label = escape(_SEVERITY_LABEL.get(issue.severity, issue.severity))
        meta = "".join(
            f"<br><span style=\"color:#555\">{escape(line)}</span>"
            for line in _issue_meta_lines(issue)
        )
        orientacao = (
            f"<br><em>O que fazer:</em> {escape(issue.orientacao)}"
            if issue.orientacao
            else ""
        )
        link = (
            f'<br><a href="{escape(issue.source_url, quote=True)}">Abrir no Questor</a>'
            if issue.source_url
            else ""
        )
        html_items.append(
            f"<li style=\"margin-bottom:10px\"><strong>[{label}]</strong> "
            f"{escape(issue.title)}<br>{escape(issue.detail)}{meta}{orientacao}{link}</li>"
        )
    note_html = f"<p><em>{escape(extra_note)}</em></p>" if extra_note else ""
    html_body = (
        f"<p>{escape(titulo)} — <strong>{escape(empresa)}</strong><br>"
        f"Coletado em: {escape(captured)}</p>"
        f"<p>{escape(intro)}</p>"
        f"<ul>{''.join(html_items)}</ul>"
        f"{note_html}"
        f"<p style=\"color:#555;font-size:12px\">{escape(FRESHNESS_NOTE)}</p>"
        "<p>Favor providenciar a regularização junto ao time fiscal e de contabilidade.</p>"
    )
    return text_body, html_body


def build_alert_email(
    analysis: QuestorAnalysis,
    *,
    to: list[str],
    cc: list[str] | None = None,
    extra_note: str | None = None,
    weekly: bool = False,
) -> BuiltEmail:
    """Monta o e-mail de alerta completo (assunto + corpos + destinatários)."""
    text_body, html_body = build_alert_bodies(analysis, extra_note=extra_note, weekly=weekly)
    return BuiltEmail(
        subject=build_alert_subject(analysis, weekly=weekly),
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
