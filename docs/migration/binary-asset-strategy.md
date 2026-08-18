# Binary asset migration (HYBRID_EXTERNAL_STORAGE_LINK_ATTACHMENT)

Monday `item.assets` (update attachments) are materialized via authenticated
Monday download, stored in durable Google Drive (`MIGRATION_ASSETS_DRIVE_ROOT_FOLDER_ID`),
and referenced in Sunday via `add_link_attachment`.

FILE→LINK columns (`arquivos`, `arquivos8`) remain unchanged.

## Required credentials (APPLY only)

- `MONDAY_API_TOKEN`
- `MIGRATION_ASSETS_DRIVE_ROOT_FOLDER_ID`
- `GMAIL_OAUTH_JSON` / `GMAIL_TOKEN_JSON` (Drive upload)

## PLAN vs APPLY

- PLAN uses asset metadata only (`monday_asset_metadata.py`).
- APPLY downloads, verifies size/hash, uploads/adopts storage, then creates Sunday link attachment.

## Idempotency

- Storage: deterministic key `monday/<board>/<item>/<asset_id>/<filename>` + SHA256 appProperties.
- Sunday: filename contains marker `[monday-asset:<board>:<item>:<asset_id>]`.
