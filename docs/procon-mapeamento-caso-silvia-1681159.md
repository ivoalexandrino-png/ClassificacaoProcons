# Mapeamento — Silvia Rafaela / 1624924 ↔ 1681159 (PA)

Documento de **mapeamento** (sem implementação). Objetivo: registrar como o Procon-SP trata este caso antes de mudar parser, Monday ou portal.

## Identidade única do caso

| Campo | Valor |
|--------|--------|
| Consumidora | **SILVIA RAFAELA DE PAULA CAMARGO** |
| CPF | 446.685.528-52 |
| E-mail | silviarafaela.camargo@gmail.com |
| Fornecedor | B4A Serviços de Tecnologia e Comércio S.A (CNPJ 13.475.001/0001-34) |
| Tema | Plano Premium / oferta não cumprida (classificação vestuário/oferta) |

## Dois protocolos, um único histórico

| Papel | Protocolo | Situação no Monday (28/07/2026) |
|--------|-----------|----------------------------------|
| **Reclamação original (CIP)** | **1624924/2026** | Item existente (`12455122069`) — cadastro via fluxo normal (e-mail CIP + portal + código) |
| **Processo administrativo (PA)** | **1681159/2026** | **Não existe** coluna de protocolo com este número — PA não passou pelo `process` |

**Regra de negócio acordada:** interações e avisos que chegarem só com **1681159/2026** referem-se ao **mesmo caso** já tratado sob **1624924/2026**, até haver regra automática de alias.

### Linha do tempo (portal — evidência)

1. **04/07/2026** — Protocolo **1624924/2026** atribuído; notificação CIP; defesa B4A em 08/07 (interação consumidora na mesma CIP).
2. **22/07/2026 ~14:21** — Nova mensagem da consumidora na linha da reclamação; protocolo **1681159/2026** atribuído no portal (“Protocolo de Atendimento Atribuído”).
3. **22/07/2026 ~14:22** — “Atendimento convertido em **Processo Administrativo**”; transferência DAOC; prazo fornecedor **03/08/2026**.
4. **22/07/2026** — E-mails Gmail na caixa jurídica: PA aberto (`35.001.003.26.1681159`), vários “Notificação de emissão de **Reclamação**”, **Interação do Consumidor** (corpo: `Protocolo: 1681159/2026`).

O ano **2026** é consistente no portal, nos e-mails (corpo) e no Monday da CIP.

## Por que `1681159/2026` “não existe” hoje

1. **Monday** só foi populado na abertura da **CIP** (`1624924/2026`). O PA é um **novo número de protocolo** no Procon; nosso cadastro **não duplica** item por PA nem atualiza protocolo na coluna.
2. **`process-interactions`** localiza item por **protocolo exato** → busca `1681159/2026` → falha → fila `pending_monday_item` (mensagem `19f8ad958032419b`, 22/07).
3. O caso **já foi respondido** no portal na trilha da CIP/PA; a automação de interação **não elabora resposta** — só timeline no Monday com @ jurídico/SAC.

## Lacunas de e-mail / automação (mapeadas, não corrigidas)

| E-mail (22/07) | Assunto / remetente | Por que não cadastrou o PA |
|----------------|---------------------|----------------------------|
| PA | `Processo Administrativo Aberto: 35.001.003.26.1681159` | Corpo sem código de acesso na API Gmail; parser SP exige código no corpo |
| CIP/Reclamação | `Fundação Procon-SP - Notificação de emissão de **Reclamação**` | Parser atual só reconhece “… emissão de **CIP**” |
| Interação | `Interação do Consumidor` + `Protocolo: 1681159/2026` | Sem código (“localize o protocolo”); depende de item Monday com esse protocolo |

**Acesso humano:** login **gov.br** na área do fornecedor Procon-SP (sem código de acesso no e-mail do PA). O Playwright atual do repo usa fluxo **código de acesso**, não sessão gov.br.

## Estado Gmail / pipeline (referência técnica)

- Interação processada com sucesso hoje: **1668179/2026** (outro caso).
- Pendente em `processed-interactions.json` (Actions cache): **1681159/2026**, `message_id` `19f8ad958032419b`, sem `access_code` no parse.
- PA `19f8ada00346eb60`: `fetch_notification` → `None` (corpo vazio).

## Decisões pendentes (antes de implementar)

1. **Alias de protocolo:** `1681159/2026` → item Monday de `1624924/2026` (fixo por caso ou tabela/config).
2. **Resolução genérica:** mesmo **CPF** + mesma fornecedora + PA convertido → não criar item; `create_update` no item da CIP.
3. **Assunto “Reclamação”:** tratar como equivalente a CIP para `process` (evita UNPARSED).
4. **PA sem código:** parse de HTML do PA; ou pular portal e só Monday update com texto do e-mail; ou integração gov.br (fora de escopo imediato).
5. **Coluna Monday:** manter protocolo **1624924/2026** como chave; updates de PA/interação citam **ambos** os números no corpo do update.

## Ação manual aceitável até haver código (opcional)

- Publicar **um** update no item **1624924/2026** mencionando PA **1681159/2026** e link mental ao processo administrativo — **não** criar segundo item.

---

**Próximo passo sugerido:** validar este mapeamento com jurídico; depois abrir issue/PR de implementação (alias + Reclamação + interação por CPF/protocolo canônico).
