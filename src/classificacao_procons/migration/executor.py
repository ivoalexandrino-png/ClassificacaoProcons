"""Executor da Fase 3 (Onda 1 / Onda 2) — PLAN por padrão, APPLY fail-closed.

Consome EXCLUSIVAMENTE o plano da engine canônica (`migration.dry_run` +
`migration.disposition_rules`); não há segunda engine. APPLY exige confirmação
explícita, env, gate 100% OK e revalidação de snapshot antes da 1ª escrita.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from classificacao_procons.migration.dispositions import Disposition
from classificacao_procons.migration.dry_run import DryRunReport
from classificacao_procons.migration.mappings import (
    WAVE1_RELATION_BY_COLUMN_ID,
    WAVE1_TARGETS,
    group_rule,
)
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayItemDigest,
    MondayUpdateDigest,
)
from classificacao_procons.migration.user_mapping import (
    UserMappingPolicy,
    classify_monday_user,
)
from classificacao_procons.sunday.http import SundayConfig

ENV_ALLOW_APPLY = "SUNDAY_MIGRATION_ALLOW_APPLY"
ENV_TEST_URL = "SUNDAY_API_URL_TEST"
ENV_TEST_TOKEN = "SUNDAY_API_TOKEN_TEST"
DEFAULT_LEDGER_PATH = "docs/migration/monday-sunday-ledger.json"
LEGACY_LEDGER_PATH = "data/monday-sunday-map.json"
LEDGER_SCHEMA_VERSION = 1
LEDGER_DESCRIPTION = (
    "Ledger técnico da migração Monday→Sunday (somente IDs/metadados; sem PII/conteúdo)."
)
COMMENT_MARKER_PREFIX = "[monday-migracao:"
ATTACHMENT_MARKER_PREFIX = "monday-asset-"

#: Allowlist aprovada (Monday → Sunday). Fora dela: abort.
BOARD_ALLOWLIST: dict[str, str] = {
    "4944254220": "82",
    "3961072966": "83",
    "4443295406": "72",
    "5343921475": "84",
    "4443297481": "85",
    "5563754463": "86",
    "5301515799": "77",
    "5385471914": "87",
}


class ExecutorAbort(RuntimeError):
    """Execução abortada por regra fail-closed (nenhuma escrita realizada)."""


def sunday_config_from_test_env() -> SundayConfig:
    """Config do Sunday a partir dos aliases *_TEST (sem fallback aos originais)."""
    base_url = os.environ.get(ENV_TEST_URL, "").strip().rstrip("/")
    token = os.environ.get(ENV_TEST_TOKEN, "").strip()
    if not base_url or not token:
        raise ExecutorAbort(
            f"Secrets de teste ausentes ({ENV_TEST_URL}/{ENV_TEST_TOKEN}); "
            "sem fallback para os secrets originais.",
        )
    return SundayConfig(base_url=base_url, token=token)


def snapshot_fingerprint(inventory: MondayBoardInventory) -> str:
    """Hash estável do item e dos updates aprovados para o guard de concorrência."""
    basis = sorted(
        (
            item.item_id,
            item.updated_at or "",
            tuple(
                (
                    update.update_id,
                    update.created_at or "",
                    update.classification,
                    update.is_migratable,
                    update.exclusion_reason or "",
                )
                for update in item.update_diagnostics
            ),
        )
        for item in inventory.items
    )
    return hashlib.sha256(json.dumps(basis).encode()).hexdigest()[:24]


# ------------------------------------------------------------------- ledger IO


def _empty_ledger_payload() -> dict:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "description": LEDGER_DESCRIPTION,
        "records": {},
    }


def _read_ledger_payload(path: Path) -> dict:
    if not path.exists():
        return _empty_ledger_payload()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return _empty_ledger_payload()
    if "records" not in payload:
        payload = {"records": payload}
    payload.setdefault("schema_version", LEDGER_SCHEMA_VERSION)
    payload.setdefault("description", LEDGER_DESCRIPTION)
    return payload


def import_legacy_ledger_if_needed(
    path: str | Path = DEFAULT_LEDGER_PATH,
    *,
    legacy_path: str | Path = LEGACY_LEDGER_PATH,
) -> bool:
    """Copia records do ledger legado gitignored para o path versionado (uma vez)."""
    ledger_path = Path(path)
    if ledger_path.exists() and _read_ledger_payload(ledger_path).get("records"):
        return False
    legacy = Path(legacy_path)
    if not legacy.exists():
        return False
    legacy_records = _read_ledger_payload(legacy).get("records", {})
    if not legacy_records:
        return False
    payload = _empty_ledger_payload()
    payload["records"] = legacy_records
    payload["imported_from"] = str(legacy_path)
    payload["imported_at"] = datetime.now(UTC).isoformat()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def load_persistent_ledger(path: str | Path = DEFAULT_LEDGER_PATH) -> dict[str, dict]:
    ledger_path = Path(path)
    if ledger_path == Path(DEFAULT_LEDGER_PATH):
        import_legacy_ledger_if_needed(ledger_path)
    if not ledger_path.exists():
        return {}
    return _read_ledger_payload(ledger_path).get("records", {})


def persist_ledger_record(record: dict, path: str | Path = DEFAULT_LEDGER_PATH) -> None:
    """Grava UMA entrada confirmada (escrita atômica tmp+rename)."""
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_ledger_payload(ledger_path) if ledger_path.exists() else _empty_ledger_payload()
    records = payload.get("records", {})
    key = f"{record['monday_board_id']}:{record['monday_item_id']}"
    records[key] = record
    payload["records"] = records
    payload["updated_at"] = datetime.now(UTC).isoformat()
    tmp = ledger_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ledger_path)


# ---------------------------------------------------------------------- plano


@dataclass(frozen=True)
class RelationWrite:
    """Relação a gravar na SEGUNDA PASSADA global (após os dois lados existirem)."""

    source_monday_item_id: str
    monday_column_id: str
    target_monday_board_id: str
    target_monday_item_ids: tuple[str, ...]
    resolved_sunday_item_ids: tuple[str, ...] = ()

    @property
    def unresolved(self) -> bool:
        return len(self.resolved_sunday_item_ids) != len(self.target_monday_item_ids)


@dataclass(frozen=True)
class PlannedOperation:
    """Uma source row do escopo com tudo que o APPLY futuro fará por ela."""

    monday_item_id: str
    disposition: str
    wave: str
    action: str  # create | resume | adopt | absorb | exclude_test | already_migrated | blocked
    target_group: str | None = None
    group_action: str | None = None
    system_fields: tuple[str, ...] = ()
    owner_resolution: str = "empty_sem_owner"
    custom_values_count: int = 0
    source_updates: int = 0
    updates_migratable: int = 0
    comments_to_create: int = 0
    comments_already_present: int = 0
    update_diagnostics: tuple[MondayUpdateDigest, ...] = ()
    comments_count_exact: bool = True
    attachments_to_link: int = 0
    assets_bytes: int = 0
    subitem_count: int = 0
    adopt_sunday_item_id: str | None = None
    canonical_monday_item_id: str | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class GateCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ExecutionPlan:
    monday_board_id: str
    sunday_board_id: str
    wave: str
    mode: str
    max_items: int
    requested_item_id: str | None
    snapshot_fingerprint: str
    snapshot_total: int
    source_snapshot_timestamp: str
    requested_item_ids: tuple[str, ...] | None = None
    max_comments: int | None = None
    operations: list[PlannedOperation] = field(default_factory=list)
    relations_to_create: list[RelationWrite] = field(default_factory=list)
    relations_unresolved: list[RelationWrite] = field(default_factory=list)
    gate: list[GateCheck] = field(default_factory=list)
    scoped_safety: object | None = None
    max_writes: int | None = None

    @property
    def gate_ok(self) -> bool:
        return all(check.ok for check in self.gate)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for operation in self.operations:
            result[operation.action] = result.get(operation.action, 0) + 1
        return result

    def to_payload(self) -> dict:
        """Relatório sanitizado (ids técnicos e contagens; sem PII/conteúdo)."""
        return {
            "monday_board_id": self.monday_board_id,
            "sunday_board_id": self.sunday_board_id,
            "wave": self.wave,
            "mode": self.mode,
            "max_items": self.max_items,
            "requested_item_id": self.requested_item_id,
            "requested_item_ids": (
                list(self.requested_item_ids) if self.requested_item_ids else None
            ),
            "max_comments": self.max_comments,
            "source_scope": len(self.operations),
            "snapshot": {
                "fingerprint": self.snapshot_fingerprint,
                "total": self.snapshot_total,
                "timestamp": self.source_snapshot_timestamp,
            },
            "counts": self.counts(),
            "source_updates": sum(op.source_updates for op in self.operations),
            "updates_migraveis": sum(op.updates_migratable for op in self.operations),
            "comments_to_create": sum(op.comments_to_create for op in self.operations),
            "comments_already_present": sum(
                op.comments_already_present for op in self.operations
            ),
            "comments_excluded": sum(
                not update.is_migratable
                for op in self.operations
                for update in op.update_diagnostics
            ),
            "comments_count_exact": all(
                op.comments_count_exact for op in self.operations
            ),
            "attachments_to_link": sum(op.attachments_to_link for op in self.operations),
            "assets_bytes_estimated": sum(op.assets_bytes for op in self.operations),
            "relations_to_create": len(self.relations_to_create),
            "relations_unresolved": len(self.relations_unresolved),
            "gate": [
                {"check": check.name, "ok": check.ok, "detail": check.detail}
                for check in self.gate
            ],
            "gate_ok": self.gate_ok,
            "max_writes": self.max_writes,
            "scoped_safety": (
                self.scoped_safety.as_dict()
                if self.scoped_safety is not None and hasattr(self.scoped_safety, "as_dict")
                else None
            ),
            "operation_accounting": (
                self.scoped_safety.accounting.as_dict()
                if self.scoped_safety is not None and hasattr(self.scoped_safety, "accounting")
                else None
            ),
            "operations": [
                {
                    "monday_item_id": op.monday_item_id,
                    "disposition": op.disposition,
                    "action": op.action,
                    "target_group": op.target_group,
                    "group_action": op.group_action,
                    "system_fields": list(op.system_fields),
                    "owner_resolution": op.owner_resolution,
                    "custom_values": op.custom_values_count,
                    "source_updates": op.source_updates,
                    "updates_migraveis": op.updates_migratable,
                    "comments": op.comments_to_create,
                    "comments_already_present": op.comments_already_present,
                    "updates": [
                        {
                            "update_id": update.update_id,
                            "created_at": update.created_at,
                            "has_author": update.has_author,
                            "classification": update.classification,
                            "migratable": update.is_migratable,
                            "exclusion_reason": update.exclusion_reason,
                        }
                        for update in op.update_diagnostics
                    ],
                    "comments_count_exact": op.comments_count_exact,
                    "attachments": op.attachments_to_link,
                    "subitems": op.subitem_count,
                    "adopt_sunday_item_id": op.adopt_sunday_item_id,
                    "canonical_monday_item_id": op.canonical_monday_item_id,
                    "blocked_reason": op.blocked_reason,
                }
                for op in self.operations
            ],
        }


def _owner_resolution(item: MondayItemDigest, policy: UserMappingPolicy | None) -> str:
    if not item.people_ids:
        return "empty_sem_owner"
    if policy is None:
        return "blocked_sem_politica"
    tiers = {classify_monday_user(person, policy) for person in item.people_ids}
    if "unknown" in tiers:
        return "blocked_novo_sem_match"  # usuário ativo NOVO: abortar item (MANUAL)
    if "exact" in tiers:
        return "set_match_exato"
    if "active_unmatched" in tiers:
        return "empty_sem_match_aprovado"
    return "empty_desativado"


def _wave_label(wave: int) -> str:
    return f"WAVE_{wave}"


def _resolve_requested_item_ids(
    *,
    item_id: str | None,
    item_ids: frozenset[str] | None,
) -> frozenset[str] | None:
    """Normaliza allowlist explícita (--item-id ou --item-ids)."""
    if item_id is not None and item_ids is not None:
        raise ExecutorAbort("Use item_id ou item_ids, não ambos.")
    if item_ids is not None:
        normalized = frozenset(str(value).strip() for value in item_ids if str(value).strip())
        if not normalized:
            raise ExecutorAbort("item_ids vazio.")
        return normalized
    if item_id is not None:
        requested_item_id = str(item_id).strip()
        if not requested_item_id:
            raise ExecutorAbort("item_id vazio.")
        return frozenset({requested_item_id})
    return None


def _validate_requested_item_scope(
    *,
    board_id: str,
    wave_label: str,
    inventory: MondayBoardInventory,
    report: DryRunReport,
    requested_item_ids: frozenset[str],
) -> None:
    """Garante que cada ID autorizado existe no board e na wave."""
    for requested in sorted(requested_item_ids):
        inventory_matches = [
            item for item in inventory.items if item.item_id == requested
        ]
        if len(inventory_matches) != 1:
            raise ExecutorAbort(
                f"item_id {requested} deve ocorrer exatamente uma vez no board "
                f"{board_id}; encontrados {len(inventory_matches)}.",
            )
        wave_matches = [
            result
            for result in report.items
            if result.monday_board_id == board_id
            and result.monday_item_id == requested
            and result.wave == wave_label
        ]
        if len(wave_matches) != 1:
            raise ExecutorAbort(
                f"item_id {requested} deve pertencer exatamente uma vez a "
                f"{board_id}/{wave_label}; encontrados {len(wave_matches)}.",
            )


def build_execution_plan(
    *,
    inventory: MondayBoardInventory,
    report: DryRunReport,
    wave: int,
    max_items: int,
    item_id: str | None = None,
    item_ids: frozenset[str] | None = None,
    max_comments: int | None = None,
    mode: str = "plan",
    user_policy: UserMappingPolicy | None = None,
    persistent_ledger: dict[str, dict] | None = None,
    sunday_monday_id_index: dict[str, str] | None = None,
    sunday_comment_markers: dict[str, set[str]] | None = None,
    sunday_schema_checks: list[GateCheck] | None = None,
    source_completeness_check: GateCheck | None = None,
) -> ExecutionPlan:
    """Monta o plano executável a partir do dry-run canônico (zero escrita)."""
    board_id = inventory.board_id
    if board_id not in BOARD_ALLOWLIST:
        raise ExecutorAbort(f"Board {board_id} fora da allowlist aprovada.")
    sunday_board_id = BOARD_ALLOWLIST[board_id]
    expected_target = WAVE1_TARGETS.get(board_id, (None,))[0]
    if expected_target != sunday_board_id:
        raise ExecutorAbort(
            f"Allowlist divergente do mapping canônico para {board_id}: "
            f"{sunday_board_id} != {expected_target}.",
        )

    wave_label = _wave_label(wave)
    requested_item_ids = _resolve_requested_item_ids(item_id=item_id, item_ids=item_ids)
    requested_item_id = (
        next(iter(requested_item_ids)) if requested_item_ids and len(requested_item_ids) == 1
        else None
    )
    if requested_item_ids is not None:
        _validate_requested_item_scope(
            board_id=board_id,
            wave_label=wave_label,
            inventory=inventory,
            report=report,
            requested_item_ids=requested_item_ids,
        )
    ledger = persistent_ledger or {}
    monday_id_index = sunday_monday_id_index or {}
    existing_markers = sunday_comment_markers or {}
    items_by_id = {item.item_id: item for item in inventory.items}
    dispositions = {
        (entry.monday_board_id, entry.monday_item_id): entry
        for run in report.disposition_runs.values()
        for entry in run.ledger.entries
    }

    operations: list[PlannedOperation] = []
    relations: list[RelationWrite] = []
    for result in report.items:
        if result.monday_board_id != board_id or result.wave != wave_label:
            continue
        if requested_item_ids is not None and result.monday_item_id not in requested_item_ids:
            continue
        item = items_by_id.get(result.monday_item_id)
        if item is None:
            continue
        entry = dispositions.get((board_id, result.monday_item_id))
        disposition = (entry.disposition if entry else result.disposition) or (
            Disposition.CREATE
        )
        group_title = inventory.groups.get(item.group_id or "")
        rule = group_rule(board_id, group_title)
        owner = _owner_resolution(item, user_policy)

        blocked: str | None = None
        if result.classification == "ERROR" or disposition is Disposition.ERROR:
            blocked = "ERROR_no_dry_run"
        elif result.classification == "MANUAL" or disposition is Disposition.MANUAL:
            blocked = "MANUAL: " + ",".join(result.reasons)
        elif rule is None:
            blocked = "grupo_sem_regra_explicita"
        elif owner.startswith("blocked"):
            blocked = owner

        ledger_key = f"{board_id}:{result.monday_item_id}"
        already = ledger.get(ledger_key, {}).get("migration_status") == "migrated"
        existing_without_ledger = result.monday_item_id in monday_id_index

        if blocked:
            action = "blocked"
        elif already:
            action = "already_migrated"  # idempotência: nunca recriar
        elif existing_without_ledger and disposition is Disposition.CREATE:
            action = "resume"
        elif disposition is Disposition.ADOPT:
            action = "adopt"
        elif disposition is Disposition.ABSORB:
            action = "absorb"
        elif disposition is Disposition.EXCLUDE_TEST:
            action = "exclude_test"
        else:
            action = "create"

        system_fields = ["name", "monday_id"]
        if item.created_at:
            system_fields.append("status_sistema(derivado)")
        update_diagnostics = (
            item.update_diagnostics if action in ("create", "resume") else ()
        )
        migratable_updates = tuple(
            update for update in update_diagnostics if update.is_migratable
        )
        item_markers = existing_markers.get(result.monday_item_id, set())
        already_present = sum(
            comment_idempotency_marker(result.monday_item_id, update.update_id)
            in item_markers
            for update in migratable_updates
        )
        operations.append(
            PlannedOperation(
                monday_item_id=result.monday_item_id,
                disposition=str(disposition),
                wave=wave_label,
                action=action,
                target_group=(
                    group_title
                    if rule and rule[0] == "preservar"
                    else "Itens" if rule else None
                ),
                group_action=rule[0] if rule else None,
                system_fields=tuple(system_fields),
                owner_resolution=owner,
                custom_values_count=len(item.status_labels) + len(item.relation_targets),
                source_updates=len(update_diagnostics),
                updates_migratable=len(migratable_updates),
                comments_to_create=len(migratable_updates) - already_present,
                comments_already_present=already_present,
                update_diagnostics=update_diagnostics,
                comments_count_exact=(
                    (
                        item.updates_count_is_exact
                        and (
                            not item.has_updates
                            or bool(item.update_diagnostics)
                        )
                    )
                    if action in ("create", "resume")
                    else True
                ),
                attachments_to_link=item.file_count,
                assets_bytes=item.file_bytes,
                subitem_count=item.subitem_count,
                adopt_sunday_item_id=entry.sunday_item_id if entry else None,
                canonical_monday_item_id=(
                    entry.canonical_monday_item_id if entry else None
                ),
                blocked_reason=blocked,
            ),
        )
        for column_id, targets in item.relation_targets.items():
            target_board = WAVE1_RELATION_BY_COLUMN_ID.get((board_id, column_id))
            if not target_board:
                continue
            resolved = tuple(
                str(ledger[f"{target_board}:{target}"]["sunday_item_id"])
                for target in targets
                if ledger.get(f"{target_board}:{target}", {}).get("sunday_item_id")
            )
            write = RelationWrite(
                source_monday_item_id=result.monday_item_id,
                monday_column_id=column_id,
                target_monday_board_id=target_board,
                target_monday_item_ids=targets,
                resolved_sunday_item_ids=resolved,
            )
            relations.append(write)

    if requested_item_ids is not None:
        planned_ids = {operation.monday_item_id for operation in operations}
        missing_ids = requested_item_ids - planned_ids
        if missing_ids:
            raise ExecutorAbort(
                "item_ids ausentes no escopo do plano: "
                + ", ".join(sorted(missing_ids)),
            )
        extra_ids = planned_ids - requested_item_ids
        if extra_ids:
            raise ExecutorAbort(
                "item_ids extras no escopo do plano: "
                + ", ".join(sorted(extra_ids)),
            )
        for operation in operations:
            if operation.action not in ("create", "resume", "already_migrated"):
                raise ExecutorAbort(
                    f"item {operation.monday_item_id} action={operation.action} "
                    "no escopo autorizado.",
                )

    if max_comments is not None:
        total_comments = sum(operation.comments_to_create for operation in operations)
        if total_comments != max_comments:
            raise ExecutorAbort(
                f"comments_to_create {total_comments} != max_comments {max_comments}.",
            )

    plan = ExecutionPlan(
        monday_board_id=board_id,
        sunday_board_id=sunday_board_id,
        wave=wave_label,
        mode=mode,
        max_items=max_items,
        requested_item_id=requested_item_id,
        requested_item_ids=tuple(sorted(requested_item_ids)) if requested_item_ids else None,
        max_comments=max_comments,
        snapshot_fingerprint=snapshot_fingerprint(inventory),
        snapshot_total=len(inventory.items),
        source_snapshot_timestamp=report.source_snapshot_timestamp,
        operations=operations,
        relations_to_create=[write for write in relations if not write.unresolved],
        relations_unresolved=[write for write in relations if write.unresolved],
    )
    plan.gate = _build_gate(plan, sunday_schema_checks or [])
    if source_completeness_check is not None:
        plan.gate.append(source_completeness_check)
    return plan


def _build_gate(plan: ExecutionPlan, schema_checks: list[GateCheck]) -> list[GateCheck]:
    """Gate fail-closed: TODA checagem precisa passar antes de qualquer escrita."""
    counts = plan.counts()
    blocked = counts.get("blocked", 0)
    writable = sum(
        count for action, count in counts.items() if action not in ("already_migrated",)
    )
    checks = [
        GateCheck(
            "board_allowlist",
            plan.monday_board_id in BOARD_ALLOWLIST,
            f"{plan.monday_board_id} → {plan.sunday_board_id}",
        ),
        GateCheck(
            "max_items",
            writable <= plan.max_items,
            f"{writable} operações ≤ limite {plan.max_items}",
        ),
        GateCheck("sem_bloqueios", blocked == 0, f"{blocked} itens bloqueados"),
        GateCheck(
            "relations_resolvidas",
            not plan.relations_unresolved,
            f"{len(plan.relations_unresolved)} relações sem sunday_item_id (2ª passada)",
        ),
        GateCheck(
            "snapshot_valido",
            bool(plan.snapshot_fingerprint)
            and plan.snapshot_total > 0
            and all(operation.comments_count_exact for operation in plan.operations),
            (
                f"board_global {plan.snapshot_fingerprint} / {plan.snapshot_total} rows; "
                "updates exatos"
                if all(operation.comments_count_exact for operation in plan.operations)
                else "snapshot legado sem IDs exatos de updates"
            ),
        ),
    ]
    if plan.scoped_safety is not None:
        scoped = plan.scoped_safety
        checks.append(
            GateCheck(
                "selected_source_fingerprint",
                bool(getattr(scoped, "selected_source_fingerprint", "")),
                getattr(scoped, "selected_source_fingerprint", ""),
            ),
        )
        checks.append(
            GateCheck(
                "migration_schema_fingerprint",
                bool(getattr(scoped, "migration_schema_fingerprint", "")),
                getattr(scoped, "migration_schema_fingerprint", ""),
            ),
        )
        checks.append(
            GateCheck(
                "operation_manifest_hash",
                bool(getattr(scoped, "operation_manifest_hash", "")),
                getattr(scoped, "operation_manifest_hash", ""),
            ),
        )
        accounting = getattr(scoped, "accounting", None)
        if accounting is not None and plan.max_writes is not None:
            checks.append(
                GateCheck(
                    "max_writes",
                    accounting.operation_total == plan.max_writes,
                    (
                        f"{accounting.operation_total} operações técnicas "
                        f"== limite {plan.max_writes}"
                    ),
                ),
            )
    if schema_checks:
        checks.extend(schema_checks)
    else:
        checks.append(
            GateCheck(
                "schema_live_verificado",
                False,
                "schema do Sunday não verificado nesta execução (leitura live pendente)",
            ),
        )
    return checks


def build_sunday_schema_checks(
    *,
    sunday_board_id: str,
    columns: list,
    groups: dict[str, str],
    expected_groups: tuple[str, ...] = (),
) -> list[GateCheck]:
    """Checagens de schema a partir de uma leitura live/snapshot do board destino."""
    labels = {str(getattr(column, "label", "")).strip().lower() for column in columns}
    checks = [
        GateCheck(
            "monday_id_presente",
            "monday id" in labels,
            f"colunas no board {sunday_board_id}: {len(labels)}",
        ),
    ]
    if expected_groups:
        existing = {name.strip().lower() for name in groups.values()}
        missing = [name for name in expected_groups if name.strip().lower() not in existing]
        checks.append(
            GateCheck(
                "groups_esperados",
                not missing,
                "faltando: " + ", ".join(missing) if missing else "todos presentes",
            ),
        )
    return checks


# ---------------------------------------------------------------------- apply


@dataclass
class ApplyReport:
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    not_attempted: list[str] = field(default_factory=list)
    write_stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplyMigrationContext:
    """Contexto opcional para APPLY real (campos mapeados + verificação por item)."""

    inventory: MondayBoardInventory
    board_plan: object
    sunday_snapshot: object
    apply_sources: dict[str, object]
    monday_id_column_id: str
    target_group_id: str


def apply_plan(
    plan: ExecutionPlan,
    *,
    client,
    confirm_writes: bool = False,
    snapshot_revalidator: Callable[[], str] | None = None,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    fail_fast: bool = True,
    migration_context: ApplyMigrationContext | None = None,
    now: Callable[[], str] = lambda: datetime.now(UTC).isoformat(),
) -> ApplyReport:
    """Executa o plano. Fail-closed: aborta antes da 1ª escrita se gate/snapshot falhar."""
    if plan.mode != "apply":
        raise ExecutorAbort("Plano não foi gerado em modo apply (default é plan).")
    if not confirm_writes:
        raise ExecutorAbort("APPLY exige confirm_writes=True explícito.")
    if os.environ.get(ENV_ALLOW_APPLY) != "1":
        raise ExecutorAbort(f"APPLY exige {ENV_ALLOW_APPLY}=1 no ambiente.")
    if not plan.gate_ok:
        failing = [check.name for check in plan.gate if not check.ok]
        raise ExecutorAbort(f"Gate fail-closed reprovado: {', '.join(failing)}.")
    if snapshot_revalidator is None:
        raise ExecutorAbort("APPLY exige revalidação de snapshot (concorrência).")
    if plan.scoped_safety is not None:
        from classificacao_procons.migration.operation_manifest import (
            validate_scoped_apply_fingerprints,
        )

        current_scoped = snapshot_revalidator()
        if not hasattr(current_scoped, "selected_source_fingerprint"):
            raise ExecutorAbort(
                "APPLY escopado exige revalidador que retorne ScopedSafetyMetadata.",
            )
        failures = validate_scoped_apply_fingerprints(
            approved=plan.scoped_safety,
            current=current_scoped,
        )
        if failures:
            raise ExecutorAbort(
                "Scoped safety reprovado: " + "; ".join(failures),
            )
        if plan.max_writes is not None and (
            current_scoped.accounting.operation_total != plan.max_writes
        ):
            raise ExecutorAbort(
                f"operation_total {current_scoped.accounting.operation_total} "
                f"!= max_writes {plan.max_writes}.",
            )
    else:
        current = snapshot_revalidator()
        if not isinstance(current, str):
            raise ExecutorAbort(
                "Revalidador legado deve retornar fingerprint global (str).",
            )
        if current != plan.snapshot_fingerprint:
            raise ExecutorAbort(
                "Snapshot do Monday mudou desde o PLAN aprovado "
                f"({current} != {plan.snapshot_fingerprint}); gere novo PLAN.",
            )

    report = ApplyReport()
    write_stats = None
    if migration_context is not None:
        from classificacao_procons.migration.apply_writer import (
            ApplyWriteStats,
            apply_create_item,
            build_sunday_monday_id_index,
            migrate_monday_updates,
        )

        write_stats = ApplyWriteStats()

    pending = list(plan.operations)
    for index, operation in enumerate(pending):
        if operation.action == "already_migrated":
            continue
        if operation.action in ("exclude_test", "absorb"):
            # absorb/exclude registram ledger sem criar item Sunday.
            _record_ledger(plan, operation, sunday_item_id=None, ledger_path=ledger_path,
                           now=now)
            report.succeeded.append(operation.monday_item_id)
            continue
        if operation.action == "blocked":
            report.not_attempted.append(operation.monday_item_id)
            if fail_fast:
                report.not_attempted.extend(
                    op.monday_item_id for op in pending[index + 1:]
                )
                break
            continue
        try:
            if migration_context is not None and operation.action in ("create", "resume"):
                live_index = build_sunday_monday_id_index(
                    client,
                    board_id=plan.sunday_board_id,
                    monday_id_column_id=migration_context.monday_id_column_id,
                )
                ledger_key = f"{plan.monday_board_id}:{operation.monday_item_id}"
                if load_persistent_ledger(ledger_path).get(ledger_key, {}).get(
                    "migration_status",
                ) == "migrated":
                    report.succeeded.append(operation.monday_item_id)
                    continue
                apply_source = migration_context.apply_sources.get(operation.monday_item_id)
                if apply_source is None:
                    raise RuntimeError(
                        f"Source Monday ausente para item {operation.monday_item_id}.",
                    )
                sunday_item_id = live_index.get(operation.monday_item_id)
                if sunday_item_id:
                    migrate_monday_updates(
                        client=client,
                        sunday_item_id=sunday_item_id,
                        monday_item_id=operation.monday_item_id,
                        updates=apply_source.updates,
                        expected_update_ids=tuple(
                            update.update_id
                            for update in operation.update_diagnostics
                            if update.is_migratable
                        ),
                        stats=write_stats,
                    )
                else:
                    if operation.action == "resume":
                        raise RuntimeError(
                            f"Item Sunday esperado para retomada de "
                            f"{operation.monday_item_id} não foi encontrado.",
                        )
                    sunday_item_id = apply_create_item(
                        client=client,
                        plan=plan,
                        operation=operation,
                        inventory=migration_context.inventory,
                        board_plan=migration_context.board_plan,
                        sunday_snapshot=migration_context.sunday_snapshot,
                        apply_source=apply_source,
                        monday_id_column_id=migration_context.monday_id_column_id,
                        target_group_id=migration_context.target_group_id,
                        stats=write_stats,
                    )
            elif operation.action == "adopt":
                sunday_item_id = operation.adopt_sunday_item_id
                if not sunday_item_id:
                    raise ExecutorAbort(
                        f"ADOPT sem sunday_item_id ({operation.monday_item_id}) — "
                        "nunca degradar para CREATE.",
                    )
            else:  # create (modo teste/mock) ou adopt já resolvido acima
                if operation.action == "create" and migration_context is None:
                    created = client.create_item(
                        plan.sunday_board_id,
                        f"[migracao] {operation.monday_item_id}",
                    )
                    sunday_item_id = created.id
                elif operation.action == "adopt":
                    pass  # sunday_item_id já definido
                else:
                    raise RuntimeError(f"Ação não suportada: {operation.action}")
            _record_ledger(
                plan, operation, sunday_item_id=sunday_item_id,
                ledger_path=ledger_path, now=now,
            )
            report.succeeded.append(operation.monday_item_id)
        except ExecutorAbort:
            raise
        except Exception as exc:  # noqa: BLE001 — falha isolada não duplica anteriores
            report.failed.append((operation.monday_item_id, str(exc)[:200]))
            if fail_fast:
                report.not_attempted.extend(
                    op.monday_item_id for op in pending[index + 1:]
                )
                break
    if write_stats is not None:
        report.write_stats = {
            "items_created": write_stats.items_created,
            "system_fields": write_stats.system_fields,
            "custom_values": write_stats.custom_values,
            "status": write_stats.status_writes,
            "comments": write_stats.comments,
            "comments_skipped": write_stats.comments_skipped,
            "attachments": write_stats.attachments,
            "relations": write_stats.relations,
            "subitems": write_stats.subitems,
        }
    return report


def _record_ledger(
    plan: ExecutionPlan,
    operation: PlannedOperation,
    *,
    sunday_item_id: str | None,
    ledger_path: str | Path,
    now: Callable[[], str],
) -> None:
    persist_ledger_record(
        {
            "monday_board_id": plan.monday_board_id,
            "monday_item_id": operation.monday_item_id,
            "sunday_board_id": plan.sunday_board_id,
            "sunday_item_id": sunday_item_id,
            "wave": operation.wave,
            "disposition": operation.disposition,
            "canonical_monday_item_id": operation.canonical_monday_item_id,
            "reason": operation.blocked_reason,
            "migration_status": "migrated",
            "migrated_at": now(),
            "source_snapshot_timestamp": plan.source_snapshot_timestamp,
        },
        path=ledger_path,
    )


def comment_idempotency_marker(monday_item_id: str, update_id: str) -> str:
    """Marcador embutido no corpo do comment para evitar duplicação."""
    return f"{COMMENT_MARKER_PREFIX}{monday_item_id}:{update_id}]"


def attachment_idempotency_name(asset_id: str, filename: str | None = None) -> str:
    """Nome determinístico do anexo (idempotência por listagem)."""
    suffix = f"-{filename}" if filename else ""
    return f"{ATTACHMENT_MARKER_PREFIX}{asset_id}{suffix}"
