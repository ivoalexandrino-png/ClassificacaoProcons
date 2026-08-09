"""Digest por e-mail dos editais relevantes para os pesquisadores.

Reutiliza o transporte genérico do Gmail já testado em ``questor.notifier``
(``GmailSender``/``BuiltEmail``, escopo ``gmail.send`` ou ``gmail.modify``); aqui
só montamos o conteúdo específico do radar de editais.
"""

from __future__ import annotations

from html import escape

from classificacao_procons.questor.notifier import (
    BuiltEmail,
    GmailSender,
    GmailSenderError,
)
from classificacao_procons.radar.models import Area, RadarAnalysis, RadarMatch

__all__ = [
    "BuiltEmail",
    "GmailSender",
    "GmailSenderError",
    "build_digest_email",
    "build_digest_subject",
    "build_digest_bodies",
]

_AREA_LABEL: dict[Area, str] = {
    "direito": "Direito",
    "saude": "Saúde",
    "administracao": "Administração",
    "educacao": "Educação",
    "multidisciplinar": "Multidisciplinar",
    "outro": "Outros",
}

_SCOPE_LABEL = {"nacional": "Nacional", "internacional": "Internacional"}
_STATUS_LABEL = {
    "aberto": "ABERTO",
    "previsto": "Previsto",
    "encerrado": "Encerrado",
    "desconhecido": "Verificar",
}


def _areas_label(areas: tuple[Area, ...]) -> str:
    return ", ".join(_AREA_LABEL.get(area, area) for area in areas) or "—"


def build_digest_subject(analysis: RadarAnalysis) -> str:
    total = len(analysis.matches)
    abertos = len(analysis.open_matches)
    prefixo = "[Radar de Editais]"
    if abertos:
        return f"{prefixo} {abertos} aberto(s) de {total} oportunidade(s) para pesquisa"
    return f"{prefixo} {total} oportunidade(s) de fomento para pesquisa"


def _match_line(match: RadarMatch) -> str:
    status = _STATUS_LABEL.get(match.status, match.status)
    scope = _SCOPE_LABEL.get(match.scope, match.scope)
    areas = _areas_label(match.matched_areas)
    prazo = (
        f" | prazo: {match.edital.closes_at.strftime('%d/%m/%Y')}"
        if match.edital.closes_at
        else ""
    )
    return (
        f"[{status}] {match.edital.title}\n"
        f"    {match.edital.source_name} ({scope}) | áreas: {areas}{prazo}\n"
        f"    {match.edital.url}"
    )


def build_digest_bodies(analysis: RadarAnalysis) -> tuple[str, str]:
    """Monta (texto puro, HTML) do digest a partir dos editais relevantes."""
    captured = analysis.snapshot.captured_at.strftime("%d/%m/%Y %H:%M")
    areas_interesse = _areas_label(analysis.interest_areas)

    text_lines = [
        "Radar de editais de fomento — novas oportunidades para pesquisadores",
        f"Áreas monitoradas: {areas_interesse}",
        f"Coletado em: {captured}",
        "",
        f"Foram encontrados {len(analysis.matches)} edital(is) relevante(s):",
        "",
    ]
    for match in analysis.matches:
        text_lines.append(_match_line(match))
        text_lines.append("")
    text_lines.append(
        "Acesse os links para conferir requisitos, elegibilidade e prazos de submissão.",
    )
    text_body = "\n".join(text_lines)

    html_items = []
    for match in analysis.matches:
        status = escape(_STATUS_LABEL.get(match.status, match.status))
        scope = escape(_SCOPE_LABEL.get(match.scope, match.scope))
        areas = escape(_areas_label(match.matched_areas))
        prazo = (
            f" &middot; <strong>prazo:</strong> {match.edital.closes_at.strftime('%d/%m/%Y')}"
            if match.edital.closes_at
            else ""
        )
        link = escape(match.edital.url, quote=True)
        html_items.append(
            f"<li><strong>[{status}]</strong> "
            f'<a href="{link}">{escape(match.edital.title)}</a><br>'
            f"<small>{escape(match.edital.source_name)} &middot; {scope} &middot; "
            f"áreas: {areas}{prazo}</small></li>"
        )
    html_body = (
        "<p>Radar de editais de fomento — novas oportunidades para "
        "<strong>pesquisadores</strong><br>"
        f"Áreas monitoradas: {escape(areas_interesse)}<br>"
        f"Coletado em: {escape(captured)}</p>"
        f"<p>Foram encontrados <strong>{len(analysis.matches)}</strong> "
        "edital(is) relevante(s):</p>"
        f"<ul>{''.join(html_items)}</ul>"
        "<p>Acesse os links para conferir requisitos, elegibilidade e prazos de submissão.</p>"
    )
    return text_body, html_body


def build_digest_email(
    analysis: RadarAnalysis,
    *,
    to: list[str],
    cc: list[str] | None = None,
) -> BuiltEmail:
    """Monta o e-mail de digest completo (assunto + corpos + destinatários)."""
    text_body, html_body = build_digest_bodies(analysis)
    return BuiltEmail(
        subject=build_digest_subject(analysis),
        text_body=text_body,
        html_body=html_body,
        to=tuple(to),
        cc=tuple(cc or ()),
    )
