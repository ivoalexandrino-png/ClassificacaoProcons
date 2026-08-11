# Controle Assinaturas — greenfield no Sunday

> **Status:** planejamento ativo (pós-congelamento Monday).  
> **Fonte da verdade:** Autentique (documentos, signatários, assinaturas, PDF).  
> **Destino:** Sunday — board Legal Controle de Assinaturas (workspace 22).  
> **Legado Monday:** não migrar como pré-requisito; ver `docs/controle-monday-remediation-freeze.md`.

## Princípios

1. **Autentique → Sunday** — cada documento elegível gera **N itens** conforme filas
   esperadas (`jan`, `luciano`), chave lógica `(autentique_document_id, track)`.
2. **Sem deduplicação por título** — identidade = `autentique_document_id` (+ track).
3. **Sem auto-archive por padrão de título** — escopo ineligible ignora criação; não
   arquivar legado Monday.
4. **Regras de domínio reutilizadas** — módulos Python existentes, sem acoplamento ao
   Monday transport/API.

## Módulos a reutilizar (já validados)

| Módulo | Responsabilidade |
|--------|------------------|
| `contratos/signer_identity.py` | Jan (`assinador@…`) vs Luciano (`juridico@…`); aliases de nome |
| `contratos/controle_required_tracks.py` | `resolve_expected_tracks` — filas a partir dos signatários |
| `contratos/controle_scope.py` | `classify_controle_scope` — eligible / ineligible / manual_review |
| `contratos/controle_status.py` | Status por fila vs estado Autentique (Aguardando / Assinado / …) |
| `contratos/controle_tipo.py` | Classificação Tipo (B2B, aditivo, RH, …) — heurística + Gemini quando necessário |
| `contratos/controle_autentique_terminal.py` | Documento totalmente assinado / terminal |
| `contratos/autentique/client.py` | Feed e metadados Autentique |

## Módulos Monday — não estender

| Módulo | Motivo |
|--------|--------|
| `monday_contracts.py` (escrita Controle) | Substituído por `sunday/client.py` (base em GO) |
| `controle_sync.py` / `controle_sync_remediation.py` | Lógica de sync legado; extrair só regras puras |
| `controle_reconcile.py` / dedup legado Monday | Não aplicável ao greenfield |
| Scripts etapa 2 remediation | Congelados |

## Modelo de dados Sunday (proposta)

### Board

- Nome alvo: **Legal - Controle de Assinaturas** (board produção Sunday; sandbox 80 para testes).
- Grupos: **Jan**, **Luciano**, **Assinados** (espelho operacional; configurar manualmente 1×).
- Coluna estrutural **Área**: ignorável pelo adapter (confirmado microteste F0.14).

### Colunas customizadas (config manual 1×)

| Coluna | Tipo Sunday | Uso |
|--------|-------------|-----|
| Autentique ID | text | Chave estável |
| Tipo | status custom | Valores de `controle_tipo` |
| Status negócio | status custom | **Não** system status; API `values/{col}` |
| Link assinatura | link | URL Autentique + metadados track |
| Relação → Contratos | board_relation | Quando existir board Contratos no Sunday |

### Identidade e filas

- Um item Sunday por `(autentique_document_id, track)`.
- Status de negócio atualizável via coluna custom (`teste_status_negocio` validado no sandbox).
- `board_relation` nativo com `source_board_id` correto (payload `{"links":[{"item_id":"…"}]}`).

## Fluxo alvo (v1)

```
Autentique webhook / polling
        │
        ▼
  classify_controle_scope
  resolve_expected_tracks
        │
        ▼
  sunday/client.py  ──►  criar/atualizar itens (Jan/Luciano)
        │
        ▼
  controle_status + controle_tipo  ──►  atualizar colunas
        │
        ▼
  documento assinado  ──►  mover grupo Assinados + gatilho Contratos (fase 2)
```

## Fora do escopo imediato

- Migração dos 1.607 itens Monday
- Execução de `controle-remediation-plan-v2.json`
- Regras etapa 2 pendentes (pedido B2B refinado, cessão/parceria) — avaliar só no contexto Sunday
- Automações Monday (Controle → Contratos)

## Dependências Fase 0 Sunday (já validadas)

- `sunday/client.py` — **GO** para implementar
- Status custom, `board_relation`, criação de item — microtestes A/B/C sandbox 80/81
- Schema de colunas — configuração manual aceitável (classe C)

## Próximos passos sugeridos

1. Implementar `sunday/client.py` (transporte + CRUD item + values).
2. Definir contrato de config (board/coluna IDs Sunday) via env/Secret Manager.
3. Novo comando `contratos-webhook sync-controle-sunday` — só Autentique → Sunday, sem Monday.
4. Testes unitários espelhando `tests/test_controle_*` com backend Sunday mockado.
