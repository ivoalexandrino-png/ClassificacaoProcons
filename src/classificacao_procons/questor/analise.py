"""Núcleo de análise do Questor: transforma um snapshot em pendências fiscais.

100% offline e determinístico — é o coração testável do agente. Regras:

Certidões
- ``positiva`` → crítico (empresa irregular perante o órgão).
- ``vencida``, ou ``data_validade`` já passou → crítico (precisa reemitir).
- válida mas vencendo em até ``warn_within_days`` → aviso (reemitir preventivo).
- ``indisponivel`` → aviso (emissão falhou; verificar manualmente).
- ``negativa``/``positiva_com_efeitos_negativa`` dentro da validade → sem problema.

Caixa postal
- mensagem não lida → aviso.
- prazo de ciência já vencido → crítico.
- prazo de ciência em até ``warn_within_days`` → crítico (não perder o prazo).
"""

from __future__ import annotations

from datetime import date

from classificacao_procons.questor.models import (
    REGULAR_STATUSES,
    Certidao,
    FiscalIssue,
    MensagemCaixaPostal,
    QuestorAnalysis,
    QuestorSnapshot,
)
from classificacao_procons.questor.relevancia import classify_caixa_message

DEFAULT_WARN_WITHIN_DAYS = 15


def _slug(value: str) -> str:
    return "-".join(value.split()).lower()


def analyze_certidao(
    certidao: Certidao,
    *,
    today: date,
    warn_within_days: int = DEFAULT_WARN_WITHIN_DAYS,
) -> list[FiscalIssue]:
    """Avalia uma certidão e devolve as pendências (0, 1 ou mais)."""
    orgao = certidao.orgao
    empresa = certidao.empresa
    slug = _slug(f"{empresa or ''} {orgao}")
    label = f"{orgao}" + (f" ({empresa})" if empresa else "")

    if certidao.situacao == "neutra":
        return []

    if certidao.situacao == "positiva":
        return [
            FiscalIssue(
                kind="certidao_positiva",
                severity="critical",
                orgao=orgao,
                title=f"Certidão IRREGULAR — {label}",
                detail=(
                    f"A certidão de {label} está irregular/positiva (com débitos ou "
                    "pendências). Regularizar junto ao órgão."
                ),
                due_date=certidao.data_validade,
                source_url=certidao.url,
                dedup_key=f"certidao_positiva:{slug}",
            ),
        ]

    if certidao.situacao == "restricao":
        return [
            FiscalIssue(
                kind="certidao_restricao",
                severity="critical",
                orgao=orgao,
                title=f"Certidão com RESTRIÇÃO — {label}",
                detail=(
                    f"A certidão de {label} está com restrição. "
                    "Verificar e regularizar junto ao órgão."
                ),
                due_date=certidao.data_validade,
                source_url=certidao.url,
                dedup_key=f"certidao_restricao:{slug}",
            ),
        ]

    if certidao.situacao == "indisponivel":
        return [
            FiscalIssue(
                kind="certidao_indisponivel",
                severity="warning",
                orgao=orgao,
                title=f"Certidão indisponível — {label}",
                detail=(
                    f"Não foi possível emitir/consultar a certidão de {label}. "
                    "Verificar manualmente no órgão emissor."
                ),
                source_url=certidao.url,
                dedup_key=f"certidao_indisponivel:{slug}",
            ),
        ]

    validade = certidao.data_validade
    already_expired = certidao.situacao == "vencida" or (
        validade is not None and validade < today
    )
    if already_expired:
        return [
            FiscalIssue(
                kind="certidao_vencida",
                severity="critical",
                orgao=orgao,
                title=f"Certidão vencida — {label}",
                detail=(
                    f"A certidão de {label} está vencida"
                    + (f" (validade {validade.strftime('%d/%m/%Y')})" if validade else "")
                    + ". Reemitir."
                ),
                due_date=validade,
                source_url=certidao.url,
                dedup_key=f"certidao_vencida:{slug}",
            ),
        ]

    if certidao.situacao in REGULAR_STATUSES and validade is not None:
        days_left = (validade - today).days
        if 0 <= days_left <= warn_within_days:
            return [
                FiscalIssue(
                    kind="certidao_a_vencer",
                    severity="warning",
                    orgao=orgao,
                    title=f"Certidão a vencer — {label}",
                    detail=(
                        f"A certidão de {label} vence em {days_left} dia(s) "
                        f"({validade.strftime('%d/%m/%Y')}). Reemitir preventivamente."
                    ),
                    due_date=validade,
                    source_url=certidao.url,
                    dedup_key=f"certidao_a_vencer:{slug}:{validade.isoformat()}",
                ),
            ]

    return []


def analyze_mensagem(
    mensagem: MensagemCaixaPostal,
    *,
    today: date,
    warn_within_days: int = DEFAULT_WARN_WITHIN_DAYS,
) -> list[FiscalIssue]:
    """Avalia uma mensagem da caixa postal e devolve as pendências."""
    issues: list[FiscalIssue] = []
    orgao = mensagem.orgao
    empresa = mensagem.empresa
    label = f"{orgao}" + (f", {empresa}" if empresa else "")
    key_base = mensagem.nsu or mensagem.protocolo or _slug(
        f"{empresa or ''} {orgao} {mensagem.assunto}",
    )
    prazo = mensagem.prazo_ciencia

    if prazo is not None:
        days_left = (prazo - today).days
        if days_left < 0:
            issues.append(
                FiscalIssue(
                    kind="prazo_ciencia_vencido",
                    severity="critical",
                    orgao=orgao,
                    title=f"Prazo de ciência VENCIDO — {label}",
                    detail=(
                        f"A mensagem \"{mensagem.assunto}\" ({label}) teve o prazo de "
                        f"ciência vencido em {prazo.strftime('%d/%m/%Y')}."
                    ),
                    due_date=prazo,
                    source_url=mensagem.url,
                    dedup_key=f"prazo_ciencia_vencido:{key_base}",
                ),
            )
        elif days_left <= warn_within_days:
            issues.append(
                FiscalIssue(
                    kind="prazo_ciencia_proximo",
                    severity="critical",
                    orgao=orgao,
                    title=f"Prazo de ciência próximo — {label}",
                    detail=(
                        f"A mensagem \"{mensagem.assunto}\" ({label}) tem prazo de "
                        f"ciência em {days_left} dia(s) ({prazo.strftime('%d/%m/%Y')})."
                    ),
                    due_date=prazo,
                    source_url=mensagem.url,
                    dedup_key=f"prazo_ciencia_proximo:{key_base}",
                ),
            )

    # Já há problema de prazo genuíno para a mensagem: não duplica.
    if issues:
        return issues

    # Aviso da mensagem não lida, com severidade pela relevância do assunto
    # (fiscalização/lançamento/atraso → crítico; certidão/processo → aviso;
    # rotineira → aviso genérico). A seleção do que chega aqui é da policy.
    if not mensagem.lida:
        classification = classify_caixa_message(mensagem)
        if classification is not None:
            _category, cat_label, severity = classification
            title = f"{cat_label} — {label}"
            detail = (
                f"Mensagem relevante ({cat_label.lower()}) não lida em {label}: "
                f"\"{mensagem.assunto}\"."
            )
        else:
            severity = "warning"
            title = f"Mensagem não lida — {label}"
            detail = (
                f"Há mensagem não lida na caixa postal de {label}: "
                f"\"{mensagem.assunto}\"."
            )
        issues.append(
            FiscalIssue(
                kind="mensagem_nao_lida",
                severity=severity,
                orgao=orgao,
                title=title,
                detail=detail,
                due_date=mensagem.prazo_ciencia,
                source_url=mensagem.url,
                dedup_key=f"mensagem_nao_lida:{key_base}",
            ),
        )

    return issues


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def analyze_snapshot(
    snapshot: QuestorSnapshot,
    *,
    today: date | None = None,
    warn_within_days: int = DEFAULT_WARN_WITHIN_DAYS,
) -> QuestorAnalysis:
    """Analisa todas as certidões e mensagens, ordenando por severidade."""
    reference = today or date.today()
    issues: list[FiscalIssue] = []
    for certidao in snapshot.certidoes:
        issues.extend(
            analyze_certidao(certidao, today=reference, warn_within_days=warn_within_days),
        )
    for mensagem in snapshot.mensagens:
        issues.extend(
            analyze_mensagem(mensagem, today=reference, warn_within_days=warn_within_days),
        )

    issues.sort(key=lambda issue: (_SEVERITY_ORDER.get(issue.severity, 9), issue.orgao))
    return QuestorAnalysis(snapshot=snapshot, issues=tuple(issues))
