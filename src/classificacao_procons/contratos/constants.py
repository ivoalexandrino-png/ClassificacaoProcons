"""IDs e rótulos fixos dos quadros Monday e pastas do Drive."""

from __future__ import annotations

# Google Drive — pasta raiz "2. Contratos"
DRIVE_ROOT_CONTRATOS_ID = "1UiWRh2iL-ee8ozZxmkeaZSI0Lned9r1y"
DRIVE_FOLDER_CONTRATOS_ID = "1WLO6pvT9aCsqJPfzasCdbZVf7F9esoVj"
DRIVE_FOLDER_LOCACAO_ID = "1GHo8YNgeXhC6K0uJwETU6Nq0fB0zn3nc"
DRIVE_FOLDER_MINUTAS_ID = "1GuGalt896VtVs75zOvbXBfrwRtjWKnB7"

# Subpastas em "1 - Contratos" (DRIVE_FOLDER_CONTRATOS_ID)
DRIVE_SUBFOLDER_RH_CLT = "RH - CLT"
DRIVE_SUBFOLDER_RH_PJ = "RH - PJ"

# Nomes legíveis das pastas raiz (para logs e resultado do pipeline)
DRIVE_ROOT_FOLDER_NAMES: dict[str, str] = {
    DRIVE_FOLDER_CONTRATOS_ID: "1 - Contratos",
    DRIVE_FOLDER_LOCACAO_ID: "2 - Contratos de Locação - Imóveis",
    DRIVE_FOLDER_MINUTAS_ID: "3 - Minutas padrões",
}

# Monday boards
MONDAY_CONTROLE_ASSINATURAS_BOARD_ID = "5301515799"
MONDAY_CONTRATOS_BOARD_ID = "5385471914"

# Controle Assinaturas — grupos
CONTROLE_GROUP_ASSINADOS = "novo_grupo"

# Controle Assinaturas — colunas
CONTROLE_COL_STATUS = "status"
CONTROLE_COL_DATA_ASSINATURA = "data0"
CONTROLE_COL_LINK_ASSINADO = "link"
CONTROLE_COL_LINK_ASSINATURA = "long_text_mkvnwp6d"
CONTROLE_COL_TIPO = "status_1__1"

# Controle Assinaturas — status (labels)
CONTROLE_STATUS_ASSINADO = "Assinado"
CONTROLE_STATUS_AGUARDANDO_OUTROS = "Aguardando outros"

# Contratos — grupos (board 5385471914)
MONDAY_GROUP_CONTRATOS_TRABALHO_CLT = "Contratos de Trabalho (CLT)"
MONDAY_GROUP_CONTRATOS_PJ = "Contratos PJ (Interno)"

CONTRATOS_GROUP_BY_TIPO: dict[str, str] = {
    "Contratos B4A": "topics",
    "Contratos MMKT": "novo_grupo",
    "Contratos Itaro": "novo_grupo9189",
    "Contratos RV BVI": "novo_grupo97670",
    "Contratos Aurora": "novo_grupo73906",
    "Contratos Societários": "novo_grupo11905",
    "Contratos B2B": "novo_grupo525",
    "Contratos de Câmbio": "novo_grupo__1",
    "NDA": "novo_grupo28073",
    "Contratos Influencers (Queens)": "novo_grupo67322",
    "Contratos Jan": "contratos_jan__1",
    "Pedidos Marcas Próprias": "topics",
    MONDAY_GROUP_CONTRATOS_TRABALHO_CLT: MONDAY_GROUP_CONTRATOS_TRABALHO_CLT,
    MONDAY_GROUP_CONTRATOS_PJ: MONDAY_GROUP_CONTRATOS_PJ,
}

# Grupos criados dinamicamente no Monday (título = chave de lookup)
DYNAMIC_CONTRATOS_GROUP_TITLES = frozenset(
    {
        MONDAY_GROUP_CONTRATOS_TRABALHO_CLT,
        MONDAY_GROUP_CONTRATOS_PJ,
    }
)

DEFAULT_CONTRATOS_GROUP_ID = "topics"

# Minutas padrões — subpastas de 2º nível no Drive
MINUTAS_SUBFOLDER_BY_CATEGORY: dict[str, str] = {
    "b2b": "Comercial - B2B",
    "influencer": "Influenciadores",
    "marcas_proprias": "Fornecimento Exclusivo (Marcas Proprias)",
    "transportadora": "Transportadoras",
    "consignacao": "Consignação",
    "nda": "NDA",
    "terceirizados": "Terceirizados",
    "imagem": "Autorizações de imagem",
}
