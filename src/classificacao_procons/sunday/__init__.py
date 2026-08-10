"""Integração com o Sunday (sunday.b4a.ai) — API REST própria da B4A.

Diferente do Monday (GraphQL), o Sunday expõe uma API REST (NestJS). Este pacote
concentra o cliente REST e o parsing dos payloads, para a migração dos temas de
legal (ver ``docs/migracao-monday-sunday-legal.md``).
"""

from __future__ import annotations
