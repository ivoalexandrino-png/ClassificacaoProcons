# Ledger durável e approval safety

## Fonte canônica

O ledger durável/versionado da migração Monday→Sunday é:

`docs/migration/monday-sunday-ledger.json`

Esse arquivo é a fonte canônica para:

- idempotência (`already_migrated`);
- contagem de itens migrados por board;
- vínculo Monday item id ↔ Sunday item id.

Reconstrução a partir do Sunday **não** substitui o ledger canônico. Serve apenas para diagnóstico/sync plan.

## Semântica de persistência

Durante APPLY, cada operação `LEDGER_ENTRY` deve:

1. gravar entrada via `persist_ledger_record()` (tmp+rename);
2. fazer read-back/reload do ledger;
3. só então contar como `ledger_durable_confirmed`.

Relatórios distinguem:

| Campo | Significado |
|---|---|
| `ledger_expected` | operações de ledger previstas no manifest |
| `ledger_durable_confirmed` | entradas persistidas e confirmadas por read-back |
| `ledger_pending_sync` | mapping comprovado live mas ausente do ledger versionado |
| `ledger_failed` | persistência ou read-back falhou |

`operation_manifest.accounting.ledger_operations` continua sendo a contagem **esperada** no PLAN. O APPLY report usa os campos acima para a execução real.

## Approval e runtime change

Depois que um approval bundle é emitido:

- qualquer mudança em módulo coberto por `migration_code_revision()` invalida o approval;
- é obrigatório gerar fresh PLAN e nova autorização antes de APPLY.

**Recomendação operacional:** não fazer direct commit em `main` de runtime de migração durante janela de APPLY aprovado. Fluxo: branch/PR → merge → fresh PLAN → nova autorização.

## Ledger sync

Quando o ledger versionado ficar atrás do estado live comprovado:

```bash
python scripts/sunday_migration_execute.py \
  --board 4944254220 --wave 1 --mode ledger-sync-plan --max-items 1 \
  --out /tmp/ledger-sync-plan.json
```

O PLAN é read-only. A sincronização real exige revisão humana e commit explícito do JSON canônico.
