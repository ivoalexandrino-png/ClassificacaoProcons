# ClassificacaoProcons

Agente de triagem e cadastro de reclamações do Procon-SP.

## Escopo atual (MVP — e-mail)

Monitora a caixa de entrada do Gmail em busca de notificações de CIP do Procon-SP e extrai:

- **URL do portal** (`fornecedor2.procon.sp.gov.br`)
- **Código de acesso** (único por reclamação)

### Critérios de identificação

| Campo | Valor |
|-------|-------|
| Remetente | `procon.naoresponder@procon.sp.gov.br` |
| Assunto | `Fundação Procon-SP - Notificação de emissão de CIP` |

## Pré-requisitos

- Python 3.11+
- Projeto no [Google Cloud Console](https://console.cloud.google.com/) com **Gmail API** habilitada
- Credenciais OAuth 2.0 (tipo "Desktop app") salvas em `credentials/gmail-oauth.json`

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuração do Gmail

1. Crie credenciais OAuth no Google Cloud Console (Gmail API habilitada).
2. Baixe o JSON e salve como `credentials/gmail-oauth.json` (não commitar).
3. Na primeira execução, o fluxo OAuth abrirá o navegador e salvará o token em `credentials/gmail-token.json`.

Variáveis opcionais:

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `GMAIL_CREDENTIALS_PATH` | `credentials/gmail-oauth.json` | Client secrets OAuth |
| `GMAIL_TOKEN_PATH` | `credentials/gmail-token.json` | Token autorizado |

## Uso

### Conectar Google (Gmail + Drive)

```bash
procon-email auth
```

### Processar reclamações novas (fluxo automático)

```bash
procon-email process
```

Isso faz, para cada e-mail **não lido** do Procon:
1. Lê o e-mail e extrai o código
2. Acessa o portal e baixa o PDF
3. Cria pasta no Drive (nome da consumidora) e salva o PDF
4. Marca o e-mail como lido

Simular sem executar:

```bash
procon-email process --dry-run
```

### Comandos individuais

```bash
procon-email list          # listar e-mails não lidos
procon-portal --code "..." # só portal
procon-drive --consumer-name "..." --pdf downloads/arquivo.pdf
```


Saída (JSON):

```json
[
  {
    "message_id": "abc123",
    "subject": "Fundação Procon-SP - Notificação de emissão de CIP",
    "sender": "procon.naoresponder@procon.sp.gov.br",
    "received_at": "2025-07-14T10:00:00+00:00",
    "portal_url": "https://fornecedor2.procon.sp.gov.br/login",
    "access_code": "ABC123-XYZ789"
  }
]
```

## Uso programático (parser)

Para testar o parser com o corpo de um e-mail, sem Gmail:

```python
from classificacao_procons.email import parse_procon_notification_body

result = parse_procon_notification_body(html=email_html)
print(result.portal_url, result.access_code)
```

## Próximas etapas

- [ ] Portal Procon: login + código → extrair dados e PDF
- [ ] Google Drive: criar pasta e upload do PDF
- [ ] Monday.com: cadastro em "pendentes de resposta"

## Validação

```bash
ruff check src tests
pytest
```

## Product

_Pendente definição no registry B4A._

## Owner

_Pendente._

## Environments

_Pendente (stg/prd)._
