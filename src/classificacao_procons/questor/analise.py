"""Núcleo de análise do Questor: transforma um snapshot em pendências fiscais.

100% offline e determinístico — é o coração testável do agente. Regras:

Certidões
- ``positiva`` (Irregular) → crítico; se estiver "aguardando conferência" no
  Questor (situação ainda não confirmada) → aviso "pendente de conferência".
- ``restricao`` → crítico.
- ``vencida`` (status ou ``data_validade`` no passado) → crítico.
- válida mas vencendo em até ``warn_within_days`` → aviso.
- ``indisponivel`` (Falha) → aviso.
- ``negativa``/``positiva_com_efeitos_negativa``/``neutra`` → sem problema.

Caixa postal
- prazo de ciência (quando presente) vencido/próximo → crítico.
- não lida: severidade pela relevância do assunto (ver ``relevancia.py``).
"""

from __future__ import annotations

from datetime import date

from classificacao_procons.credentials.mapping import normalize_label
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

# Orientação ("o que fazer") por tipo de pendência.
ORIENTACAO_CERTIDAO_IRREGULAR = (
    "Verificar os débitos/pendências no órgão e regularizar (ou confirmar "
    "parcelamento ativo). Sem certidão negativa a empresa fica impedida em "
    "licitações, financiamentos e operações que exijam regularidade fiscal."
)
ORIENTACAO_CERTIDAO_PENDENTE_CONFERENCIA = (
    "A captura está pendente de conferência no Questor — a situação ainda não é "
    "definitiva. Conferir/renovar no Questor e reconfirmar no órgão; pode já estar "
    "regular (ex.: certidão recém-emitida)."
)
ORIENTACAO_CERTIDAO_RESTRICAO = (
    "Identificar a origem da restrição no órgão emissor e providenciar a baixa."
)
ORIENTACAO_CERTIDAO_VENCIDA = "Reemitir a certidão para restabelecer a regularidade."
ORIENTACAO_CERTIDAO_A_VENCER = "Reemitir preventivamente antes do vencimento."
ORIENTACAO_CERTIDAO_INDISPONIVEL = (
    "A captura automática falhou; consultar/emitir manualmente no órgão."
)
ORIENTACAO_POR_CATEGORIA = {
    "fiscalizacao": (
        "Início/andamento de ação fiscal. Acionar o fiscal/jurídico e responder no prazo."
    ),
    "lancamento": (
        "Lançamento/auto de infração. Avaliar pagamento, parcelamento ou impugnação no prazo."
    ),
    "pagamento": (
        "Débito/atraso. Emitir a guia e quitar ou parcelar antes da inscrição em dívida ativa."
    ),
    "intimacao": "Intimação/exigência. Cumprir ou responder no prazo indicado pelo órgão.",
    "autorregularizacao": (
        "Convite à autorregularização. Revisar e corrigir antes de virar ação fiscal."
    ),
    "certidao": "Aviso de vencimento de certidão. Programar a reemissão.",
    "processo": "Movimentação em processo administrativo. Verificar necessidade de manifestação.",
}
ORIENTACAO_MENSAGEM_GENERICA = "Abrir a mensagem no órgão e avaliar se exige providência."


def _slug(value: str) -> str:
    return "-".join(value.split()).lower()


def format_cnpj(cnpj: str | None) -> str | None:
    """Formata CNPJ (14 díg.) ou CPF (11 díg.); devolve como veio se não casar."""
    if not cnpj:
        return None
    digits = "".join(ch for ch in cnpj if ch.isdigit())
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return cnpj


def is_awaiting_conference(certidao: Certidao) -> bool:
    """True quando a certidão está pendente de conferência no Questor.

    O Questor pode exibir uma certidão como Irregular enquanto a captura aguarda
    conferência (protocolo "Aguardando conferência"); nesse caso a situação ainda
    não é definitiva e não deve gerar alarme de irregularidade real.
    """
    if certidao.conferida:
        return False
    protocolo = normalize_label(certidao.protocolo or "")
    return "aguardando" in protocolo or "conferenc" in protocolo


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
    common = {
        "orgao": orgao,
        "empresa": empresa,
        "cnpj": format_cnpj(certidao.cnpj),
        "uf": certidao.uf,
        "data_emissao": certidao.data_emissao,
        "protocolo": certidao.protocolo,
        "source_url": certidao.url,
    }

    if certidao.situacao == "neutra":
        return []

    if certidao.situacao == "positiva":
        if is_awaiting_conference(certidao):
            return [
                FiscalIssue(
                    kind="certidao_pendente_conferencia",
                    severity="warning",
                    title=f"Certidão pendente de conferência — {label}",
                    detail=(
                        f"A certidão de {label} consta como irregular no Questor, mas a "
                        "captura está pendente de conferência (situação não definitiva)."
                    ),
                    due_date=certidao.data_validade,
                    dedup_key=f"certidao_pendente_conferencia:{slug}",
                    orientacao=ORIENTACAO_CERTIDAO_PENDENTE_CONFERENCIA,
                    **common,
                ),
            ]
        return [
            FiscalIssue(
                kind="certidao_positiva",
                severity="critical",
                title=f"Certidão IRREGULAR — {label}",
                detail=(
                    f"A certidão de {label} está irregular/positiva (com débitos ou "
                    "pendências), impedindo a emissão da certidão negativa."
                ),
                due_date=certidao.data_validade,
                dedup_key=f"certidao_positiva:{slug}",
                orientacao=ORIENTACAO_CERTIDAO_IRREGULAR,
                **common,
            ),
        ]

    if certidao.situacao == "restricao":
        return [
            FiscalIssue(
                kind="certidao_restricao",
                severity="critical",
                title=f"Certidão com RESTRIÇÃO — {label}",
                detail=f"A certidão de {label} está com restrição registrada no órgão.",
                due_date=certidao.data_validade,
                dedup_key=f"certidao_restricao:{slug}",
                orientacao=ORIENTACAO_CERTIDAO_RESTRICAO,
                **common,
            ),
        ]

    if certidao.situacao == "indisponivel":
        return [
            FiscalIssue(
                kind="certidao_indisponivel",
                severity="warning",
                title=f"Certidão indisponível — {label}",
                detail=(
                    f"A captura automática da certidão de {label} falhou "
                    "(sem retorno do órgão)."
                ),
                dedup_key=f"certidao_indisponivel:{slug}",
                orientacao=ORIENTACAO_CERTIDAO_INDISPONIVEL,
                **common,
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
                title=f"Certidão vencida — {label}",
                detail=(
                    f"A certidão de {label} está vencida"
                    + (f" (validade {validade.strftime('%d/%m/%Y')})" if validade else "")
                    + "."
                ),
                due_date=validade,
                dedup_key=f"certidao_vencida:{slug}",
                orientacao=ORIENTACAO_CERTIDAO_VENCIDA,
                **common,
            ),
        ]

    if certidao.situacao in REGULAR_STATUSES and validade is not None:
        days_left = (validade - today).days
        if 0 <= days_left <= warn_within_days:
            return [
                FiscalIssue(
                    kind="certidao_a_vencer",
                    severity="warning",
                    title=f"Certidão a vencer — {label}",
                    detail=(
                        f"A certidão de {label} vence em {days_left} dia(s) "
                        f"({validade.strftime('%d/%m/%Y')})."
                    ),
                    due_date=validade,
                    dedup_key=f"certidao_a_vencer:{slug}:{validade.isoformat()}",
                    orientacao=ORIENTACAO_CERTIDAO_A_VENCER,
                    **common,
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
    common = {
        "orgao": orgao,
        "empresa": empresa,
        "cnpj": format_cnpj(mensagem.cnpj),
        "remetente": mensagem.remetente,
        "data_referencia": mensagem.data_postagem,
        "source_url": mensagem.url,
    }
    prazo = mensagem.prazo_ciencia

    if prazo is not None:
        days_left = (prazo - today).days
        if days_left < 0:
            issues.append(
                FiscalIssue(
                    kind="prazo_ciencia_vencido",
                    severity="critical",
                    title=f"Prazo de ciência VENCIDO — {label}",
                    detail=(
                        f"A mensagem \"{mensagem.assunto}\" teve o prazo de "
                        f"ciência vencido em {prazo.strftime('%d/%m/%Y')}."
                    ),
                    due_date=prazo,
                    dedup_key=f"prazo_ciencia_vencido:{key_base}",
                    orientacao=ORIENTACAO_MENSAGEM_GENERICA,
                    **common,
                ),
            )
        elif days_left <= warn_within_days:
            issues.append(
                FiscalIssue(
                    kind="prazo_ciencia_proximo",
                    severity="critical",
                    title=f"Prazo de ciência próximo — {label}",
                    detail=(
                        f"A mensagem \"{mensagem.assunto}\" tem prazo de "
                        f"ciência em {days_left} dia(s) ({prazo.strftime('%d/%m/%Y')})."
                    ),
                    due_date=prazo,
                    dedup_key=f"prazo_ciencia_proximo:{key_base}",
                    orientacao=ORIENTACAO_MENSAGEM_GENERICA,
                    **common,
                ),
            )

    # Já há problema de prazo genuíno para a mensagem: não duplica.
    if issues:
        return issues

    # Aviso da mensagem não lida, com severidade pela relevância do assunto.
    if not mensagem.lida:
        classification = classify_caixa_message(mensagem)
        if classification is not None:
            category, cat_label, severity = classification
            title = f"{cat_label} — {label}"
            detail = (
                f"Mensagem relevante ({cat_label.lower()}) não lida: "
                f"\"{mensagem.assunto}\"."
            )
            orientacao = ORIENTACAO_POR_CATEGORIA.get(category, ORIENTACAO_MENSAGEM_GENERICA)
        else:
            severity = "warning"
            title = f"Mensagem não lida — {label}"
            detail = f"Mensagem não lida: \"{mensagem.assunto}\"."
            orientacao = ORIENTACAO_MENSAGEM_GENERICA
        issues.append(
            FiscalIssue(
                kind="mensagem_nao_lida",
                severity=severity,
                title=title,
                detail=detail,
                due_date=mensagem.prazo_ciencia,
                dedup_key=f"mensagem_nao_lida:{key_base}",
                orientacao=orientacao,
                **common,
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
