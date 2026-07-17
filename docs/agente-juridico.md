# Agente Jurídico — intimações, prazos e audiências

Agente para o jurídico interno: recebe intimações/pushes por e-mail, identifica o
processo e o movimento, calcula prazos e audiências e registra as **providências**
no Monday para controle. Foi desenhado para, no futuro, acionar dois outros
agentes (ainda inexistentes) via interfaces bem definidas.

## Fluxo

```
Gmail (intimação/push)
      │  parse: nº CNJ, tribunal, vara, movimento, prazo, audiência
      ▼
Sistema de andamento (fonte plugável: e-mail hoje; portal amanhã)
      │  classificação da providência + cálculo do prazo (dias úteis)
      ▼
Monday  ──►  board jurídico (prazos e audiências)
      │
      ├─► [futuro] agente de peças processuais (elaborar/protocolar)
      └─► [futuro] agente de relatórios contingenciais (andamentos, depósitos, provisões)
```

## Comandos (`procon-juridico`)

```bash
procon-juridico auth                         # conectar o Gmail que recebe as intimações
procon-juridico parse --file intimacao.txt   # extrair dados de uma intimação (offline)
procon-juridico parse --file intimacao.html  # idem, a partir de HTML
procon-juridico list                         # listar intimações não lidas (JSON)
procon-juridico process                      # processar: providência + Monday
procon-juridico process --dry-run            # simular sem efeitos colaterais
```

O comando `parse` é 100% offline e é o núcleo do agente: dado o corpo de um
e-mail (arquivo `.txt`/`.html` ou `stdin`), retorna o processo e a providência
(tipo, prazo final e/ou audiência) em JSON.

Exemplo:

```bash
$ procon-juridico parse --file intimacao.txt
{
  "intimacao": {
    "process_number": "1023456-78.2026.8.26.0100",
    "tribunal": "TJSP",
    "vara": "3ª Vara Cível ...",
    "movement_type": "Sentença",
    "prazo_dias": 15,
    "publication_date": "2026-07-17",
    ...
  },
  "providencia": {
    "tipo": "Analisar recurso",
    "prazo_final": "2026-08-07",
    "status": "A providenciar",
    ...
  }
}
```

## Variáveis de ambiente

| Variável | Uso | Padrão |
|----------|-----|--------|
| `GMAIL_CREDENTIALS_PATH` / `GMAIL_TOKEN_PATH` | OAuth Google (compartilhado com o Procon) | `credentials/gmail-*.json` |
| `JURIDICO_GMAIL_QUERY` | Filtro Gmail das intimações | busca por intimação/andamento/audiência |
| `MONDAY_API_TOKEN` | Registro no Monday | — |
| `JURIDICO_MONDAY_BOARD_NAME` | Nome do board jurídico | `juridico` |
| `JURIDICO_MONDAY_BOARD_ID` | ID do board (prevalece sobre o nome) | — |
| `JURIDICO_MONDAY_GROUP_NAME` | Grupo do board | `prazos e audiencias` |

## Board do Monday

As colunas são associadas por **título** (normalizado, sem acento). Crie um board
com colunas cujos títulos contenham as palavras‑chave abaixo:

| Campo | Palavras‑chave no título | Tipo sugerido |
|-------|--------------------------|---------------|
| Processo | processo, cnj, autos | text |
| Tribunal | tribunal, comarca, foro | text |
| Vara | vara, juízo, juizado | text |
| Tipo/Movimento | tipo, movimento, classificação | text/status |
| Providência | providência, tarefa, ação | text/status |
| Prazo final | prazo final, prazo fatal, prazo, vencimento | date |
| Audiência | audiência, sessão | date |
| Status | status, situação | status |
| Partes | partes, autor, réu | text |
| Link | link, portal, url | link |

A deduplicação usa a coluna de **processo**: intimações do mesmo processo/movimento
não geram itens duplicados.

## Cálculo de prazos (importante — revisar com o jurídico)

`calculate_prazo_final` implementa uma versão **simplificada e documentada** das
regras do CPC/2015:

- Prazos processuais em **dias úteis** (art. 219); use `business_days=False` para
  prazos de direito material (dias corridos).
- Exclui o dia do começo, inclui o do vencimento (art. 224); a contagem inicia no
  **primeiro dia útil seguinte** à data de publicação.
- Fins de semana e feriados informados em `holidays` não são contados; vencimento
  em dia não útil é prorrogado.

O parser prioriza a data de **publicação** (“considera‑se publicado em …”) sobre a
de **disponibilização**. Feriados forenses variam por tribunal/comarca — informe‑os
em `holidays`. **Valide os prazos calculados antes de usar como prazo fatal.**

## Pontos de extensão para os dois agentes futuros

Definidos em `classificacao_procons.juridico.agents` como `Protocol`, com
implementações nulas (no-op) usadas por padrão:

- `PecaProcessualAgent.draft_and_file(processo, providencia)` — elaborar e
  protocolar peças. Hoje: `NullPecaProcessualAgent` → status `pendente_integracao`.
- `RelatorioContingenciaAgent.update_report(processo, andamento)` — atualizar
  relatórios contingenciais (andamentos, depósitos, provisões). Hoje:
  `NullRelatorioContingenciaAgent` → status `pendente_integracao`.

Basta injetar implementações concretas em `process_new_intimacoes(...)` quando os
agentes existirem — o pipeline não muda:

```python
process_new_intimacoes(
    options,
    peca_agent=MinhaIntegracaoDePecas(),
    relatorio_agent=MinhaIntegracaoDeRelatorios(),
)
```

O acesso ao sistema de andamento também é plugável
(`classificacao_procons.juridico.andamento.AndamentoSource`): hoje usa o próprio
e-mail (`EmailAndamentoSource`); o `PlaywrightAndamentoSource` é o esqueleto para
raspar o portal do tribunal (PJe/e-SAJ), seguindo o padrão do módulo `portal`.

## Testes

Tudo é validado offline (Gmail/Monday mockados):

```bash
ruff check src tests
pytest -q tests/test_juridico_*.py
```
