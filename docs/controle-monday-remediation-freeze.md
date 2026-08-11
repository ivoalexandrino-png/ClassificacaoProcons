# Congelamento — remediation Monday / Controle Assinaturas

> **Status:** CONGELADO (2026-08-11).  
> **Decisão:** não investir mais na resolução do legado Monday. O código e os artefatos
> de diagnóstico **permanecem** no repositório; não serão descartados.

## O que está congelado

| Área | Estado |
|------|--------|
| Etapa 2 / 2.1 — plano de remediation (`controle-remediation-plan-v2.json`) | Referência histórica; **não executar** |
| Scripts `build_controle_remediation_plan.py`, `build_controle_consistency_audit.py` | Mantidos; sem evolução ativa |
| PRs de remediation / etapa 2 | Não mergear para execução; podem servir de arquivo |
| `CONTROLE_WRITE_ENABLED=false` | **Permanece** até decisão explícita contrária |
| `CONTROLE_PAUSE_CREATE=true` | **Permanece** |
| Auto-link legado, reparo de filas, archive em massa no Monday | **Fora de roadmap** |

## O que continua válido (read-only)

- `compare-controle` — diagnóstico Autentique ↔ Monday
- Webhooks Autentique → Cloud Run (sem ampliar escrita no Monday)
- Kill switch e políticas de escrita já em produção
- Artefatos em `artifacts/controle-etapa2/` e `artifacts/controle-etapa2-1/`

## Próximo foco

**Controle Assinaturas greenfield no Sunday** — ver `docs/controle-sunday-greenfield.md`.

Autentique permanece **source of truth**. O Sunday recebe apenas o estado derivado;
não há migração item-a-item do legado Monday como pré-requisito.

## Motivo do congelamento

A Etapa 2.1 mostrou que o legado Monday (1.607 itens, ~1.204 sem Autentique ID indexado,
314 candidatos a archive só por heurística de título/URL, 57 grupos de track ambíguo)
custa mais para sanear com segurança do que redesenhar o quadro no Sunday a partir do
feed Autentique com regras já validadas.
