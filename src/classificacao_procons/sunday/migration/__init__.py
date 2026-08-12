"""Núcleo do dry-run de migração Monday → Sunday (read-only, sem escrita).

Modela **disposições de fonte** (o que fazer com cada linha do Monday), um
**ledger** que admite muitos Monday IDs apontando para o mesmo Sunday item, e a
**conservação** das source rows do snapshot. Nada aqui escreve no Monday ou no
Sunday nem migra itens — é planejamento/verificação.

Ver ``docs/migracao-monday-sunday-legal.md`` e ``docs/sunday-api-endpoints.md``.
"""

from __future__ import annotations
