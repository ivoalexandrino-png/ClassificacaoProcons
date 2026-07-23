# Proconsumidor — execução local

O portal `https://proconsumidor.mj.gov.br/#/login` bloqueia IPs de datacenter (cloud,
GitHub Actions `ubuntu-latest`, Cloud Agents). Por isso o Proconsumidor deve rodar em
máquina local no Brasil ou em runner self-hosted com IP permitido.

## Teste rápido (um e-mail)

1. Deixe o e-mail `Notificação de Carta` como **não lido**.
2. Exporte o token do Monday:

```bash
export MONDAY_API_TOKEN=seu_token
```

3. Execute:

```bash
bash scripts/run-proconsumidor-process.sh
```

## Agendar a cada hora (Mac/Linux)

```bash
export MONDAY_API_TOKEN=seu_token   # adicione ao ~/.zshrc ou ~/.bashrc
bash scripts/install-proconsumidor-cron.sh
```

Logs: `logs/proconsumidor.log`

## GitHub Actions (runner self-hosted)

1. No Mac/PC: **Settings → Actions → Runners → New self-hosted runner**
2. Instale o runner no repositório.
3. Dispare manualmente o workflow **Proconsumidor local processing**.

O runner usa os mesmos secrets (`GMAIL_*`, `MONDAY_API_TOKEN`) do job horário.

## Assuntos suportados

- `Proconsumidor - Notificação`
- `Notificação de Carta`
