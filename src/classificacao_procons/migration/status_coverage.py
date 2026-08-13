"""Cobertura e diagnóstico de custom status Monday → Sunday (read-only + guard pré-APPLY)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.column_transforms import (
    StatusResolveError,
    resolve_sunday_custom_status_option,
)
from classificacao_procons.migration.models import (
    BoardPlan,
    MondayBoardInventory,
    SundayBoardSnapshot,
)
from classificacao_procons.migration.source_audit import derive_expected_sunday_value

StatusSourceClassification = Literal[
    "EXACT_OPTION",
    "NORMALIZED_EXACT_OPTION",
    "EXPLICIT_MAPPING_EXISTS",
    "SEMANTIC_CANDIDATE_ONLY",
    "TARGET_OPTION_MISSING",
    "AMBIGUOUS",
    "OTHER",
]

StatusResolution = Literal["RESOLVED", "UNRESOLVED", "AMBIGUOUS"]

TargetLiveState = Literal[
    "FIELD_VALUE_CORRECT",
    "TARGET_EMPTY",
    "TARGET_INCORRECT",
    "INDETERMINATE",
]


def normalize_status_label_for_compare(label: str) -> str:
    """Normalização técnica para diagnóstico (case/acento/espaço/pontuação)."""
    normalized = unicodedata.normalize("NFKD", label.strip().casefold())
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    collapsed = re.sub(r"\s+", " ", without_accents).strip()
    return re.sub(r"[^\w\s]", "", collapsed).strip()


def _option_key(option: dict) -> str:
    return str(option["key"])


def _column_options(snapshot: SundayBoardSnapshot, sunday_column_id: str) -> list[dict]:
    for column in snapshot.columns:
        if column.id == sunday_column_id:
            return list((column.settings or {}).get("options", []))
    return []


@dataclass(frozen=True)
class StatusSourceCompareResult:
    classification: StatusSourceClassification
    option_key: str | None = None
    option_label: str | None = None
    candidate_label: str | None = None
    candidate_reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class StatusFieldDiagnosis:
    source_value: str
    semantic_key: str
    target_current: object | None
    classification: StatusSourceClassification
    resolution: StatusResolution
    option_key: str | None = None
    candidate_option: str | None = None
    target_live_state: TargetLiveState = "INDETERMINATE"
    detail: str | None = None


@dataclass
class CustomStatusCoverageReport:
    distinct_source_values: int = 0
    resolved: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    by_column: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class StatusCoverageIssue:
    monday_item_id: str
    monday_column_id: str
    field_name: str
    source_value: str
    issue: Literal["UNRESOLVED", "AMBIGUOUS"]
    detail: str


@dataclass
class StatusCoverageReport:
    ok: bool
    issues: list[StatusCoverageIssue] = field(default_factory=list)

    @property
    def detail(self) -> str:
        if self.ok:
            return "todos os custom status source resolvem para exatamente uma option live"
        sample = "; ".join(
            f"{issue.monday_item_id}/{issue.field_name}:{issue.issue}"
            for issue in self.issues[:5]
        )
        extra = len(self.issues) - min(len(self.issues), 5)
        suffix = f" (+{extra} mais)" if extra > 0 else ""
        return f"{len(self.issues)} problema(s): {sample}{suffix}"


def classify_status_source_vs_options(
    *,
    source_value: str,
    semantic_key: str,
    column_options: list[dict],
    status_mappings: dict[str, str | None],
) -> StatusSourceCompareResult:
    """Compara valor source Monday com options live Sunday (sem fuzzy automático)."""
    if not column_options:
        return StatusSourceCompareResult(
            classification="TARGET_OPTION_MISSING",
            detail=f'Sem options live para source "{source_value}".',
        )

    exact_label_matches = [
        option
        for option in column_options
        if str(option.get("label", "")).strip() == source_value.strip()
    ]
    if len(exact_label_matches) == 1:
        option = exact_label_matches[0]
        return StatusSourceCompareResult(
            classification="EXACT_OPTION",
            option_key=_option_key(option),
            option_label=str(option.get("label", "")),
        )
    if len(exact_label_matches) > 1:
        return StatusSourceCompareResult(
            classification="AMBIGUOUS",
            detail=f'Label source "{source_value}" corresponde a múltiplas options.',
        )

    normalized_source = normalize_status_label_for_compare(source_value)
    normalized_matches = [
        option
        for option in column_options
        if normalize_status_label_for_compare(str(option.get("label", ""))) == normalized_source
    ]
    if len(normalized_matches) == 1:
        option = normalized_matches[0]
        return StatusSourceCompareResult(
            classification="NORMALIZED_EXACT_OPTION",
            option_key=_option_key(option),
            option_label=str(option.get("label", "")),
        )
    if len(normalized_matches) > 1:
        return StatusSourceCompareResult(
            classification="AMBIGUOUS",
            detail=(
                f'Label source normalizado "{normalized_source}" '
                "corresponde a múltiplas options."
            ),
        )

    mapped_key = status_mappings.get(source_value)
    if mapped_key:
        try:
            resolved = resolve_sunday_custom_status_option(
                column_options=column_options,
                semantic_key=mapped_key,
                monday_label=source_value,
            )
        except StatusResolveError as exc:
            if exc.reason == "AMBIGUOUS":
                return StatusSourceCompareResult(
                    classification="AMBIGUOUS",
                    detail=exc.detail,
                )
            typo_candidates = _typo_candidates(semantic_key, column_options)
            if len(typo_candidates) == 1:
                option = typo_candidates[0]
                return StatusSourceCompareResult(
                    classification="SEMANTIC_CANDIDATE_ONLY",
                    candidate_label=str(option.get("label", "")),
                    candidate_reason=(
                        f'Mapping explícito "{mapped_key}" não resolve; '
                        f'option "{option.get("label")}" é candidata por typo/normalização.'
                    ),
                )
            return StatusSourceCompareResult(
                classification="TARGET_OPTION_MISSING",
                detail=exc.detail,
            )
        return StatusSourceCompareResult(
            classification="EXPLICIT_MAPPING_EXISTS",
            option_key=resolved.option_key,
            option_label=resolved.option_label,
            detail=f"Mapping explícito label→slug→option ({mapped_key}).",
        )

    try:
        resolve_sunday_custom_status_option(
            column_options=column_options,
            semantic_key=semantic_key,
            monday_label=source_value,
        )
    except StatusResolveError as exc:
        if exc.reason == "AMBIGUOUS":
            return StatusSourceCompareResult(
                classification="AMBIGUOUS",
                detail=exc.detail,
            )

    typo_candidates = _typo_candidates(semantic_key, column_options)
    if len(typo_candidates) == 1:
        option = typo_candidates[0]
        return StatusSourceCompareResult(
            classification="SEMANTIC_CANDIDATE_ONLY",
            candidate_label=str(option.get("label", "")),
            candidate_reason=(
                f'Label Sunday "{option.get("label")}" difere do source por typo provável '
                f'(sem match exato/normalizado com "{source_value}").'
            ),
        )

    return StatusSourceCompareResult(
        classification="TARGET_OPTION_MISSING",
        detail=f'Nenhuma option Sunday representa source "{source_value}".',
    )


def _typo_candidates(semantic_key: str, column_options: list[dict]) -> list[dict]:
    return [
        option
        for option in column_options
        if _is_single_char_prefix_typo(semantic_key, str(option.get("label", "")))
    ]


def _is_single_char_prefix_typo(semantic_key: str, option_label: str) -> bool:
    normalized_option = normalize_status_label_for_compare(option_label).replace(" ", "_")
    if normalized_option == semantic_key:
        return False
    if semantic_key.endswith(normalized_option) and len(semantic_key) - len(normalized_option) == 1:
        return True
    if normalized_option.endswith(semantic_key) and len(normalized_option) - len(semantic_key) == 1:
        return True
    return False


def classify_target_live_state(
    *,
    source_value: str,
    semantic_key: str,
    target_current: object | None,
    column_options: list[dict],
    resolved_option_key: str | None,
) -> TargetLiveState:
    if target_current is None or str(target_current).strip() == "":
        return "TARGET_EMPTY"

    actual = str(target_current)
    if resolved_option_key and actual == resolved_option_key:
        return "FIELD_VALUE_CORRECT"

    if actual == semantic_key:
        return "INDETERMINATE"

    try:
        resolved = resolve_sunday_custom_status_option(
            column_options=column_options,
            semantic_key=semantic_key,
            monday_label=source_value,
        )
        if actual == resolved.option_key:
            return "FIELD_VALUE_CORRECT"
    except StatusResolveError:
        pass

    normalized_source = normalize_status_label_for_compare(source_value)
    for option in column_options:
        if actual == _option_key(option):
            option_label = normalize_status_label_for_compare(str(option.get("label", "")))
            if option_label == normalized_source:
                return "FIELD_VALUE_CORRECT"
            return "TARGET_INCORRECT"

    if actual.startswith("opt_"):
        return "TARGET_INCORRECT"

    return "INDETERMINATE"


def diagnose_status_field(
    *,
    source_value: str,
    semantic_key: str,
    column_options: list[dict],
    status_mappings: dict[str, str | None],
    target_current: object | None,
) -> StatusFieldDiagnosis:
    compare = classify_status_source_vs_options(
        source_value=source_value,
        semantic_key=semantic_key,
        column_options=column_options,
        status_mappings=status_mappings,
    )
    resolution: StatusResolution
    if compare.classification == "AMBIGUOUS":
        resolution = "AMBIGUOUS"
    elif compare.classification in {
        "EXACT_OPTION",
        "NORMALIZED_EXACT_OPTION",
        "EXPLICIT_MAPPING_EXISTS",
    }:
        resolution = "RESOLVED"
    else:
        resolution = "UNRESOLVED"

    candidate = None
    if compare.classification == "SEMANTIC_CANDIDATE_ONLY":
        candidate = compare.candidate_label
    elif compare.option_key:
        candidate = f"{compare.option_key} ({compare.option_label})"

    target_state = classify_target_live_state(
        source_value=source_value,
        semantic_key=semantic_key,
        target_current=target_current,
        column_options=column_options,
        resolved_option_key=compare.option_key,
    )

    return StatusFieldDiagnosis(
        source_value=source_value,
        semantic_key=semantic_key,
        target_current=target_current,
        classification=compare.classification,
        resolution=resolution,
        option_key=compare.option_key,
        candidate_option=candidate,
        target_live_state=target_state,
        detail=compare.detail or compare.candidate_reason,
    )


def check_status_coverage_for_sources(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    item_ids: set[str] | None = None,
) -> StatusCoverageReport:
    """Guard pré-APPLY: cada custom status source não vazio → exatamente 1 option live."""
    column_plans = {plan.monday_column_id: plan for plan in board_plan.column_plans}
    issues: list[StatusCoverageIssue] = []

    for item_id, source in apply_sources.items():
        if item_ids is not None and item_id not in item_ids:
            continue
        for monday_column in inventory.columns:
            if monday_column.type != "status":
                continue
            source_text = source.values_by_column_id.get(monday_column.id)
            if not (source_text or "").strip():
                continue

            plan_column = column_plans.get(monday_column.id)
            if plan_column is None or not plan_column.sunday_column_id:
                continue

            expected = derive_expected_sunday_value(
                monday_column=monday_column,
                source_text=source_text,
                board_plan=board_plan,
            )
            if not isinstance(expected, str):
                continue

            options = _column_options(sunday_snapshot, plan_column.sunday_column_id)
            try:
                resolve_sunday_custom_status_option(
                    column_options=options,
                    semantic_key=expected,
                    monday_label=source_text,
                )
            except StatusResolveError as exc:
                issues.append(
                    StatusCoverageIssue(
                        monday_item_id=item_id,
                        monday_column_id=monday_column.id,
                        field_name=monday_column.title,
                        source_value=source_text,
                        issue=exc.reason,
                        detail=exc.detail,
                    ),
                )

    return StatusCoverageReport(ok=not issues, issues=issues)


def analyze_custom_status_coverage(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
) -> CustomStatusCoverageReport:
    """Análise read-only de cobertura de valores source vs options live."""
    column_plans = {plan.monday_column_id: plan for plan in board_plan.column_plans}
    report = CustomStatusCoverageReport()
    seen_values: set[tuple[str, str]] = set()

    for source in apply_sources.values():
        for monday_column in inventory.columns:
            if monday_column.type != "status":
                continue
            source_text = source.values_by_column_id.get(monday_column.id)
            if not (source_text or "").strip():
                continue

            key = (monday_column.id, source_text.strip())
            if key in seen_values:
                continue
            seen_values.add(key)

            plan_column = column_plans.get(monday_column.id)
            if plan_column is None or not plan_column.sunday_column_id:
                continue

            expected = derive_expected_sunday_value(
                monday_column=monday_column,
                source_text=source_text,
                board_plan=board_plan,
            )
            if not isinstance(expected, str):
                continue

            report.distinct_source_values += 1
            col_stats = report.by_column.setdefault(monday_column.id, {
                "distinct": 0,
                "resolved": 0,
                "unresolved": 0,
                "ambiguous": 0,
            })
            col_stats["distinct"] += 1

            options = _column_options(sunday_snapshot, plan_column.sunday_column_id)
            try:
                resolve_sunday_custom_status_option(
                    column_options=options,
                    semantic_key=expected,
                    monday_label=source_text,
                )
                report.resolved += 1
                col_stats["resolved"] += 1
            except StatusResolveError as exc:
                if exc.reason == "AMBIGUOUS":
                    report.ambiguous += 1
                    col_stats["ambiguous"] += 1
                else:
                    report.unresolved += 1
                    col_stats["unresolved"] += 1

    return report


def build_status_coverage_gate_check(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    item_ids: set[str] | None = None,
) -> tuple[bool, str]:
    report = check_status_coverage_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=apply_sources,
        item_ids=item_ids,
    )
    return report.ok, report.detail
