# Etapa 2.1 — Auditoria de consistência (read-only)

> **CONGELADO (2026-08-11):** remediation Monday interrompida. Este documento e os
> artefatos em `artifacts/controle-etapa2-1/` permanecem como referência histórica.
> Próximo trabalho: **Controle greenfield no Sunday** — `docs/controle-sunday-greenfield.md`.

> **Escopo:** Autentique → Monday / Controle Assinaturas apenas.  
> **Política:** `CONTROLE_WRITE_ENABLED=false`, `CONTROLE_PAUSE_CREATE=true`.  
> **Nenhuma mutation** no Monday. Nenhuma execução de remediation.

**Fonte:** `artifacts/compare-production/compare-controle-full.json` + índice Monday live.  
**Script:** `scripts/build_controle_consistency_audit.py`  
**Plano v2:** `artifacts/controle-etapa2-1/controle-remediation-plan-v2.json`

---

## Board Monday

| Bucket | Quantidade |
|--------|------------|
| **Total** | **1.607** |
| Com Autentique ID no índice (`items_by_document_id`) | 359 |
| Sem Autentique ID no índice | 1.204 |
| Casos especiais (linha `Autentique ID:` no link, não indexado) | 44 |
| **Soma** | **359 + 1.204 + 44 = 1.607** ✓ |

**Reconciliação 1.248 vs 1.204:**

- Compare `without_link` = **1.248** (só olha `items_by_document_id`)
- Etapa 2.1 `without_id` = **1.204**
- Diferença = **44** = casos especiais com linha explícita `Autentique ID:` no link mas
  ausentes do índice por documento
- Fórmula: `1.248 = 1.204 + 44`

Detalhes: `artifacts/controle-etapa2-1/monday_reconciliation.json`

---

## Archive (314 `ARCHIVE_LATER` etapa2)

| Métrica | Valor |
|---------|-------|
| Itens etapa2 `ARCHIVE_LATER` | 314 |
| Auditados no índice live | 314 |
| **ARCHIVE executável** | **0** |
| Rebaixados para `PROBABLE_ARCHIVE_REVIEW` | 314 |

**Distribuição `evidence_type`:**

| evidence_type | Qtd |
|---------------|-----|
| `autentique_url_confirmed` | 300 |
| `metadata_confirmed` | 9 |
| `title_pattern_only` | 5 |

Regra aplicada: **nenhum ARCHIVE automático** — inclusive `title_pattern_only` e URL
Autentique isolada. Todos os 314 viram `PROBABLE_ARCHIVE_REVIEW` no plano v2.

Detalhes item a item: `artifacts/controle-etapa2-1/archive_audit_314.json`

---

## Duplicatas (55 grupos etapa2 reavaliados)

Identidade correta: `(Autentique ID, track)`.

| Classificação | Grupos |
|---------------|--------|
| `VALID_MULTI_TRACK` (Jan + Luciano legítimo) | 35 |
| `TRUE_DUPLICATE_SAME_TRACK` | **0** |
| `AMBIGUOUS_TRACK` | 57 |

**Reconciliação com `duplicate_items = 0` no compare:** o compare só conta duplicata na
**mesma track** para o mesmo doc Autentique. Os 55 `TRUE_DUPLICATE` da etapa2 misturavam
pares Jan+Luciano válidos. Após reclassificação por `(Autentique ID, track)`, não há
duplicata real na mesma track.

Detalhes: `artifacts/controle-etapa2-1/duplicate_reaudit.json`

---

## Missing tracks (61 vs 57)

| Classificação humana | Documentos | Tracks faltantes |
|----------------------|------------|------------------|
| `CONFIRMED_CREATE_LATER` | 38 | 57 |
| `NEEDS_REVIEW` | 4 | 4 |
| **Total** | **42** | **61** |

- **57 `CREATE_TRACK`** no plano v2 = 61 − 4 tracks dos 4 docs `NEEDS_REVIEW`
- **Confirmado:** nenhuma track dos 4 `NEEDS_REVIEW` entrou como `CREATE_TRACK`

Detalhes: `artifacts/controle-etapa2-1/missing_tracks_math.json`

---

## Manual review — regras sugeridas (análise only, sem implementação)

### Pedido B2B (11 docs em `manual_review`)

**Regra proposta:** `pedido` + indicador comercial no título (b2b|fornec|comercial|parceria|…)
E ausência de indicadores RH/operacionais.

**Retrospectivo 298 docs:**

| Métrica | Valor |
|---------|-------|
| Novos elegíveis | 11 |
| Falsos positivos aparentes | 0 |
| Falsos negativos aparentes | 0 |

`juridico@` presente em 298/298 — **não** usar “signatário interno” como discriminador.

Detalhes: `artifacts/controle-etapa2-1/pedido_b2b_rule_analysis.json`

### Outras regras (impacto nos 298)

| Regra | Captura | Mudaria escopo |
|-------|---------|----------------|
| cessão → eligible | 1 doc | 1 |
| parceria → eligible | 12 docs | 1 |
| contrato mensal/colaborador → ineligible | 3 docs | 3 |

Detalhes: `artifacts/controle-etapa2-1/scope_rules_impact.json`

---

## remediation_plan_v2

| action_type | Qtd |
|-------------|-----|
| `CREATE_TRACK` | 57 |
| `LINK` | 9 |
| `UPDATE_STATUS` | 1 |
| `PROBABLE_ARCHIVE_REVIEW` | 324 (314 archive + 10 status ineligible) |
| `MANUAL_REVIEW` | 46 |
| `NO_ACTION` | 1.245 |

| Validação | Resultado |
|-----------|-----------|
| **violations** | **0** |
| confidence high / medium / low | 426 / 363 / 893 |
| requires_human_approval | 1.682 ações |

---

## Classificação final

### `NEEDS_MORE_REVIEW`

Motivo: **57 grupos `AMBIGUOUS_TRACK`** ainda precisam de triagem humana antes de
remediação controlada (track inferido incerto ou combinação ambígua).

Sinais ausentes que permitiriam `READY_FOR_CONTROLLED_REMEDIATION`:

- `executable_archive` = 0 ✓
- `violations` = 0 ✓
- `TRUE_DUPLICATE_SAME_TRACK` = 0 ✓
- `AMBIGUOUS_TRACK` = 57 ✗

**Não habilitar WRITE. Não executar remediation.**
