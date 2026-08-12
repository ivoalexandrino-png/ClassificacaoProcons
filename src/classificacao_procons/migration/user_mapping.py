"""Política de matching de usuários Monday → Sunday (decisão aprovada 25/3/30)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

UserMatchTier = Literal["exact", "active_unmatched", "deactivated", "unknown"]

DEFAULT_IDENTITIES_PATH = "docs/monday-user-identities-2026-08-11.json"


@dataclass(frozen=True)
class UserMappingPolicy:
    """Conjuntos aprovados para classificar responsáveis sem fuzzy matching."""

    exact_match_ids: frozenset[str]
    active_unmatched_ids: frozenset[str]
    deactivated_ids: frozenset[str]

    @property
    def known_active_ids(self) -> frozenset[str]:
        return self.exact_match_ids | self.active_unmatched_ids


def identity_hash_from_email(email: str) -> str:
    """Hash técnico aprovado F2.5: sha256(email.lower())[:16]."""
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def compute_match_buckets_from_directory(
  directory_emails: list[str],
  identities_path: str | Path = DEFAULT_IDENTITIES_PATH,
) -> tuple[frozenset[str], frozenset[str]]:
    """Classifica usuários ativos Monday em match exato vs sem match (F2.5)."""
    payload = json.loads(Path(identities_path).read_text(encoding="utf-8"))
    sunday_hashes = {identity_hash_from_email(email) for email in directory_emails}
    exact: set[str] = set()
    unmatched: set[str] = set()
    for user in payload.get("users", []):
        if not user.get("enabled", True):
            continue
        monday_id = str(user["monday_user_id"])
        identity_hash = str(user["identity_hash"])
        if identity_hash in sunday_hashes:
            exact.add(monday_id)
        else:
            unmatched.add(monday_id)
    return frozenset(exact), frozenset(unmatched)


def materialize_active_sem_match_sunday(
    active_unmatched_ids: frozenset[str],
    identities_path: str | Path = DEFAULT_IDENTITIES_PATH,
) -> None:
    """Persiste os 3 ativos sem match no JSON (somente IDs técnicos)."""
    path = Path(identities_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["active_sem_match_sunday"] = sorted(active_unmatched_ids)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_user_mapping_policy(path: str | Path = DEFAULT_IDENTITIES_PATH) -> UserMappingPolicy:
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
