# Modo manual (sem Cloud Run)

Enquanto o serviço 24h no Google Cloud não estiver no ar, dá para usar **botões no GitHub** para fazer quase tudo. Não precisa configurar webhooks no Autentique.

## O que já funciona sem Cloud Run

| O que você quer | Onde clicar no GitHub | Quando usar |
|-----------------|----------------------|-------------|
| **Tudo de uma vez** (Controle + assinados → Drive) | Actions → **Catch-up contratos** | Retomar atraso sem Cloud Run |
| Criar/atualizar itens no **Controle Assinaturas** | Actions → **Sync Controle Assinaturas** | Só Controle, sem processar assinados |
| Registrar **um** contrato específico | Actions → **Registrar contrato no Controle** | Só um documento novo (você tem o ID) |
| Processar contrato **totalmente assinado** (Drive + Monday) | Actions → **Test contrato assinado** | Depois que Jan e Luciano assinaram |

## Passo a passo — sincronizar tudo (recomendado)

1. Abra o repositório no GitHub → aba **Actions**
2. Escolha **Catch-up contratos (Autentique → Monday/Drive)**
3. Clique **Run workflow**
4. Primeira vez: deixe **dry_run = true** (só simula)
5. Veja o log — confira `sync_created`, `sync_updated`, `processed`
6. Se estiver ok, rode de novo com **dry_run = false**

Alternativa (só Controle, sem Drive):

1. Actions → **Sync Controle Assinaturas (Autentique)**
2. **Run workflow** com dry_run true/false conforme acima

**Resultado esperado:** itens novos no grupo **Jan** (com Tipo), sem duplicar os que já existem.

## Passo a passo — um contrato só

1. No Autentique, copie o **ID do documento**
2. Actions → **Registrar contrato no Controle**
3. Cole o ID → **Run workflow**

## Passo a passo — contrato assinado por completo

1. Actions → **Test contrato assinado (manual)**
2. Cole o ID do documento (ou deixe vazio para pegar o último assinado)
3. **Run workflow**

**Resultado esperado:** PDF no Drive, Controle → Assinado, item no board Contratos.

## O que ainda precisa do Cloud Run

| Função | Por quê |
|--------|---------|
| Webhooks do Autentique (`document.created`, `signature.accepted`, `document.finished`) | O Autentique precisa de uma URL pública na internet |
| Webhook do Monday (enriquecer Contratos automaticamente) | Mesmo motivo — URL pública |

## O que podemos adiantar no código (sem deploy)

- Implementar `signature.accepted` (atualizar status quando Jan ou Luciano assina) — **feito no código; ativo após deploy**
- Melhorar o sync para **atualizar** itens existentes (mover Jan → Luciano, status “Aguardando outros”) — **feito**
- Mesclar PRs pendentes no GitHub

## Secrets necessários no GitHub

Confirme em **Settings → Secrets and variables → Actions**:

- `MONDAY_API_TOKEN`
- `AUTENTIQUE_API_TOKEN`
- `GEMINI_API_KEY` (só para processar contrato assinado)
- `GMAIL_OAUTH_JSON` e `GMAIL_TOKEN_JSON` (só para Drive)
