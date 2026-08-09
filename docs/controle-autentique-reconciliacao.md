# Reconciliação Autentique ↔ Controle Assinaturas

## Fonte da verdade

| Sistema | Papel |
|---------|--------|
| **Autentique** | Existência do documento, signatários, quem já assinou, PDF assinado |
| **Monday Controle** | Filas Jan/Luciano, Tipo, gatilho para Contratos |
| **Monday Contratos** | Contratos concluídos (fase posterior; depende de colunas + automação) |

O vínculo estável entre os três é o **`Autentique ID`** no link do item do Controle. Título no Monday pode divergir do Autentique (minuta vs contrato B2B); **não** usamos só o fornecedor no nome para fundir itens.

Comparar “abrindo o arquivo” no Autentique, no sentido ideal, significa consultar a **API** (metadados + signatários + URL do PDF) e, quando necessário, o **PDF** — não adivinhar só pelo título. Hoje o repositório faz a parte via API no sync/webhook; comparação de conteúdo do PDF fica como melhoria futura para casos legados ambíguos.

## Quatro garantias (objetivo operacional)

### 1 — Tudo do Autentique está no Monday (Controle)

- **Pendente no Autentique** → deve existir par Jan/Luciano no Controle (ou item legado vinculado com o mesmo `Autentique ID`).
- **Como medir:** `compare-controle` → `pending_missing_in_monday`.
- **Como corrigir:** `sync-controle` (modo seguro: só pendentes, `create_only` / `skip_signed_documents` conforme workflow).
- **Pausa operacional:** enquanto o quadro estiver sendo saneado, a **criação** de novos itens fica desligada por padrão (`CONTROLE_PAUSE_CREATE`). O sync ainda atualiza, repara filas e faz auto-link legado inequívoco. Reativar criação só quando `compare-controle` estiver limpo o suficiente: `--allow-create` ou `CONTROLE_PAUSE_CREATE=false`.

### 2 — Assinado no Autentique → quadro Contratos

- Fora do escopo imediato deste documento; depende de Tipo + Status no Controle, automação Monday e/ou `document.finished` (Drive + pipeline).
- **Como medir (futuro):** cruzar `signed_missing_in_monday` + itens em Contratos.

### 3 — Sem duplicatas no Controle

- Mesmo `Autentique ID` em mais de um item → duplicata.
- Mesmo título normalizado em mais de um item (sem ser o par Jan/Luciano esperado) → suspeita.
- **Como medir:** `compare-controle` → `duplicate_autentique_ids`, `duplicate_normalized_names`.
- **Como corrigir:** arquivar manualmente no Monday; scripts de cleanup quando existirem.

### 4 — Monday reflete o que está pendente no Autentique

- Cada fila (**Jan** / **Luciano**) tem status e **data de assinatura** próprios: só contam assinaturas de **Jan/Assinador** ou **Luciano/Beauty For All**, não de terceiros.
- Item no Controle com link para documento **já totalmente assinado** no Autentique mas status ainda “Aguardando…” → **desatualizado**.
- **Como medir:** `compare-controle` → `monday_track_status_mismatch`, `monday_status_behind_autentique`, `monday_multiple_autentique_ids`.
- **Reparo (um ID por item):** GitHub Actions → **Sync Controle Assinaturas** → `mode: repair`, `dry_run: true` (depois `false` para aplicar). Ou CLI: `repair-controle-autentique-links --dry-run --max-pages 50`.
- **Corrigir só divergências do compare (rápido):** `mode: reconcile-mismatches` ou CLI `reconcile-controle-mismatches` (atualiza track/status onde `monday_track_status_mismatch` / `monday_status_behind_autentique`; itens **inativos** no Monday são ignorados, não falham o job).
- **Como corrigir (varredura completa):** `sync-controle` (campo `legacy_linked` no JSON); workflow **Sync Controle Assinaturas** roda em cron (compare only no push/schedule).

## Plano antes de gravar (sync)

O sync classifica cada documento do Autentique **antes** de criar linha no Monday:

| Ação | Quando |
|------|--------|
| **CRIAR** | Pendente no Autentique e não há linha legada com título exato sem ID |
| **VINCULAR** | Existe linha (Jan/Luciano ou Assinado) com título exato **sem** Autentique ID |
| **ATUALIZAR** | Autentique ID já está no link do item |
| **IGNORAR** | Assinado sem legado correspondente (ou match ambíguo — revisão manual) |

`compare-controle` expõe `plan_action_counts` (mesma lógica, somente leitura). Com `--skip-signed-documents`, o sync ainda **vincula** e **atualiza** assinados; só adia **CRIAR** de novos assinados.

## Comandos

```bash
# Diagnóstico (não grava)
contratos-webhook compare-controle --max-pages 50

# Corrigir pendentes faltando + vínculo legado automático (título exato único)
# Criação pausada por padrão — use --allow-create só após saneamento do quadro
contratos-webhook sync-controle --create-only --skip-signed-documents --max-pages 50
contratos-webhook sync-controle --allow-create --create-only --skip-signed-documents --max-pages 50

# Desligar auto-link (raro)
contratos-webhook sync-controle --no-auto-link-legacy ...
```

Workflow GitHub: **Sync Controle Assinaturas (Autentique)** — modos `compare`, `repair`, `reconcile-mismatches`, `sync`.

### Catch-up operacional (Autentique → Monday, agora)

Ordem recomendada no workflow **Sync Controle Assinaturas**:

1. `mode=compare` — revisar `plan_action_counts` (`vincular` / `atualizar` / `criar` / `ignorar`).
2. `mode=sync`, `dry_run=true`, `create_only=false`, `skip_signed_documents=true`, `allow_create=false` — simula **só vínculo + atualização** (criação pausada).
3. `mode=sync`, `dry_run=false`, mesmos parâmetros — aplica vínculos legado e status.
4. Só então `allow_create=true` + `create_only=true` para pendentes **CRIAR** genuínos (nunca `skip_signed_documents=false` em massa).

### Catch-up recomendado (após compare limpo em track/status/multi-ID)

1. **compare** — artefato `controle-pending-export` (pending, signed missing, sugestões legado).
2. **validate_status_labels** — `validate_status_labels=true` no dispatch.
3. **sync** `dry_run=true`, `allow_create=true`, `create_only=false`, `skip_signed_documents=true`.
4. **sync** `dry_run=false`, mesmos parâmetros — cria pendentes + auto-link + atualiza existentes.
5. **Não** usar `skip_signed_documents=false` + `allow_create=true` em massa — isso recria filas para documentos **já assinados** quando existe legado **Assinado** sem Autentique ID (duplicatas na fila Luciano). Preferir `link-controle` ou `remediate-sync-duplicates`.
6. **reconcile-mismatches** — `light_autentique_feed=true` quando só há poucas divergências.
7. **pilot_bruno_distrato** — `pilot_bruno_dry_run=true`, depois `false`.
8. **compare** final.

### Remediação (duplicatas do sync)

```bash
# Listar candidatos (filas pendentes + doc assinado + legado Assinado com mesmo título)
contratos-webhook remediate-sync-duplicates --max-pages 100

# Arquivar no Monday (reversível)
contratos-webhook remediate-sync-duplicates --max-pages 100 --apply
```

Workflow: **Remediar duplicatas sync Controle** (`apply=false` primeiro).

**Itens inativos no Monday:** sync/reconcile ignoram com `skipped_inactive` (não atualizam colunas).

**Fase Contratos:** Tipo + Assinado (Jan) → automação Monday / `document.finished`. Ver `docs/cloud-agent-autonomia.md`.

## Regra de nome (resumo)

Ver `AGENTS.md`. Não fundir vários contratos do mesmo fornecedor (ex. `202505_BrassHill` vs `202503_BrassHill`). Vincular legado só com **ID** ou título **igual** (normalizado), ou evidência forte documentada em `controle_dedup.py`.

## Roadmap técnico

1. **Hoje:** compare + sync com auto-link legado + duas filas Jan/Luciano; cron no workflow **Sync Controle Assinaturas**.
2. **Próximo:** assinados → Contratos + colunas Monday.
3. **Depois:** match legado ambíguo via API/PDF (hash) quando título divergir.
