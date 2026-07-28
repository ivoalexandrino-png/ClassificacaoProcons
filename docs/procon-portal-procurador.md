# Portal Procon-SP — login procurador (gov.br)

## Contexto

Processos administrativos abertos após conversão da CIP **não trazem código de acesso** no e-mail. O acesso é via **gov.br** (CPF do procurador) e seleção da empresa (B4A / MMKT, etc.). No portal, PA ficam na aba **Processos administrativos**, separada de **Reclamações**.

## Automação

1. Salvar sessão Playwright após login manual (uma vez):

```bash
# Exemplo local — após login gov.br + empresa B4A
playwright codegen https://fornecedor2.procon.sp.gov.br/login --save-storage=credentials/procon-sp-storage.json
```

2. No Cloud Agent / GitHub Actions, configurar secret ou arquivo:

- `PROCON_SP_STORAGE_STATE_PATH` → caminho do JSON (ex.: `credentials/procon-sp-storage.json`)
- `PROCON_SP_COMPANY_HINT` → `B4A` (padrão)

3. O módulo `portal/procurador.py` usa essa sessão para ler CPF/nome na lista de PA e confirmar vínculo com a CIP no Monday.

Sem storage state, o cadastro de PA usa **heurística** (único item com “Gerou PA” = Sim) ou CPF quando disponível.

## Limitações

- Sessão gov.br expira; é preciso renovar o storage periodicamente.
- Várias empresas no mesmo login exigem troca no `mat-select` (hint `B4A`).
- Não substitui o fluxo por **código de acesso** (CIP com código no e-mail).
