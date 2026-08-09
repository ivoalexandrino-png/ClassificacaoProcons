"""Conversão entre JSON e os modelos do Questor (usado pelo CLI e testes)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from classificacao_procons.questor.models import (
    Certidao,
    FiscalIssue,
    MensagemCaixaPostal,
    QuestorAnalysis,
    QuestorSnapshot,
)
from classificacao_procons.questor.parser import (
    normalize_cnpj,
    normalize_situacao,
    parse_brazilian_date,
)


class SnapshotParseError(ValueError):
    """JSON de snapshot malformado."""


def _parse_captured_at(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _certidao_from_dict(data: dict[str, Any]) -> Certidao:
    situacao_raw = data.get("situacao")
    return Certidao(
        orgao=str(data.get("orgao") or "").strip() or "órgão não informado",
        situacao=normalize_situacao(situacao_raw) if situacao_raw else "desconhecida",
        tipo=data.get("tipo"),
        cnpj=normalize_cnpj(data.get("cnpj")),
        empresa=data.get("empresa"),
        uf=data.get("uf"),
        data_emissao=parse_brazilian_date(data.get("data_emissao")),
        data_validade=parse_brazilian_date(data.get("data_validade")),
        observacao=data.get("observacao"),
        url=data.get("url"),
    )


def _mensagem_from_dict(data: dict[str, Any]) -> MensagemCaixaPostal:
    return MensagemCaixaPostal(
        orgao=str(data.get("orgao") or "").strip() or "Caixa postal",
        assunto=str(data.get("assunto") or "").strip() or "(sem assunto)",
        categoria=data.get("categoria"),
        empresa=data.get("empresa"),
        cnpj=normalize_cnpj(data.get("cnpj")),
        remetente=data.get("remetente"),
        relevante=bool(data.get("relevante", False)),
        data_postagem=parse_brazilian_date(data.get("data_postagem")),
        prazo_ciencia=parse_brazilian_date(data.get("prazo_ciencia")),
        lida=bool(data.get("lida", False)),
        protocolo=data.get("protocolo"),
        nsu=data.get("nsu"),
        url=data.get("url"),
    )


def snapshot_from_dict(data: dict[str, Any]) -> QuestorSnapshot:
    """Constrói um ``QuestorSnapshot`` a partir de um dict (JSON carregado)."""
    if not isinstance(data, dict):
        raise SnapshotParseError("Snapshot deve ser um objeto JSON.")
    certidoes_raw = data.get("certidoes", [])
    mensagens_raw = data.get("mensagens", [])
    if not isinstance(certidoes_raw, list) or not isinstance(mensagens_raw, list):
        raise SnapshotParseError("Campos 'certidoes' e 'mensagens' devem ser listas.")
    return QuestorSnapshot(
        captured_at=_parse_captured_at(data.get("captured_at")),
        empresa=data.get("empresa"),
        cnpj=normalize_cnpj(data.get("cnpj")),
        certidoes=tuple(_certidao_from_dict(item) for item in certidoes_raw),
        mensagens=tuple(_mensagem_from_dict(item) for item in mensagens_raw),
    )


def _issue_to_dict(issue: FiscalIssue) -> dict[str, Any]:
    return {
        "kind": issue.kind,
        "severity": issue.severity,
        "orgao": issue.orgao,
        "title": issue.title,
        "detail": issue.detail,
        "due_date": issue.due_date.isoformat() if issue.due_date else None,
        "source_url": issue.source_url,
        "dedup_key": issue.dedup_key,
    }


def analysis_to_dict(analysis: QuestorAnalysis) -> dict[str, Any]:
    """Serializa a análise para JSON (saída do CLI)."""
    snapshot = analysis.snapshot
    return {
        "empresa": snapshot.empresa,
        "cnpj": snapshot.cnpj,
        "captured_at": snapshot.captured_at.isoformat(),
        "has_problems": analysis.has_problems,
        "issue_count": len(analysis.issues),
        "critical_count": len(analysis.critical_issues),
        "issues": [_issue_to_dict(issue) for issue in analysis.issues],
    }
