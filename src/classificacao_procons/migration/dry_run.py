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

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from classificacao_procons.migration.mappings import (
    WAVE1_FULL_BOARDS,
    build_board_plan,
    find_main_status_column,
    group_rule,
    item_is_concluded,
    sunday_board_by_monday_map,
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

RECORTE_MONTHS = 12


@dataclass
class DryRunReport:
    cutoff_iso: str
    scenario: str
    items: list[ItemDryRunResult] = field(default_factory=list)

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

    def to_payload(self) -> dict:
        """Relatório agregado sanitizado (sem conteúdo de itens).

        Escopo total = Onda 1 + Onda 2: itens `WAVE_2_HISTORICAL` são
        contabilizados como OBRIGATÓRIOS para a Onda 2 (backfill), nunca como
        descarte. Percentuais de prontidão são calculados sobre a Onda 1.
        """
        counts = self.counts()
        total = sum(counts.values())
        onda1 = counts["WAVE_1_READY"] + counts["MANUAL"] + counts["ERROR"]
        return {
            "scenario": self.scenario,
            "cutoff": self.cutoff_iso,
            "total_analisado": total,
            "onda1_total": onda1,
            "onda2_backfill_obrigatorio": counts["WAVE_2_HISTORICAL"],
            "meta_final": f"{total}/{total} itens no Sunday (duas ondas)",
            "counts": counts,
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
    users_mapped: set[str],
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
            wave="onda1" if in_recorte else "onda2",
        )
    if not in_recorte:
        # Fora da Onda 1 ≠ descarte: backfill histórico OBRIGATÓRIO na Onda 2.
        return ItemDryRunResult(
            monday_board_id=plan.monday_board_id,
            monday_item_id=item.item_id,
            classification="WAVE_2_HISTORICAL",
            reasons=("HISTORICAL_BACKFILL",),
            wave="onda2",
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

    if item.people_ids and not set(item.people_ids).issubset(users_mapped):
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
        wave="onda1",
    )


def run_dry_run(
    inventories: dict[str, MondayBoardInventory],
    sunday_snapshots: dict[str, SundayBoardSnapshot],
    *,
    cutoff: datetime | None = None,
    users_mapped: set[str] | None = None,
    scenario: str = "pos_checklist",
) -> tuple[DryRunReport, dict[str, BoardPlan], dict[str, int]]:
    """Executa o dry-run completo. NUNCA chama métodos de escrita.

    Recebe dados prontos (inventários Monday e snapshots Sunday) — a coleta é
    responsabilidade do chamador, o que garante por construção que este motor
    não faz nenhuma chamada HTTP.
    """
    resolved_cutoff = cutoff or default_cutoff()
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
    report = DryRunReport(cutoff_iso=resolved_cutoff.isoformat(), scenario=scenario)
    for board_id, inventory in inventories.items():
        plan = plans[board_id]
        for item in inventory.items:
            report.items.append(
                classify_item(
                    item,
                    plan=plan,
                    in_recorte=item.item_id in selections[board_id],
                    scenario=scenario,
                    known_target_items=known_target_items,
                    users_mapped=users_mapped or set(),
                    group_title=inventory.groups.get(item.group_id or ""),
                ),
            )
    return report, plans, pulled
