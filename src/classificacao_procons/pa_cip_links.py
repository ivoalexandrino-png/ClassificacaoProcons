"""Vínculos declarados PA → CIP (mesmos fatos), quando heurística/portal não bastam."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_LINKS_PATH = Path("data/procon-pa-cip-links.json")
ENV_PA_CIP_PROTOCOL_MAP = "PROCON_PA_CIP_PROTOCOL_MAP"

# Casos validados (mesmos fatos); arquivo local / env sobrescrevem.
BUILTIN_PA_CIP_LINKS: dict[str, str] = {
    "1681159/2026": "1624924/2026",
}


def _parse_map_line(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        pa_proto, cip_proto = part.split("=", 1)
        pa_proto = pa_proto.strip()
        cip_proto = cip_proto.strip()
        if pa_proto and cip_proto:
            result[pa_proto] = cip_proto
    return result


def load_pa_cip_protocol_links(
    *,
    links_path: Path | None = None,
) -> dict[str, str]:
    """Mapa protocolo PA → protocolo CIP de origem (arquivo + env)."""
    merged: dict[str, str] = {}
    path = links_path or DEFAULT_LINKS_PATH
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key, value in data.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                if key.strip() and value.strip():
                    merged[key.strip()] = value.strip()

    env_raw = os.environ.get(ENV_PA_CIP_PROTOCOL_MAP, "").strip()
    if env_raw:
        merged.update(_parse_map_line(env_raw))

    for key, value in BUILTIN_PA_CIP_LINKS.items():
        merged.setdefault(key, value)
    return merged


def origin_cip_protocol_for_pa(pa_protocol: str) -> str | None:
    normalized = pa_protocol.strip()
    if not normalized:
        return None
    links = load_pa_cip_protocol_links()
    return links.get(normalized)


def normalize_board_protocol(value: str) -> str | None:
    """Extrai NNNN/AAAA de texto de coluna do Monday."""
    compact = re.sub(r"\s+", "", value.strip())
    match = re.search(r"(\d{5,}/\d{4})", compact)
    if match:
        return match.group(1)
    match = re.search(r"(\d+/\d{4})", compact)
    return match.group(1) if match else None
