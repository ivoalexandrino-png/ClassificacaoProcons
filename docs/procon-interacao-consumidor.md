# Interação do consumidor (Procon-SP) — v1

## Gatilho

- Assunto contendo **Interação do Consumidor**
- Remetente `procon.naoresponder*@procon.sp.gov.br`
- Protocolo `NNNNNNN/AAAA` no corpo do e-mail

## Comportamento

1. **Não** cria item no Monday.
2. Localiza item existente pela coluna de protocolo e publica **update** com menções a `walquiria.marquart@b4a.com.br` e `manu@b4a.com.br`.
3. Lê a aba **Interações & Respostas** no portal (somente blocos do consumidor).
4. Lista anexos do e-mail e rótulos de anexo do portal no update.
5. **Não** altera prazos, status nem dispara elaboração automática.

## Fila `pending`

Se o item Monday ainda não existir (CIP ainda não processada), a interação fica em `data/processed-interactions.json` até o `process` cadastrar o protocolo; então o flush roda automaticamente.

## CLI / automação

```bash
procon-email process-interactions --max-results 20
procon-email process-interactions --skip-portal   # só e-mail
```

O workflow **Procon automation (every 30 min)** executa `process-interactions` após `process`.

## Fora do escopo v1

- E-mail **Inclusão de Resposta em Sistema**
- Upload de anexos para coluna file do Monday (apenas nomes no update)
- Subpasta Drive `Interacao consumidor/` (fase 2)
