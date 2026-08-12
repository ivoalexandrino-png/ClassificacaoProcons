"""Modelos da Fase 2 (inventário, mapping e dry-run Monday → Sunday).

Todos os digests são SANITIZADOS por construção: não guardam nome de item, CPF,
CNPJ, texto de contrato/processo nem conteúdo de updates — apenas IDs técnicos,
rótulos de schema (labels de status), datas, contagens e hashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Strategy = Literal[
    "direto",
    "transformacao",
    "configurar_manualmente",
    "nao_migrar",
    "derivado_pelo_codigo",
]

# Escopo definitivo (decisão do usuário, 2026-08-12): migração TOTAL em duas ondas.
# Nenhum item é descartado — o que não entra na Onda 1 (cutover operacional) é
# obrigatório na Onda 2 (backfill histórico): 4.391/4.391 itens no Sunday ao final.
Classification = Literal["WAVE_1_READY", "WAVE_2_HISTORICAL", "MANUAL", "ERROR"]

# Disposição de fonte: o que fazer com cada source row (linha do Monday). É uma
# dimensão INDEPENDENTE da onda (Classification): um item pode ser wave=1 e
# disposition=ADOPT, ou wave=1 e disposition=ABSORB, etc. A soma das disposições
# deve igualar o total de source rows do snapshot (conservação).
Disposition = Literal["CREATE", "ADOPT", "ABSORB", "EXCLUDE_TEST", "MANUAL", "ERROR"]

ALL_DISPOSITIONS: tuple[Disposition, ...] = (
    "CREATE",
    "ADOPT",
    "ABSORB",
    "EXCLUDE_TEST",
    "MANUAL",
    "ERROR",
)

# Classificação de itens do lado Sunday sem source row Monday: preservar, não
# excluir, não inventar Monday ID e NÃO contar no denominador de source rows.
SundayItemClassification = Literal["SUNDAY_NATIVE"]

ManualReason = Literal[
    "MISSING_TARGET_COLUMN",
    "MISSING_STATUS_MAPPING",
    "MISSING_USER_MAPPING",
    "INVALID_RELATION_CONFIG",
    "UNSUPPORTED_FIELD",
    "FILE_REQUIRES_MATERIALIZATION",
    "AMBIGUOUS_MAPPING",
    "HISTORICAL_BACKFILL",
    "OTHER",
]

Confidence = Literal["ALTA", "MEDIA", "BAIXA"]


@dataclass(frozen=True)
class MondayColumnInfo:
    """Schema de coluna do Monday (id, título e settings — sem dados de itens)."""

    id: str
    title: str
    type: str
    settings: dict = field(default_factory=dict)

    def status_labels(self) -> tuple[str, ...]:
        labels = self.settings.get("labels")
        if isinstance(labels, dict):
            return tuple(str(label) for label in labels.values() if str(label).strip())
        return ()


@dataclass(frozen=True)
class MondayItemDigest:
    """Resumo sanitizado de um item do Monday (sem qualquer conteúdo pessoal)."""

    item_id: str
    group_id: str | None
    created_at: str | None
    updated_at: str | None
    status_labels: dict[str, str] = field(default_factory=dict)  # column_id -> label
    people_ids: tuple[str, ...] = ()
    file_count: int = 0
    file_bytes: int = 0
    has_updates: bool = False
    subitem_count: int = 0
    relation_targets: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class MondayBoardInventory:
    board_id: str
    name: str
    groups: dict[str, str] = field(default_factory=dict)  # group_id -> title
    columns: tuple[MondayColumnInfo, ...] = ()
    items: tuple[MondayItemDigest, ...] = ()
    updates_count_capped: int = 0
    updates_count_is_lower_bound: bool = False

    def column_by_id(self, column_id: str) -> MondayColumnInfo | None:
        for column in self.columns:
            if column.id == column_id:
                return column
        return None


@dataclass(frozen=True)
class SundayColumnSnapshot:
    id: str
    key: str | None
    label: str
    type: str
    is_system: bool
    settings: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SundayBoardSnapshot:
    board_id: str
    name: str
    columns: tuple[SundayColumnSnapshot, ...] = ()
    status_keys: tuple[str, ...] = ()
    groups: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ColumnPlan:
    """Plano de migração de uma coluna Monday para o Sunday."""

    monday_column_id: str
    monday_title: str
    monday_type: str
    strategy: Strategy
    sunday_target: str | None = None  # key/campo de sistema ou tipo proposto
    sunday_column_id: str | None = None  # quando a coluna já existe no destino
    exists_in_target: bool = False
    note: str | None = None


@dataclass(frozen=True)
class RelationPlan:
    monday_board_id: str
    monday_column_id: str
    monday_column_title: str
    monday_target_board_id: str | None
    sunday_board_id: str | None
    sunday_column_id: str | None
    expected_sunday_target_board_id: str | None
    configured_source_board_id: str | None
    config_ok: bool | None  # None = coluna ainda não existe no Sunday
    note: str | None = None


@dataclass(frozen=True)
class BoardPlan:
    monday_board_id: str
    monday_name: str
    domain: str
    sunday_board_id: str | None
    sunday_name: str | None
    confidence: Confidence
    note: str | None = None
    column_plans: tuple[ColumnPlan, ...] = ()
    relation_plans: tuple[RelationPlan, ...] = ()
    status_mappings: dict[str, dict[str, str | None]] = field(default_factory=dict)
    # status_mappings: column_id -> {label monday -> key sunday proposto (slug) | None}


@dataclass(frozen=True)
class ItemDryRunResult:
    monday_board_id: str
    monday_item_id: str
    classification: Classification
    reasons: tuple[ManualReason, ...] = ()
    flags: tuple[str, ...] = ()  # avisos não bloqueantes (ex.: file_materialization)
    wave: Literal["onda1", "onda2"] = "onda1"


@dataclass(frozen=True)
class UserMappingEntry:
    """De-para de responsável. A identidade técnica é hash (sem e-mail em claro)."""

    monday_user_id: str
    identity_hash: str
    sunday_user_id: str | None = None
    confidence: Literal["MATCH_EXATO", "MATCH_PROVAVEL", "SEM_MATCH"] = "SEM_MATCH"


@dataclass(frozen=True)
class LedgerRecord:
    """Registro persistente de rastreabilidade/idempotência (Etapa 10).

    Persistido em `data/monday-sunday-map.json` como dict indexado por
    `"{monday_board_id}:{monday_item_id}"` (lookup O(1); reexecução não duplica;
    retomada após falha lê `migration_status`/`attempts`; rollback lógico marca
    `migration_status="skipped"` mantendo o vínculo para auditoria).
    """

    monday_board_id: str
    monday_item_id: str
    sunday_board_id: str | None = None
    sunday_item_id: str | None = None
    domain: str | None = None
    migration_status: Literal["pending", "migrated", "skipped", "error"] = "pending"
    migrated_at: str | None = None
    source_updated_at: str | None = None
    error: str | None = None
    attempts: int = 0
    # Dimensão disposição (independente da onda). Quando ABSORB, `canonical_monday_item_id`
    # aponta para a linha canônica; múltiplos Monday IDs podem compartilhar um sunday_item_id.
    disposition: Disposition | None = None
    canonical_monday_item_id: str | None = None
    disposition_reason: str | None = None

    @property
    def key(self) -> str:
        return f"{self.monday_board_id}:{self.monday_item_id}"

    @property
    def creates_sunday_item(self) -> bool:
        return self.disposition == "CREATE"


@dataclass(frozen=True)
class SundayNativeRecord:
    """Item nativo do Sunday (sem source row Monday). Fora do denominador Monday."""

    sunday_board_id: str
    sunday_item_id: str
    classification: SundayItemClassification = "SUNDAY_NATIVE"
    note: str | None = None
