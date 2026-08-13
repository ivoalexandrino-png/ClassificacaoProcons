"""Guard global de completude source → mapping antes de APPLY.

Falha se coluna de negócio preenchida no Monday não tiver mapping aprovado
(MAPPED_DIRECT, MAPPED_TRANSFORM ou INTENTIONALLY_NOT_MIGRATED com reason).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.models import BoardPlan, MondayBoardInventory
from classificacao_procons.migration.source_audit import (
    APPLY_WRITER_SKIP_TYPES,
    classify_mapping_status,
    derive_expected_sunday_value,
)


@dataclass(frozen=True)
class SourceCompletenessIssue:
    monday_item_id: str
    monday_column_id: str
    field_name: str
    issue: str
    detail: str


@dataclass
class SourceCompletenessReport:
    ok: bool
    issues: list[SourceCompletenessIssue] = field(default_factory=list)

    @property
    def detail(self) -> str:
        if self.ok:
            return "todas as colunas source preenchidas possuem mapping aprovado"
        sample = "; ".join(
            f"{issue.monday_item_id}/{issue.field_name}:{issue.issue}"
            for issue in self.issues[:5]
        )
        extra = len(self.issues) - min(len(self.issues), 5)
        suffix = f" (+{extra} mais)" if extra > 0 else ""
        return f"{len(self.issues)} problema(s): {sample}{suffix}"


def _source_nonempty(text: str | None) -> bool:
    return bool((text or "").strip())


def check_source_completeness_for_sources(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    apply_sources: dict[str, MondayApplySource],
    item_ids: set[str] | None = None,
) -> SourceCompletenessReport:
    """Valida mapping coverage para colunas source preenchidas (pré-APPLY)."""
    column_plans = {plan.monday_column_id: plan for plan in board_plan.column_plans}
    issues: list[SourceCompletenessIssue] = []

    for item_id, source in apply_sources.items():
        if item_ids is not None and item_id not in item_ids:
            continue
        for monday_column in inventory.columns:
            if monday_column.type in {"name", "item_id", "creation_log", "last_updated"}:
                continue
            source_text = source.values_by_column_id.get(monday_column.id)
            if not _source_nonempty(source_text):
                continue

            plan_column = column_plans.get(monday_column.id)
            if plan_column is None:
                issues.append(
                    SourceCompletenessIssue(
                        monday_item_id=item_id,
                        monday_column_id=monday_column.id,
                        field_name=monday_column.title,
                        issue="UNMAPPED",
                        detail="Coluna sem plano de mapping",
                    ),
                )
                continue

            status, reason = classify_mapping_status(plan_column)
            if status == "UNMAPPED":
                issues.append(
                    SourceCompletenessIssue(
                        monday_item_id=item_id,
                        monday_column_id=monday_column.id,
                        field_name=monday_column.title,
                        issue="UNMAPPED",
                        detail=reason or "Coluna business sem destino Sunday",
                    ),
                )
                continue

            if status == "INTENTIONALLY_NOT_MIGRATED":
                if not reason:
                    issues.append(
                        SourceCompletenessIssue(
                            monday_item_id=item_id,
                            monday_column_id=monday_column.id,
                            field_name=monday_column.title,
                            issue="INTENTIONAL_WITHOUT_REASON",
                            detail="INTENTIONALLY_NOT_MIGRATED exige reason",
                        ),
                    )
                continue

            if status in {"MAPPED_DIRECT", "MAPPED_TRANSFORM"}:
                if monday_column.type in APPLY_WRITER_SKIP_TYPES:
                    issues.append(
                        SourceCompletenessIssue(
                            monday_item_id=item_id,
                            monday_column_id=monday_column.id,
                            field_name=monday_column.title,
                            issue="MAPPED_BUT_NOT_WRITABLE",
                            detail=(
                                f"Mapping {status} mas apply_writer omite tipo "
                                f"{monday_column.type}"
                            ),
                        ),
                    )
                    continue
                expected = derive_expected_sunday_value(
                    monday_column=monday_column,
                    source_text=source_text,
                    board_plan=board_plan,
                )
                if expected is None and monday_column.type not in {"formula"}:
                    issues.append(
                        SourceCompletenessIssue(
                            monday_item_id=item_id,
                            monday_column_id=monday_column.id,
                            field_name=monday_column.title,
                            issue="TRANSFORMATION_ERROR",
                            detail="Não foi possível derivar valor target esperado",
                        ),
                    )

    return SourceCompletenessReport(ok=not issues, issues=issues)


def build_source_completeness_gate_check(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    apply_sources: dict[str, MondayApplySource],
    item_ids: set[str] | None = None,
) -> tuple[bool, str]:
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources=apply_sources,
        item_ids=item_ids,
    )
    return report.ok, report.detail
