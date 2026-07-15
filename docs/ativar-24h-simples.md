# Ativar 24h — passo a passo simples

Para rodar **de hora em hora, 24h por dia**, siga estes passos.

---

## Por que não existe a pasta `credentials` no GitHub?

Essa pasta fica **só no servidor**, com arquivos secretos do Google. Ela **não aparece** no site do GitHub de propósito (segurança).  
Você **não precisa** procurar essa pasta no seu computador.

---

## Passo 1 — Secret do OAuth (só uma vez)

1. Abra: https://github.com/ivoalexandrino-png/ClassificacaoProcons/settings/secrets/actions
2. Crie o secret `GMAIL_OAUTH_JSON` com o JSON do cliente OAuth do Google (se ainda não existir).

---

## Passo 2 — Gerar o token pelo GitHub (sem pasta credentials)

1. Abra: https://github.com/ivoalexandrino-png/ClassificacaoProcons/actions/workflows/setup-google-token.yml
2. Clique em **Run workflow** → deixe o campo do código **vazio** → **Run workflow**
3. Abra a execução que acabou de rodar → clique no job **setup-token**
4. No log, copie o **link longo** que começa com `https://accounts.google.com/...`
5. Abra esse link no navegador, faça login com `ivo.alexandrino@b4a.com.br` e clique em **Permitir**
6. A página pode ficar em branco — normal. Na barra de endereço, copie o texto depois de `code=` (até o próximo `&`)
7. Volte em **Setup Google token** → **Run workflow** de novo → **cole o código** no campo → **Run workflow**
8. Na execução, em **Artifacts**, baixe **gmail-token**
9. Abra o arquivo `gmail-token.json` baixado, selecione **tudo** (Ctrl+A) e copie
10. Em Secrets, crie ou atualize `GMAIL_TOKEN_JSON` colando esse conteúdo inteiro

---

## Passo 3 — Testar

1. Abra: https://github.com/ivoalexandrino-png/ClassificacaoProcons/actions/workflows/procon-hourly.yml
2. Clique em **Run workflow** → **Run workflow**

Se der verde, está funcionando. Depois disso roda **sozinho a cada 1 hora**.

---

## Pronto!

O GitHub cuida de rodar 24h. Seu PC pode ficar desligado.

Para ver histórico: aba **Actions** no GitHub.
