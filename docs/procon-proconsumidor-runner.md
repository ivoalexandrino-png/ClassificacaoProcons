# Runner self-hosted — Proconsumidor (MJ)

O portal **proconsumidor.mj.gov.br** bloqueia IPs de datacenter (HTTP **403**). O workflow **Proconsumidor local processing** não roda em `ubuntu-latest`; precisa de um **runner no Brasil** (escritório ou Mac em casa).

## Checklist rápido

1. [ ] Máquina com acesso ao portal (abra `https://proconsumidor.mj.gov.br/` — não pode ser 403).
2. [ ] Credenciais Monday no board **Acessos** para elemento **Proconsumidor** (login/senha do portal).
3. [ ] Runner registrado no repositório com label **`procon-br`**.
4. [ ] Secrets do repo já usados pelo hourly: `GMAIL_OAUTH_JSON`, `GMAIL_TOKEN_JSON`, `MONDAY_API_TOKEN`.

## Instalar o runner (Linux ou macOS)

1. No GitHub: **Settings → Actions → Runners → New self-hosted runner** — copie o **token** (válido ~1 hora).

2. Na máquina (Brasil):

```bash
git clone https://github.com/ivoalexandrino-png/ClassificacaoProcons.git
cd ClassificacaoProcons
export RUNNER_REGISTRATION_TOKEN="cole_o_token_aqui"
bash scripts/setup-github-proconsumidor-runner.sh
```

O script valida o portal, baixa o Actions Runner, registra com labels `self-hosted,procon-br` e (no Linux) instala serviço **systemd**.

3. Disparar teste:

```bash
gh workflow run "Proconsumidor local processing" -f max_results=5
gh run list --workflow="Proconsumidor local processing" --limit 3
```

O job deve sair de **queued** e ficar **verde** (ou warning 403 se o IP ainda for bloqueado).

## Sem GitHub Actions (cron local)

Se preferir não manter runner, use o mesmo host com cron:

```bash
export MONDAY_API_TOKEN="..."
# credentials/gmail-token.json já configurado (procon-email auth)
bash scripts/run-proconsumidor-process.sh
```

Agende com `crontab` (ex.: a cada 30 min). O estado `data/processed-protocols.json` fica **só nesta máquina** — o hourly na nuvem não vê esse arquivo, mas como o hourly **não** processa `proconsumidor`, não há conflito de fonte. Após sucesso, o e-mail é marcado como lido no Gmail.

Para alinhar deduplicação com o workflow Actions, prefira o runner (cache `data/` compartilhado com o hourly).

## Backup de disparo (GCP Cloud Scheduler)

Se o cron do GitHub atrasar, crie um job que chama `workflow_dispatch`:

```bash
export GITHUB_ACTIONS_PAT="github_pat_..."   # Actions: Read and write
export PROJECT_ID="b4a-prj-SEU-SLUG-stg"
bash scripts/setup-gcp-github-proconsumidor-scheduler.sh
```

Agenda padrão: minutos **:10** e **:40** (horário de Brasília). O runner ainda precisa estar online.

## VM no GCP (cuidado)

VM em `southamerica-east1` **pode** continuar com 403 (IP de cloud). Só use se `curl -I https://proconsumidor.mj.gov.br/` retornar 200/302. Em dúvida, use Mac/PC do escritório.

## O que não muda

- Workflow **Procon automation (every 30 min)** segue só `sp,sc,alerj,campinas,uberlandia` em `ubuntu-latest`.
- Mutex `procon-pipeline-mutex` evita `process` simultâneo entre hourly e Proconsumidor quando ambos usam cache `data/`.
