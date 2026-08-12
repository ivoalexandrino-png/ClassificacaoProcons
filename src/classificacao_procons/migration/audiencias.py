"""Regras aprovadas do board Audiências (Monday 4443295406 → Sunday 72).

Codifica a semântica final aprovada. É **dado**, não escrita: o dry-run aplica
estas regras sobre um snapshot read-only. Nenhum item é criado.
"""

from __future__ import annotations

from classificacao_procons.migration.board_disposition import BoardRules
from classificacao_procons.migration.disposition_ledger import SundayNativeEntry

AUDIENCIAS_MONDAY_BOARD_ID = "4443295406"
AUDIENCIAS_SUNDAY_BOARD_ID = "72"
AUDIENCIAS_SOURCE_SNAPSHOT_TOTAL = 121

# Nominais reconciliados: adotam itens Sunday existentes (não criar duplicata).
AUDIENCIAS_ADOPT_MAP: dict[str, str] = {
    "11322933382": "7043",
    "12163783926": "7044",
    "12641412911": "7045",
    "12119095560": "7046",
    "12641444415": "7047",
    "12471322038": "7048",
    "12641421545": "7049",
    "12641423370": "7050",
}

# Auxiliares/duplicados semânticos: monday_item_id -> canonical_monday_item_id.
AUDIENCIAS_ABSORB_MAP: dict[str, str] = {
    # Técnico Daiane absorvido no nominal canônico (Sunday 7043).
    "12658169524": "11322933382",
    # Placeholder 22/10 00:00 absorvido no canônico 22/10 16:00 (mesmo processo).
    "12765154145": "12774333107",
}

# Técnico canônico (16:00) cria o item Sunday.
AUDIENCIAS_CREATE_IDS: frozenset[str] = frozenset({"12774333107"})

# Registro de validação: não cria item operacional, mas conta no snapshot.
AUDIENCIAS_EXCLUDE_TEST_MAP: dict[str, str] = {
    "12566356804": "VALIDATION_RECORD",
}

# Item nativo do Sunday, sem correspondente Monday: preservar, fora do denominador.
AUDIENCIAS_SUNDAY_NATIVES: tuple[SundayNativeEntry, ...] = (
    SundayNativeEntry(
        sunday_board_id=AUDIENCIAS_SUNDAY_BOARD_ID,
        sunday_item_id="7065",
        name="Maria Helena Correia",
    ),
)


def audiencias_rules(*, wave: str | None = "WAVE_1") -> BoardRules:
    """Regras do board Audiências."""
    return BoardRules(
        monday_board_id=AUDIENCIAS_MONDAY_BOARD_ID,
        sunday_board_id=AUDIENCIAS_SUNDAY_BOARD_ID,
        adopt_map=dict(AUDIENCIAS_ADOPT_MAP),
        absorb_map=dict(AUDIENCIAS_ABSORB_MAP),
        exclude_test_map=dict(AUDIENCIAS_EXCLUDE_TEST_MAP),
        create_ids=AUDIENCIAS_CREATE_IDS,
        sunday_natives=AUDIENCIAS_SUNDAY_NATIVES,
        wave=wave,
    )
