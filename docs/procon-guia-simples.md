# Procon automático — guia simples (sem terminal)

Você **não precisa** configurar GCP nem rodar comandos para o fluxo básico funcionar. O GitHub já roda o robô várias vezes por hora.

## O que acontece sozinho

1. Chega e-mail do **Procon-SP** (ou outros Procons) na caixa **financeiro/jurídico**.
2. O GitHub (**Procon automation (every 30 min)**) lê o e-mail, baixa o PDF, salva no Drive e **cria o caso no Monday**.
3. O Monday manda o e-mail para o SAC (“novo caso no Monday”).
4. Na **hora cheia** (UTC), o mesmo robô tenta **elaborar a resposta** (se já tiver Docs SAC no Monday).

Horários são em **UTC** no GitHub; no Brasil costuma ser ~3h a menos (ex.: 07:00 UTC ≈ 04:00 em São Paulo).

---

## Se um caso demorou — dispare na mão (1 minuto)

1. Abra: https://github.com/ivoalexandrino-png/ClassificacaoProcons/actions/workflows/procon-hourly.yml  
2. Botão **Run workflow** (à direita).  
3. Branch: **main**.  
4. Deixe **skip_elaborate** desmarcado se quiser processar **e** elaborar; marque se só quiser **cadastrar no Monday**.  
5. **Run workflow**.  
6. Espere ~2–5 min e abra a linha verde; se ficar vermelha, chame alguém de TI com o link da run.

Isso substitui o “rodar no terminal”.

---

## Token `procon-gcp-scheduler` (opcional — só TI)

Só é necessário se a empresa quiser **backup no Google Cloud** quando o GitHub falhar por muitas horas.

Quem tiver acesso ao **GCP** roda **uma vez**:

`bash scripts/setup-gcp-github-procon-scheduler.sh`

(com `PROJECT_ID` e o PAT que você já criou). Detalhes: `docs/gcp-procon-github-scheduler.md`.

**Você não precisa fazer isso** para o dia a dia se o passo “Run workflow” ou as runs automáticas estiverem verdes.

---

## O que pedir para TI / Cursor (se quiser que o agente dispare sozinho)

1. Cadastrar o PAT **procon-gcp-scheduler** como secret **`GITHUB_ACTIONS_PAT`** no **Cursor → Cloud Agents → Secrets** (não commitar no repo).  
2. Opcional: mesmo secret no **GCP Secret Manager** + script do Scheduler (acima).

---

## Segurança do token

Se o PAT apareceu em print ou chat, no GitHub: **Fine-grained tokens → procon-gcp-scheduler → Regenerate token**, copie o novo e guarde no gerenciador de senhas. Não envie o token por e-mail.
