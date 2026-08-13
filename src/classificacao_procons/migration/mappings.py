"""Regras de mapping Monday → Sunday da Onda 1.

Construídas a partir do uso REAL no código (não por semelhança de nomes):
`monday/mapping.py` (Procon), `juridico/monday.py` e `juridico/casos.py`
(Prazos/Audiências/Processos/KPI) e `contratos/constants.py` +
`contratos/controle_*` (Controle/Contratos).
"""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.migration.models import (
    BoardPlan,
    ColumnPlan,
    Confidence,
    MondayBoardInventory,
    RelationPlan,
    SundayBoardSnapshot,
)

WAVE1_DOMAINS: dict[str, dict[str, str]] = {
    # monday_board_id -> {name, domain}
    "4944254220": {"name": "Procons", "domain": "procon"},
    "3961072966": {"name": "Prazos", "domain": "juridico"},
    "4443295406": {"name": "Audiências", "domain": "juridico"},
    "5343921475": {"name": "Processos Judiciais", "domain": "juridico"},
    "4443297481": {"name": "Processos Trabalhista", "domain": "juridico"},
    "5563754463": {"name": "KPI - Processos Consumidores", "domain": "juridico"},
    "5301515799": {"name": "Controle Assinaturas Contratos", "domain": "contratos"},
    "5385471914": {"name": "Contratos", "domain": "contratos"},
}

# Destinos no Sunday (workspace 22) — mapeamento definitivo F2.5 (8 boards).
WAVE1_TARGETS: dict[str, tuple[str | None, str | None, Confidence, str]] = {
    "4944254220": ("82", "Legal - Procons", "ALTA", "Board Sunday 82 confirmado F2.5."),
    "3961072966": ("83", "Legal - Prazos", "ALTA", "Board Sunday 83 confirmado F2.5."),
    "4443295406": (
        "72",
        "Legal - Audiências",
        "MEDIA",
        "Board Sunday 72; regras de disposição aprovadas (ADOPT/ABSORB/…).",
    ),
    "5343921475": (
        "84",
        "Legal - Processos Judiciais",
        "ALTA",
        "Quadro-mestre; alvo de relações Prazos/Audiências.",
    ),
    "4443297481": ("85", "Legal - Processos Trabalhista", "ALTA", "Board Sunday 85 F2.5."),
    "5563754463": (
        "86",
        "Legal - KPI Processos Consumidores",
        "ALTA",
        "Board Sunday 86; exceção integral na Onda 1.",
    ),
    "5301515799": (
        "77",
        "Legal - Controle de Assinaturas - Jan & Luciano",
        "MEDIA",
        "Board Sunday 77; não greenfield.",
    ),
    "5385471914": (
        "87",
        "Legal - Contratos",
        "ALTA",
        "Board Sunday 87; Tipo derivado dos grupos; alvo de relações Controle.",
    ),
}

# Relações realmente usadas pelo código (juridico/casos.py, juridico/monday.py,
# contratos/parent_resolver.py): coluna board_relation -> board Monday alvo.
WAVE1_RELATION_TARGETS: dict[tuple[str, str], str] = {
    # (monday_board_id, column_title normalizado) -> monday_target_board_id
    ("3961072966", "processos consumidores"): "5343921475",
    ("4443295406", "processos judiciais"): "5343921475",
    ("5301515799", "contrato relacionado"): "5385471914",
}

# Relações por column_id (inequívoco; duas colunas homônimas em Audiências).
WAVE1_RELATION_BY_COLUMN_ID: dict[tuple[str, str], str] = {
    ("3961072966", "conectar_quadros"): "5343921475",
    ("4443295406", "conectar_quadros__1"): "5343921475",
    ("4443295406", "conectar_quadros8__1"): "5343921475",
    ("5301515799", "board_relation_mm5ap90f"): "5385471914",
}

# Boards que entram INTEGRALMENTE na Onda 1 (exceções aprovadas ao recorte
# operacional): KPI é pequeno e é dado de referência (decisão de 2026-08-11).
WAVE1_FULL_BOARDS: frozenset[str] = frozenset({"5563754463"})

# ---------------------------------------------------------------------------
# Regras EXPLÍCITAS por grupo do Monday (preflight, item 3): todo group_id do
# escopo precisa de uma regra declarada — "preservar" (grupo homônimo no
# destino), "colapsar" (→ grupo Itens; a dimensão já vive em coluna) ou
# "transformar" (→ alimenta um campo no destino). Grupo sem regra = ERROR no
# dry-run; NUNCA fallback silencioso para Itens.
# Títulos exatos do inventário real de 2026-08-11 (normalizados sem acento).
GROUP_ACTION_PRESERVE = "preservar"
GROUP_ACTION_COLLAPSE = "colapsar"
GROUP_ACTION_TRANSFORM = "transformar"

GROUP_RULES: dict[str, dict[str, tuple[str, str]]] = {
    # monday_board_id -> {titulo normalizado: (ação, nota)}
    "4944254220": {
        "pendentes de resposta": (GROUP_ACTION_PRESERVE, "fila operacional do Procon"),
        "processos administrativos": (GROUP_ACTION_PRESERVE, "fila de PA"),
        "2023": (GROUP_ACTION_COLLAPSE, "arquivo anual; ano preservado nas datas"),
        "2024": (GROUP_ACTION_COLLAPSE, "arquivo anual"),
        "2025": (GROUP_ACTION_COLLAPSE, "arquivo anual"),
        "2026": (GROUP_ACTION_COLLAPSE, "arquivo anual"),
    },
    "3961072966": {
        "prazos processos": (GROUP_ACTION_PRESERVE, "grupo usado pelo agente jurídico"),
        "procon": (GROUP_ACTION_COLLAPSE, "domínio Procon; coluna Processo Administrativo"),
        "prazos procon's": (GROUP_ACTION_COLLAPSE, "idem"),
    },
    "4443295406": {
        "audiencias (procons e processos)": (
            GROUP_ACTION_COLLAPSE,
            "board 72 preserva os grupos atuais; distinção vive na coluna Processo/Procon",
        ),
    },
    "5343921475": {
        "processos consumidores ativos": (
            GROUP_ACTION_PRESERVE,
            "grupo-mestre usado por juridico/casos.py",
        ),
        "civel": (GROUP_ACTION_COLLAPSE, "dimensão na coluna 'Processo relacionado a'"),
        "fiscal tributario": (GROUP_ACTION_COLLAPSE, "idem"),
        "criminal": (GROUP_ACTION_COLLAPSE, "idem"),
        "administrativo": (GROUP_ACTION_COLLAPSE, "idem"),
        "processos encerrados": (GROUP_ACTION_COLLAPSE, "estado na coluna Status=Encerrado"),
    },
    "4443297481": {
        "trabalhista ativo": (GROUP_ACTION_COLLAPSE, "estado na coluna Status"),
        "trabalhista encerrado": (GROUP_ACTION_COLLAPSE, "estado na coluna Status"),
    },
    "5563754463": {
        "2023": (GROUP_ACTION_COLLAPSE, "ano na Data Ajuizamento"),
        "2022": (GROUP_ACTION_COLLAPSE, "idem"),
        "2021": (GROUP_ACTION_COLLAPSE, "idem"),
        "2020": (GROUP_ACTION_COLLAPSE, "idem"),
        "2018": (GROUP_ACTION_COLLAPSE, "idem"),
    },
    "5301515799": {
        "contratos pendentes de assinatura jan": (GROUP_ACTION_PRESERVE, "fila Jan"),
        "contratos pendentes de assinatura luciano": (GROUP_ACTION_PRESERVE, "fila Luciano"),
        "pendente fornecedor": (GROUP_ACTION_PRESERVE, "fila fornecedor"),
        "assinados": (GROUP_ACTION_PRESERVE, "terminal"),
        "recusado": (GROUP_ACTION_PRESERVE, "terminal"),
    },
    "5385471914": {
        # grupos são o "tipo" do contrato → alimentam a coluna Tipo do board 87
        "rh": (GROUP_ACTION_TRANSFORM, "Tipo=RH"),
        "contratos b4a": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos B4A"),
        "contratos mmkt": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos MMKT"),
        "contratos itaro": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos Itaro"),
        "contratos rv bvi": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos RV BVI"),
        "contratos aurora": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos Aurora"),
        "contratos societarios": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos Societários"),
        "contratos b2b": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos B2B"),
        "contratos de cambio": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos de Câmbio"),
        "nda": (GROUP_ACTION_TRANSFORM, "Tipo=NDA"),
        "contratos influencers (queens)": (
            GROUP_ACTION_TRANSFORM,
            "Tipo=Contratos Influencers (Queens)",
        ),
        "procuracoes": (GROUP_ACTION_TRANSFORM, "Tipo=Procurações"),
        "contratos jan": (GROUP_ACTION_TRANSFORM, "Tipo=Contratos Jan"),
        "sindicato": (GROUP_ACTION_TRANSFORM, "Tipo=Sindicato"),
        "politicas internas": (GROUP_ACTION_TRANSFORM, "Tipo=Políticas Internas"),
        "ferramentas": (GROUP_ACTION_TRANSFORM, "Tipo=Ferramentas"),
        # Encerrados NÃO vira Tipo (decisão do usuário): vira Vigência=Não Vigente.
        "contratos encerrados": (
            GROUP_ACTION_TRANSFORM,
            "Vigência=Não Vigente; Tipo fica vazio (não inventar)",
        ),
    },
}


def group_rule(board_id: str, group_title: str | None) -> tuple[str, str] | None:
    """Regra explícita para um grupo do Monday; None = sem regra (ERROR)."""
    if group_title is None:
        return None
    return GROUP_RULES.get(board_id, {}).get(_normalize(group_title))

# Grupos que significam "concluído" (semântica real de cada board — grupos de
# arquivo por ano, assinados/recusados e encerrados).
_DONE_GROUP_PATTERNS = (
    re.compile(r"^(19|20)\d{2}([/ ].*)?$"),  # "2023", "2024" …
    re.compile(r"assinados"),
    re.compile(r"recusado"),
    re.compile(r"encerrad"),  # encerrado(s)
    re.compile(r"arquivad"),
)

# Labels de status que significam "concluído" quando o board não usa grupos de
# arquivo (derivadas dos fluxos reais: Controle/Contratos/Jurídico).
DONE_STATUS_LABELS = frozenset(
    {
        "assinado",
        "recusado",
        "concluido",
        "concluído",
        "done",
        "encerrado",
        "finalizado",
        "respondido",
        "baixado",
        "pago",
        "cancelado",
        "cancelada",
        "feito",
        "nao vigente",
    },
)

# Boards cuja coluna de conclusão não se chama "Status" (semântica real do board).
MAIN_STATUS_TITLE_OVERRIDES: dict[str, str] = {
    # Contratos: repositório de contratos; "concluído" = fora de vigência.
    "5385471914": "vigencia",
}

# De-para explícito Monday column_id → label Sunday quando o rótulo difere
# (truncamento, Houve vs Teve, etc.). Chave normalizada via _normalize().
COLUMN_LABEL_OVERRIDES: dict[tuple[str, str], str] = {
    # Procons: Sunday col 609 label truncado "ouve Cancelamento de Assinatura?"
    ("4944254220", "color_mknz9dwg"): "ouve cancelamento de assinatura?",
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", stripped).strip()


def slugify_status_key(label: str) -> str:
    """Key determinística proposta para a opção de status no Sunday."""
    normalized = _normalize(label)
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return slug or "opcao"


def group_is_done(group_title: str) -> bool:
    normalized = _normalize(group_title)
    return any(pattern.search(normalized) for pattern in _DONE_GROUP_PATTERNS)


def item_is_concluded(
    *,
    group_title: str | None,
    status_labels: dict[str, str],
    main_status_column_id: str | None,
) -> bool:
    """Semântica de concluído: grupo de arquivo OU status terminal na coluna principal."""
    if group_title and group_is_done(group_title):
        return True
    if main_status_column_id:
        label = status_labels.get(main_status_column_id, "")
        if _normalize(label) in DONE_STATUS_LABELS:
            return True
    return False


def find_main_status_column(inventory: MondayBoardInventory) -> str | None:
    """Coluna de conclusão do board (título "Status", com overrides por board)."""
    wanted = MAIN_STATUS_TITLE_OVERRIDES.get(inventory.board_id, "status")
    for column in inventory.columns:
        if column.type == "status" and _normalize(column.title) == wanted:
            return column.id
    return None


_TYPE_STRATEGY: dict[str, tuple[str, str, str | None]] = {
    # monday type -> (estratégia, alvo sunday proposto, nota)
    "name": ("direto", "name (campo de sistema)", None),
    "text": ("direto", "text", None),
    "long_text": ("direto", "long_text", None),
    "numbers": ("direto", "number", None),
    "date": ("direto", "date", None),
    "link": ("direto", "link", None),
    "email": ("direto", "email", None),
    "status": (
        "configurar_manualmente",
        "status (coluna custom com options 1:1)",
        "Criar coluna e options manualmente; de-para de labels na tabela de status.",
    ),
    "people": (
        "transformacao",
        "people (owner) via de-para de usuários",
        "Depende do de-para Monday→Sunday aprovado (Etapa 6).",
    ),
    "file": (
        "transformacao",
        "attachments/link",
        "Materialização: asset Monday → Drive/GCS → anexo por link (upload binário é 403).",
    ),
    "board_relation": (
        "transformacao",
        "board_relation (values) + mapa de IDs",
        "Requer coluna criada manualmente com source_board_id correto (Etapa 7).",
    ),
    "subtasks": (
        "derivado_pelo_codigo",
        "subitens nativos (parent_item_id)",
        "Subelementos viram filhos nativos; nenhum campo é copiado da coluna.",
    ),
    "mirror": (
        "derivado_pelo_codigo",
        "lookup no código de sync",
        "Sunday mirror é read-only p/ token; valor é derivável da relação.",
    ),
    "lookup": ("derivado_pelo_codigo", "lookup no código de sync", None),
    "formula": (
        "configurar_manualmente",
        "formula (expressão do Sunday)",
        "Recriar a expressão à mão (2 colunas na Onda 1).",
    ),
    "location": ("transformacao", "text", "Sunday não tem tipo location; degrada para texto."),
    "time_tracking": (
        "transformacao",
        "number (horas acumuladas)",
        "Preserva o total; cronômetro futuro é config manual.",
    ),
    "item_id": ("nao_migrar", None, "ID nativo do Monday; rastreio vai na coluna Monday ID."),
    "creation_log": ("nao_migrar", None, "Metadado nativo; preservado no ledger."),
    "last_updated": ("nao_migrar", None, "Metadado nativo; preservado no ledger."),
    "checkbox": ("direto", "checkbox", None),
    "dropdown": (
        "configurar_manualmente",
        "dropdown (options 1:1)",
        "Criar options manualmente; valores migram por key.",
    ),
    "tags": ("direto", "tags", None),
    "rating": ("direto", "rating", None),
    "phone": ("direto", "phone", None),
}

_SYSTEM_TARGETS = {"name", "status", "owner", "target_date", "area"}


def build_column_plans(
    inventory: MondayBoardInventory,
    target: SundayBoardSnapshot | None,
) -> tuple[ColumnPlan, ...]:
    """Plano por coluna: estratégia por tipo + verificação de existência no destino."""
    plans: list[ColumnPlan] = []
    target_by_label = {
        _normalize(column.label): column for column in (target.columns if target else ())
    }
    for column in inventory.columns:
        strategy, sunday_target, note = _TYPE_STRATEGY.get(
            column.type, ("configurar_manualmente", None, f"Tipo {column.type} sem regra."),
        )
        override_label = COLUMN_LABEL_OVERRIDES.get((inventory.board_id, column.id))
        if override_label and target:
            existing = target_by_label.get(_normalize(override_label))
        else:
            existing = target_by_label.get(_normalize(column.title)) if target else None
        plans.append(
            ColumnPlan(
                monday_column_id=column.id,
                monday_title=column.title,
                monday_type=column.type,
                strategy=strategy,  # type: ignore[arg-type]
                sunday_target=sunday_target,
                sunday_column_id=existing.id if existing else None,
                exists_in_target=existing is not None,
                note=note,
            ),
        )
    return tuple(plans)


def build_status_mappings(
    inventory: MondayBoardInventory,
) -> dict[str, dict[str, str | None]]:
    """De-para determinístico label→key (slug) por coluna de status.

    Nenhum fuzzy match: cada label vira uma option 1:1 no Sunday com key slug;
    labels usados em itens mas ausentes do schema entram com key None (para
    revisão explícita — MISSING_STATUS_MAPPING).
    """
    mappings: dict[str, dict[str, str | None]] = {}
    for column in inventory.columns:
        if column.type != "status":
            continue
        mapping: dict[str, str | None] = {
            label: slugify_status_key(label) for label in column.status_labels()
        }
        mappings[column.id] = mapping
    for item in inventory.items:
        for column_id, label in item.status_labels.items():
            column_map = mappings.setdefault(column_id, {})
            if label not in column_map:
                column_map[label] = None  # usado em item mas fora do schema
    return mappings


def validate_wave1_targets() -> list[str]:
    """Retorna board_ids da Onda 1 sem sunday_board_id (deve ser vazio)."""
    return [
        board_id
        for board_id, target in WAVE1_TARGETS.items()
        if not target[0]
    ]


def validate_group_rules_coverage(
    inventories: dict[str, MondayBoardInventory],
) -> dict[str, list[str]]:
    """Grupos presentes no inventário sem regra explícita (deve ser vazio)."""
    missing: dict[str, list[str]] = {}
    for board_id, inventory in inventories.items():
        for group_id, title in inventory.groups.items():
            if group_rule(board_id, title) is None:
                missing.setdefault(board_id, []).append(f"{group_id}:{title}")
    return missing


def build_relation_plans(
    inventory: MondayBoardInventory,
    target: SundayBoardSnapshot | None,
    sunday_board_by_monday: dict[str, str | None],
) -> tuple[RelationPlan, ...]:
    plans: list[RelationPlan] = []
    for column in inventory.columns:
        if column.type != "board_relation":
            continue
        monday_target = WAVE1_RELATION_BY_COLUMN_ID.get(
            (inventory.board_id, column.id),
        ) or WAVE1_RELATION_TARGETS.get(
            (inventory.board_id, _normalize(column.title)),
        )
        expected_sunday = sunday_board_by_monday.get(monday_target or "", None)
        existing = None
        if target:
            for candidate in target.columns:
                if (
                    candidate.type == "board_relation"
                    and _normalize(candidate.label) == _normalize(column.title)
                ):
                    existing = candidate
        configured = (
            str(existing.settings.get("source_board_id"))
            if existing and existing.settings.get("source_board_id") is not None
            else None
        )
        config_ok: bool | None = None
        note = None
        if monday_target is None:
            note = "Coluna board_relation fora das relações usadas pelo código (avaliar)."
        if existing is not None:
            config_ok = bool(
                configured and expected_sunday and configured == expected_sunday,
            )
            if not config_ok:
                note = "CONFIGURAÇÃO MANUAL OBRIGATÓRIA ANTES DA MIGRAÇÃO (source_board_id)."
        plans.append(
            RelationPlan(
                monday_board_id=inventory.board_id,
                monday_column_id=column.id,
                monday_column_title=column.title,
                monday_target_board_id=monday_target,
                sunday_board_id=target.board_id if target else None,
                sunday_column_id=existing.id if existing else None,
                expected_sunday_target_board_id=expected_sunday,
                configured_source_board_id=configured,
                config_ok=config_ok,
                note=note,
            ),
        )
    return tuple(plans)


def build_board_plan(
    inventory: MondayBoardInventory,
    target: SundayBoardSnapshot | None,
    sunday_board_by_monday: dict[str, str | None],
) -> BoardPlan:
    meta = WAVE1_DOMAINS.get(inventory.board_id, {"name": inventory.name, "domain": "?"})
    target_id, target_name, confidence, note = WAVE1_TARGETS.get(
        inventory.board_id, (None, None, "BAIXA", "Board fora da Onda 1."),
    )
    return BoardPlan(
        monday_board_id=inventory.board_id,
        monday_name=meta["name"],
        domain=meta["domain"],
        sunday_board_id=target_id,
        sunday_name=target_name,
        confidence=confidence,  # type: ignore[arg-type]
        note=note,
        column_plans=build_column_plans(inventory, target),
        relation_plans=build_relation_plans(inventory, target, sunday_board_by_monday),
        status_mappings=build_status_mappings(inventory),
    )


def sunday_board_by_monday_map() -> dict[str, str | None]:
    return {board_id: target[0] for board_id, target in WAVE1_TARGETS.items()}
