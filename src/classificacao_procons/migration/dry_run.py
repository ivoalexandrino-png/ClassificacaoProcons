"""Motor de dry-run da migração Monday → Sunday (SEM escrita).

Escopo definitivo (decisão do usuário, 2026-08-12): **migração total em duas
ondas** — nenhum item é descartado. Classificações:

- `WAVE_1_READY`: item da Onda 1 (cutover operacional: abertos + 12 meses +
  pull-ins + boards integrais aprovados) pronto para migração automática;
- `WAVE_2_HISTORICAL`: item obrigatório da Onda 2 (backfill histórico), com
  reason `HISTORICAL_BACKFILL` — nunca descarte definitivo;
- `MANUAL` / `ERROR`: bloqueios reais (em qualquer onda).

Cenários: `estado_atual` (Sunday como está) e `pos_checklist` (schema/checklist
prontos). O relatório agregado é sanitizado: ids técnicos, contagens, motivos e
percentuais — nunca conteúdo de itens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from classificacao_procons.migration.accounting import SourceAccounting
from classificacao_procons.migration.board_disposition import (
    BoardDispositionDryRun,
    MondaySourceRow,
    run_board_disposition_dry_run,
)
from classificacao_procons.migration.disposition_rules import board_disposition_rules
from classificacao_procons.migration.dispositions import ALL_DISPOSITIONS, Disposition
from classificacao_procons.migration.mappings import (
    WAVE1_DOMAINS,
    WAVE1_FULL_BOARDS,
    build_board_plan,
    find_main_status_column,
    group_rule,
    item_is_concluded,
    sunday_board_by_monday_map,
    validate_wave1_targets,
)
from classificacao_procons.migration.models import (
    BoardPlan,
    Classification,
    ItemDryRunResult,
    ManualReason,
    MondayBoardInventory,
    MondayItemDigest,
    SundayBoardSnapshot,
)
from classificacao_procons.migration.user_mapping import (
    UserMappingPolicy,
    people_assignment_requires_manual,
)

RECORTE_MONTHS = 12


@dataclass(frozen=True)
class BoardDryRunStats:
    """Estatísticas agregadas por board (wave + disposição)."""

    monday_board_id: str
    board_name: str
    sunday_board_id: str | None
    source_total: int
    wave_1: int
    wave_2: int
    dispositions: dict[str, int]
    sunday_native: int = 0

    def as_row(self) -> dict[str, object]:
        return {
            "board": self.board_name,
            "monday_board_id": self.monday_board_id,
            "sunday_board_id": self.sunday_board_id,
            "source_total": self.source_total,
            "WAVE_1": self.wave_1,
            "WAVE_2": self.wave_2,
            **{d.value: self.dispositions.get(d.value, 0) for d in ALL_DISPOSITIONS},
            "SUNDAY_NATIVE": self.sunday_native,
        }


@dataclass
class DryRunReport:
    cutoff_iso: str
    scenario: str
    items: list[ItemDryRunResult] = field(default_factory=list)
    source_snapshot_timestamp: str = ""
    source_snapshot_total: int = 0
    source_count_by_board: dict[str, int] = field(default_factory=dict)
    board_stats: list[BoardDryRunStats] = field(default_factory=list)
    sunday_native_total: int = 0
    disposition_runs: dict[str, BoardDispositionDryRun] = field(default_factory=dict)

    def counts(self) -> dict[Classification, int]:
        result: dict[Classification, int] = {
            "WAVE_1_READY": 0,
            "WAVE_2_HISTORICAL": 0,
            "MANUAL": 0,
            "ERROR": 0,
        }
        for item in self.items:
            result[item.classification] += 1
        return result

    def manual_by_reason(self) -> dict[ManualReason, int]:
        result: dict[ManualReason, int] = {}
        for item in self.items:
            if item.classification != "MANUAL":
                continue
            for reason in item.reasons:
                result[reason] = result.get(reason, 0) + 1
        return result

    def by_board(self) -> dict[str, dict[Classification, int]]:
        result: dict[str, dict[Classification, int]] = {}
        for item in self.items:
            board = result.setdefault(
                item.monday_board_id,
                {"WAVE_1_READY": 0, "WAVE_2_HISTORICAL": 0, "MANUAL": 0, "ERROR": 0},
            )
            board[item.classification] += 1
        return result

    def flags_count(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            for flag in item.flags:
                result[flag] = result.get(flag, 0) + 1
        return result

    def disposition_counts(self) -> dict[Disposition, int]:
        counts: dict[Disposition, int] = {d: 0 for d in ALL_DISPOSITIONS}
        for item in self.items:
            if item.disposition is not None:
                counts[item.disposition] += 1
        return counts

    def source_accounting(self) -> SourceAccounting:
        counts: dict[Disposition, int] = {disposition: 0 for disposition in ALL_DISPOSITIONS}
        for item in self.items:
            if item.disposition is not None:
                counts[item.disposition] += 1
        return SourceAccounting(
            source_snapshot_timestamp=self.source_snapshot_timestamp,
            source_snapshot_total=self.source_snapshot_total,
            counts=counts,
            sunday_native_count=self.sunday_native_total,
        )

    def build_board_stats(self) -> list[BoardDryRunStats]:
        stats: list[BoardDryRunStats] = []
        for board_id, count in self.source_count_by_board.items():
            board_items = [item for item in self.items if item.monday_board_id == board_id]
            disp_counts: dict[str, int] = {d.value: 0 for d in ALL_DISPOSITIONS}
            for item in board_items:
                if item.disposition is not None:
                    disp_counts[item.disposition.value] += 1
            meta = WAVE1_DOMAINS.get(board_id, {"name": board_id})
            sunday_id = sunday_board_by_monday_map().get(board_id)
            native = 0
            if board_id in self.disposition_runs:
                native = len(self.disposition_runs[board_id].ledger.natives)
            stats.append(
                BoardDryRunStats(
                    monday_board_id=board_id,
                    board_name=meta["name"],
                    sunday_board_id=sunday_id,
                    source_total=count,
                    wave_1=sum(1 for item in board_items if item.wave == "WAVE_1"),
                    wave_2=sum(1 for item in board_items if item.wave == "WAVE_2"),
                    dispositions=disp_counts,
                    sunday_native=native,
                ),
            )
        return stats

    def to_payload(self) -> dict:
        """Relatório agregado sanitizado (sem conteúdo de itens).

        Escopo total = Onda 1 + Onda 2: itens `WAVE_2_HISTORICAL` são
        contabilizados como OBRIGATÓRIOS para a Onda 2 (backfill), nunca como
        descarte. Percentuais de prontidão são calculados sobre a Onda 1.
        """
        counts = self.counts()
        total = sum(counts.values())
        onda1 = counts["WAVE_1_READY"] + counts["MANUAL"] + counts["ERROR"]
        accounting = self.source_accounting()
        return {
            "scenario": self.scenario,
            "cutoff": self.cutoff_iso,
            "total_analisado": total,
            "onda1_total": onda1,
            "onda2_backfill_obrigatorio": counts["WAVE_2_HISTORICAL"],
            "meta_final": f"{total}/{total} itens no Sunday (duas ondas)",
            "counts": counts,
            "dispositions": {d.value: accounting.counts.get(d, 0) for d in ALL_DISPOSITIONS},
            "source_accounting": accounting.as_dict(),
            "source_count_by_board": self.source_count_by_board,
            "board_stats": [row.as_row() for row in self.build_board_stats()],
            "sunday_native_total": self.sunday_native_total,
            "percentuais_sobre_onda1": {
                key: (round(100 * value / onda1, 1) if onda1 else 0.0)
                for key, value in counts.items()
                if key != "WAVE_2_HISTORICAL"
            },
            "manual_por_motivo": self.manual_by_reason(),
            "por_board": self.by_board(),
            "flags": self.flags_count(),
        }


def default_cutoff(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(UTC)
    return moment - timedelta(days=365)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def select_recorte(
    inventory: MondayBoardInventory,
    *,
    cutoff: datetime,
) -> tuple[set[str], dict[str, bool]]:
    """Seleciona a ONDA 1 (cutover operacional): abertos + últimos 12 meses.

    Boards em `WAVE1_FULL_BOARDS` (exceções aprovadas, ex.: KPI) entram
    integralmente. O que fica de fora NÃO é descartado: é Onda 2 (backfill
    histórico obrigatório). Depois o chamador expande com os alvos de relação
    (pull-in). Retorna (ids na Onda 1, mapa id→concluído).
    """
    main_status = find_main_status_column(inventory)
    concluded: dict[str, bool] = {}
    selected: set[str] = set()
    full_board = inventory.board_id in WAVE1_FULL_BOARDS
    for item in inventory.items:
        group_title = inventory.groups.get(item.group_id or "")
        is_done = item_is_concluded(
            group_title=group_title,
            status_labels=item.status_labels,
            main_status_column_id=main_status,
        )
        concluded[item.item_id] = is_done
        created = _parse_iso(item.created_at)
        recent = created is not None and created >= cutoff
        if full_board or not is_done or recent:
            selected.add(item.item_id)
    return selected, concluded


def expand_with_relation_targets(
    selections: dict[str, set[str]],
    inventories: dict[str, MondayBoardInventory],
    plans: dict[str, BoardPlan],
) -> dict[str, int]:
    """Puxa para o recorte os alvos de relações de itens selecionados (pull-in).

    Retorna contagem de itens puxados por board de destino da relação.
    """
    pulled: dict[str, int] = {}
    for board_id, plan in plans.items():
        inventory = inventories[board_id]
        relation_target_board = {
            relation.monday_column_id: relation.monday_target_board_id
            for relation in plan.relation_plans
            if relation.monday_target_board_id
        }
        if not relation_target_board:
            continue
        selected = selections[board_id]
        for item in inventory.items:
            if item.item_id not in selected:
                continue
            for column_id, targets in item.relation_targets.items():
                target_board = relation_target_board.get(column_id)
                if not target_board or target_board not in selections:
                    continue
                target_ids = {
                    candidate.item_id for candidate in inventories[target_board].items
                }
                for target in targets:
                    if target in target_ids and target not in selections[target_board]:
                        selections[target_board].add(target)
                        pulled[target_board] = pulled.get(target_board, 0) + 1
    return pulled


def classify_item(
    item: MondayItemDigest,
    *,
    plan: BoardPlan,
    in_recorte: bool,
    scenario: str,
    known_target_items: dict[str, set[str]],
    users_mapped: set[str] | None = None,
    user_policy: UserMappingPolicy | None = None,
    group_title: str | None = None,
) -> ItemDryRunResult:
    """Classifica um item (sanitizado) num cenário do dry-run."""
    # Grupo sem regra explícita = ERROR em QUALQUER onda (nunca fallback
    # silencioso para Itens) — preflight item 3.
    if group_rule(plan.monday_board_id, group_title) is None:
        return ItemDryRunResult(
            monday_board_id=plan.monday_board_id,
            monday_item_id=item.item_id,
            classification="ERROR",
            reasons=("OTHER",),
            flags=("grupo_sem_regra_explicita",),
            wave="WAVE_1" if in_recorte else "WAVE_2",
        )
    if not in_recorte:
        # Fora da Onda 1 ≠ descarte: backfill histórico OBRIGATÓRIO na Onda 2.
        return ItemDryRunResult(
            monday_board_id=plan.monday_board_id,
            monday_item_id=item.item_id,
            classification="WAVE_2_HISTORICAL",
            reasons=("HISTORICAL_BACKFILL",),
            wave="WAVE_2",
        )
    reasons: list[ManualReason] = []
    flags: list[str] = []
    error = False

    if scenario == "estado_atual":
        if plan.sunday_board_id is None:
            reasons.append("MISSING_TARGET_COLUMN")
            flags.append("board_destino_inexistente")
        else:
            column_gap = any(
                not plan_column.exists_in_target
                and plan_column.strategy in ("direto", "transformacao")
                for plan_column in plan.column_plans
            )
            if column_gap:
                reasons.append("MISSING_TARGET_COLUMN")
        for relation in plan.relation_plans:
            if relation.monday_target_board_id and relation.config_ok is not True:
                if item.relation_targets.get(relation.monday_column_id):
                    reasons.append("INVALID_RELATION_CONFIG")
                    break

    # Cenário pos_checklist: colunas/status/relations assumidos configurados.
    for column_id, label in item.status_labels.items():
        mapping = plan.status_mappings.get(column_id, {})
        if label in mapping and mapping[label] is None:
            reasons.append("MISSING_STATUS_MAPPING")
            break

    if item.people_ids:
        mapped = users_mapped or set()
        if user_policy is not None:
            for person_id in item.people_ids:
                if people_assignment_requires_manual(
                    person_id,
                    user_policy,
                    approved_exact_match_ids=mapped,
                ):
                    reasons.append("MISSING_USER_MAPPING")
                    break
        elif not set(item.people_ids).issubset(mapped):
            reasons.append("MISSING_USER_MAPPING")

    for relation in plan.relation_plans:
        targets = item.relation_targets.get(relation.monday_column_id, ())
        if not targets:
            continue
        if relation.monday_target_board_id is None:
            reasons.append("AMBIGUOUS_MAPPING")
            continue
        target_pool = known_target_items.get(relation.monday_target_board_id, set())
        missing = [target for target in targets if target not in target_pool]
        if missing:
            error = True

    if item.file_count:
        flags.append("file_materialization")
    if item.has_updates:
        flags.append("updates_para_migrar")
    if item.subitem_count:
        flags.append("subitens")

    if error:
        classification: Classification = "ERROR"
    elif reasons:
        classification = "MANUAL"
    else:
        classification = "WAVE_1_READY"
    return ItemDryRunResult(
        monday_board_id=plan.monday_board_id,
        monday_item_id=item.item_id,
        classification=classification,
        reasons=tuple(dict.fromkeys(reasons)),
        flags=tuple(dict.fromkeys(flags)),
        wave="WAVE_1",
    )


def _resolve_item_disposition(
    wave_result: ItemDryRunResult,
    board_disposition: Disposition,
) -> Disposition:
    """Combina classificação de onda com disposição do board."""
    if wave_result.classification == "ERROR":
        return Disposition.ERROR
    if wave_result.classification == "MANUAL":
        if board_disposition in {Disposition.MANUAL, Disposition.ERROR}:
            return board_disposition
        return Disposition.CREATE
    return board_disposition


def run_dry_run(
    inventories: dict[str, MondayBoardInventory],
    sunday_snapshots: dict[str, SundayBoardSnapshot],
    *,
    cutoff: datetime | None = None,
    users_mapped: set[str] | None = None,
    user_policy: UserMappingPolicy | None = None,
    scenario: str = "pos_checklist",
) -> tuple[DryRunReport, dict[str, BoardPlan], dict[str, int]]:
    """Executa o dry-run completo. NUNCA chama métodos de escrita.

    Integra classificação de onda (WAVE_1/WAVE_2 + bloqueios) com disposição
    por board (CREATE/ADOPT/ABSORB/EXCLUDE_TEST/…). Recebe inventários prontos.
    """
    if validate_wave1_targets():
        raise ValueError("WAVE1_TARGETS incompleto: board sem sunday_board_id.")

    resolved_cutoff = cutoff or default_cutoff()
    snapshot_ts = datetime.now(UTC).isoformat()
    board_map = sunday_board_by_monday_map()
    plans = {
        board_id: build_board_plan(
            inventory,
            sunday_snapshots.get(board_map.get(board_id) or ""),
            board_map,
        )
        for board_id, inventory in inventories.items()
    }

    selections = {}
    for board_id, inventory in inventories.items():
        selected, _concluded = select_recorte(inventory, cutoff=resolved_cutoff)
        selections[board_id] = selected
    pulled = expand_with_relation_targets(selections, inventories, plans)

    known_target_items = {
        board_id: {item.item_id for item in inventory.items}
        for board_id, inventory in inventories.items()
    }

    disposition_runs: dict[str, BoardDispositionDryRun] = {}
    disposition_by_item: dict[tuple[str, str], Disposition] = {}
    sunday_native_total = 0
    for board_id, inventory in inventories.items():
        plan = plans[board_id]
        rows = [MondaySourceRow(monday_item_id=item.item_id) for item in inventory.items]
        rules = board_disposition_rules(
            board_id,
            sunday_board_id=plan.sunday_board_id,
        )
        board_run = run_board_disposition_dry_run(
            rows=rows,
            rules=rules,
            source_snapshot_timestamp=snapshot_ts,
        )
        disposition_runs[board_id] = board_run
        sunday_native_total += len(board_run.ledger.natives)
        for entry in board_run.ledger.entries:
            disposition_by_item[(board_id, entry.monday_item_id)] = entry.disposition

    source_count_by_board = {
        board_id: len(inventory.items) for board_id, inventory in inventories.items()
    }
    source_snapshot_total = sum(source_count_by_board.values())

    report = DryRunReport(
        cutoff_iso=resolved_cutoff.isoformat(),
        scenario=scenario,
        source_snapshot_timestamp=snapshot_ts,
        source_snapshot_total=source_snapshot_total,
        source_count_by_board=source_count_by_board,
        sunday_native_total=sunday_native_total,
        disposition_runs=disposition_runs,
    )

    for board_id, inventory in inventories.items():
        plan = plans[board_id]
        for item in inventory.items:
            wave_result = classify_item(
                item,
                plan=plan,
                in_recorte=item.item_id in selections[board_id],
                scenario=scenario,
                known_target_items=known_target_items,
                users_mapped=users_mapped,
                user_policy=user_policy,
                group_title=inventory.groups.get(item.group_id or ""),
            )
            board_disp = disposition_by_item.get(
                (board_id, item.item_id),
                Disposition.CREATE,
            )
            disposition = _resolve_item_disposition(wave_result, board_disp)
            report.items.append(replace(wave_result, disposition=disposition))

    report.board_stats = report.build_board_stats()
    return report, plans, pulled
