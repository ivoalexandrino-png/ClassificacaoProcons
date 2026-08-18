# Binary asset migration (HYBRID_EXTERNAL_STORAGE_LINK_ATTACHMENT)

Monday `item.assets` → authenticated download → Google Drive → Sunday `add_link_attachment`.

FILE→LINK columns (`arquivos`, `arquivos8`) remain unchanged.

## Approval flow (binary)

1. **PLAN metadata** — asset IDs, filenames, sizes (no bytes).
2. **Final approval preflight (read-only)** — download from Monday, size check, SHA256.
3. **Final manifest** — each ATTACHMENT op commits `source_sha256` + storage key + Sunday target.
4. **Human authorization** — approval bundle with manifest hash.
5. **APPLY** — runtime preflight ALL assets (SHA256 vs approved) **before first write**; then Drive + Sunday.

No Drive upload during final PLAN preflight.

## Drive URL

Sunday receives stable URL: `https://drive.google.com/file/d/{file_id}/view`

- No `access_token` or signed query strings
- Requires Google auth for restricted files (not public-by-default)
- Upload code does **not** call permissions API (`anyoneWithLink` forbidden)

## Folder policy

Configure `MIGRATION_ASSETS_DRIVE_ROOT_FOLDER_ID` as restricted folder (Shared Drive recommended).
Run `inspect_migration_assets_folder_policy()` before pilot; `link_access_validated=false` blocks pilot until ACL confirmed.

## Credentials (APPLY only)

- `MONDAY_API_TOKEN`
- `MIGRATION_ASSETS_DRIVE_ROOT_FOLDER_ID`
- `GMAIL_OAUTH_JSON` / `GMAIL_TOKEN_JSON`
