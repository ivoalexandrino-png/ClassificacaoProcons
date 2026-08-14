# Ledger durável e approval safety

## Fonte canônica

O ledger durável/versionado da migração Monday→Sunday é:

`docs/migration/monday-sunday-ledger.json`

**Versionado em Git** (`HEAD`/main aprovado). O working tree local sozinho não basta.

Reconstrução a partir do Sunday serve para diagnóstico/sync plan, não substitui o ledger canônico.

## Semântica de estados

| Campo | Significado |
|---|---|
| `ledger_expected` | operações previstas no manifest |
| `ledger_file_persisted` | `persist_ledger_record` + read-back OK no **arquivo local** |
| `ledger_pending_commit` | arquivo local contém mapping que **Git HEAD ainda não contém** |
| `ledger_versioned_confirmed` | mapping presente e equivalente em **Git HEAD** |
| `ledger_pending_sync` | mapping comprovado live (Sunday) **ausente do arquivo local** |
| `ledger_failed` | persist/reload/conflito falhou |

**Não** chamar filesystem local de `ledger_versioned_confirmed`.

## Gate para próximo APPLY

Antes de **qualquer** APPLY:

- `ledger_pending_sync = 0`
- `ledger_pending_commit = 0`

Fallback Sunday **não** libera gate. Serve para recovery/detecção via `ledger-sync-plan`.

## Fluxo APPLY → commit humano

1. APPLY grava arquivo local + read-back → `ledger_file_persisted`
2. Novos mappings → `ledger_pending_commit = N` (esperado)
3. **Próximo APPLY bloqueado** até commit/merge do ledger
4. Humano revisa PR/commit do JSON
5. Merge em main → `ledger_versioned_confirmed`
6. Fresh PLAN permitido

O executor **não** faz `git commit/push` automaticamente.

## Ledger sync (etapa separada)

```bash
python scripts/sunday_migration_execute.py \
  --board 4944254220 --wave 1 --mode ledger-sync-plan --max-items 1 \
  --out /tmp/ledger-sync-plan.json
```

- `changes_required=true` → sync necessário (`add=10`, etc.)
- Após sync file + commit Git → `sync_idempotent=true` (rerun `add=0 modify=0 delete=0`)

## code_revision

Digest recursivo de **todo** `src/classificacao_procons/migration/**/*.py` + `scripts/sunday_migration_execute.py`.

Novo/removido/alterado módulo runtime → revision muda → approval anterior inválido.

## Approval e runtime change

Depois que um approval bundle é emitido, qualquer mudança em módulo runtime invalida o approval.

**Recomendação:** não fazer direct commit em `main` de runtime de migração durante janela de APPLY aprovado.

Fluxo: branch/PR → merge → fresh PLAN → nova autorização.
