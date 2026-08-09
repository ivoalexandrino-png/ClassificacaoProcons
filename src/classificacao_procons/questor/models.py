"""Modelos de domínio do agente Questor (certidões e caixa postal)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

# Situação canônica de uma certidão. Mapeia o vocabulário do Questor:
# Regular→negativa, Irregular→positiva, Neutro→neutra, Falha→indisponivel,
# Restrição→restricao. ``a_vencer`` é derivada na análise (não vem do portal).
CertidaoStatus = Literal[
    "negativa",
    "positiva",
    "positiva_com_efeitos_negativa",
    "restricao",
    "vencida",
    "indisponivel",
    "neutra",
    "desconhecida",
]

# Situações que liberam o contribuinte (certidão regular).
REGULAR_STATUSES: frozenset[str] = frozenset(
    {"negativa", "positiva_com_efeitos_negativa"},
)

# Severidade de um problema detectado.
IssueSeverity = Literal["critical", "warning", "info"]

# Tipos de problema que o agente reporta.
IssueKind = Literal[
    "certidao_positiva",
    "certidao_restricao",
    "certidao_pendente_conferencia",
    "certidao_vencida",
    "certidao_a_vencer",
    "certidao_indisponivel",
    "mensagem_nao_lida",
    "prazo_ciencia_vencido",
    "prazo_ciencia_proximo",
    "caixa_postal_resumo",
]


@dataclass(frozen=True)
class Certidao:
    """Situação de uma certidão negativa no Questor."""

    orgao: str
    situacao: CertidaoStatus = "desconhecida"
    tipo: str | None = None
    cnpj: str | None = None
    empresa: str | None = None
    uf: str | None = None
    data_emissao: date | None = None
    data_validade: date | None = None
    protocolo: str | None = None
    conferida: bool | None = None
    observacao: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class MensagemCaixaPostal:
    """Mensagem da caixa postal eletrônica (e-CAC, SEFAZ, etc.) no Questor."""

    orgao: str
    assunto: str
    categoria: str | None = None
    empresa: str | None = None
    cnpj: str | None = None
    remetente: str | None = None
    relevante: bool = False
    data_postagem: date | None = None
    prazo_ciencia: date | None = None
    lida: bool = False
    protocolo: str | None = None
    nsu: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class QuestorSnapshot:
    """Retrato do Questor num instante: certidões + mensagens da caixa postal."""

    captured_at: datetime
    empresa: str | None = None
    cnpj: str | None = None
    certidoes: tuple[Certidao, ...] = ()
    mensagens: tuple[MensagemCaixaPostal, ...] = ()


@dataclass(frozen=True)
class FiscalIssue:
    """Pendência fiscal detectada que exige providência do time."""

    kind: IssueKind
    severity: IssueSeverity
    orgao: str
    title: str
    detail: str
    due_date: date | None = None
    source_url: str | None = None
    dedup_key: str = ""
    # Metadados estruturados para um e-mail detalhado.
    empresa: str | None = None
    cnpj: str | None = None
    uf: str | None = None
    data_emissao: date | None = None
    data_referencia: date | None = None
    remetente: str | None = None
    orientacao: str | None = None


@dataclass(frozen=True)
class QuestorAnalysis:
    """Resultado da análise de um snapshot do Questor."""

    snapshot: QuestorSnapshot
    issues: tuple[FiscalIssue, ...] = field(default_factory=tuple)

    @property
    def has_problems(self) -> bool:
        return bool(self.issues)

    @property
    def critical_issues(self) -> tuple[FiscalIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "critical")
