"""Política de matching de usuários Monday → Sunday (decisão aprovada 25/3/30)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

UserMatchTier = Literal["exact", "active_unmatched", "deactivated", "unknown"]


@dataclass(frozen=True)
class UserMappingPolicy:
    """Conjuntos aprovados para classificar responsáveis sem fuzzy matching."""

    exact_match_ids: frozenset[str]
    active_unmatched_ids: frozenset[str]
    deactivated_ids: frozenset[str]

    @property
    def known_active_ids(self) -> frozenset[str]:
        return self.exact_match_ids | self.active_unmatched_ids


def load_user_mapping_policy(path: str | Path) -> UserMappingPolicy:
    """Carrega a política a partir do JSON sanitizado de identidades Monday."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    deactivated = frozenset(str(item_id) for item_id in payload.get("monday_ids_sem_cadastro", []))
    active_unmatched = frozenset(
        str(item_id) for item_id in payload.get("active_sem_match_sunday", [])
    )
    enabled_ids = frozenset(
        str(user["monday_user_id"])
        for user in payload.get("users", [])
        if user.get("enabled", True)
    )
    exact_match = enabled_ids - active_unmatched
    return UserMappingPolicy(
        exact_match_ids=exact_match,
        active_unmatched_ids=active_unmatched,
        deactivated_ids=deactivated,
    )


def classify_monday_user(monday_user_id: str, policy: UserMappingPolicy) -> UserMatchTier:
    if monday_user_id in policy.deactivated_ids:
        return "deactivated"
    if monday_user_id in policy.active_unmatched_ids:
        return "active_unmatched"
    if monday_user_id in policy.exact_match_ids:
        return "exact"
    return "unknown"


def people_assignment_requires_manual(
    monday_user_id: str,
    policy: UserMappingPolicy,
    *,
    approved_exact_match_ids: set[str] | None = None,
) -> bool:
    """Retorna True somente quando o item deve ir para MANUAL por usuário desconhecido."""
    tier = classify_monday_user(monday_user_id, policy)
    if tier in {"deactivated", "active_unmatched"}:
        return False
    if tier == "exact":
        if approved_exact_match_ids is None:
            return False
        return monday_user_id not in approved_exact_match_ids
    return True
