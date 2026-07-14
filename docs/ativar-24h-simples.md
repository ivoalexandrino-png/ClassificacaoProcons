# Ativar 24h — passo a passo simples

Para rodar **de hora em hora, 24h por dia**, siga estes 3 passos.

---

## Passo 1 — Aprovar o código (merge)

Abra e clique em **Merge** neste PR:

https://github.com/ivoalexandrino-png/ClassificacaoProcons/compare/main...cursor/email-parser-procon-fdb8

---

## Passo 2 — Configurar senhas no GitHub (2 minutos)

1. Abra: https://github.com/ivoalexandrino-png/ClassificacaoProcons/settings/secrets/actions
2. Clique em **New repository secret**
3. Crie o primeiro:
   - Name: `GMAIL_OAUTH_JSON`
   - Secret: cole o conteúdo do arquivo `credentials/gmail-oauth.json`
4. Clique em **New repository secret** de novo
5. Crie o segundo:
   - Name: `GMAIL_TOKEN_JSON`
   - Secret: cole o conteúdo do arquivo `credentials/gmail-token.json`

> Se não tiver esses arquivos no seu PC, me avise que te ajudo a gerar de novo.

---

## Passo 3 — Testar

1. Abra: https://github.com/ivoalexandrino-png/ClassificacaoProcons/actions
2. Clique em **Procon hourly processing**
3. Clique em **Run workflow** → **Run workflow**

Se der verde, está funcionando. Depois disso roda **sozinho a cada 1 hora**.

---

## Pronto!

O GitHub cuida de rodar 24h. Seu PC pode ficar desligado.

Para ver histórico: aba **Actions** no GitHub.
