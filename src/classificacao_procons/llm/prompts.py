"""Prompts compartilhados para elaboração de resposta ao Procon."""

from __future__ import annotations

from datetime import date

MAX_PORTAL_CHARACTERS = 1024

PLAIN_TEXT_RULES = (
    "- Formato: texto corrido em português, sem markdown.\n"
    "- Proibido usar *, **, #, ###, ---, > ou outros marcadores de formatação.\n"
    "- Use títulos de seção em MAIÚSCULAS (ex.: I. BREVE SÍNTESE DA RECLAMAÇÃO).\n"
    "- Separe parágrafos com uma linha em branco.\n"
)


def sac_authority_rules() -> str:
    return (
        "POSICIONAMENTO DO SAC (PRIORIDADE MÁXIMA — NÃO CONTRADIZER):\n"
        "- O relato e os documentos do SAC definem os fatos internos e a decisão da empresa "
        "(o que foi oferecido, negado, enviado, cancelado, estornado, etc.).\n"
        "- A resposta ao Procon DEVE refletir essa posição. É proibido conceder benefícios, "
        "envio de brindes/produtos, reembolsos, trocas ou 'acordo' que o SAC não autorizou.\n"
        "- Se o SAC informa que o consumidor não tem direito a algo ou que a empresa não "
        "dará prosseguimento ao pedido, a resposta deve sustentar esse indeferimento — "
        "não invente boa-fé, envio de itens ou satisfação voluntária contrária ao SAC.\n"
        "- Distinga sempre o pedido do consumidor da posição oficial da empresa (SAC).\n"
    )


def signed_date_label(*, signed_date: date | None = None) -> str:
    reference = signed_date or date.today()
    return reference.strftime("%d/%m/%Y")


def analysis_prompt(
    *,
    consumer_name: str,
    protocol_number: str,
    complaint_excerpt: str,
    use_pdf_attachment: bool,
    sac_summary: str = "",
) -> str:
    source = (
        "Analise o PDF da reclamação anexo"
        if use_pdf_attachment
        else "Analise o texto da reclamação abaixo"
    )
    body = (
        "Você é advogado(a) que elabora resposta da EMPRESA (fornecedora) ao Procon-SP.\n"
        f"Consumidor: {consumer_name}\n"
        f"Protocolo: {protocol_number}\n\n"
        f"{source} e produza:\n"
        "1) resumo objetivo do que o consumidor alega e pede;\n"
        "2) posicionamento da empresa conforme o SAC (não recomende conceder o que o SAC negou);\n"
        "3) argumentos jurídicos para sustentar a posição da empresa.\n"
        "Responda em português do Brasil."
    )
    sac_block = ""
    if sac_summary.strip():
        sac_block = (
            f"\n\n{sac_authority_rules()}\n"
            f"RELATO DO SAC (fonte da posição da empresa):\n{sac_summary.strip()}\n"
        )
    if use_pdf_attachment:
        return body + sac_block
    return f"{body}{sac_block}\n\nTEXTO DA RECLAMAÇÃO:\n{complaint_excerpt}"


def draft_prompt(
    *,
    analysis: str,
    sac_summary: str,
    supporting_list: str,
    signed_date: str,
    defendant_legal_block: str = "",
) -> str:
    legal_section = f"{defendant_legal_block}\n\n" if defendant_legal_block else ""
    sac_section = (
        (
            f"{sac_authority_rules()}\nRELATO DO SAC (obrigatório na resposta):\n"
            f"{sac_summary.strip()}\n\n"
        )
        if sac_summary.strip()
        else f"{sac_authority_rules()}\n"
    )
    return (
        "Redija a resposta oficial da EMPRESA ao Procon, alinhada ao SAC.\n\n"
        f"{legal_section}"
        f"{sac_section}"
        f"ANÁLISE (contexto; não sobrescreva o SAC):\n{analysis}\n\n"
        f"DOCUMENTOS ANEXADOS PELO SAC:\n{supporting_list}\n\n"
        "Regras obrigatórias:\n"
        "- Retorne SOMENTE o texto da resposta oficial ao Procon.\n"
        "- A conclusão prática (conceder ou negar pedido, enviar ou não enviar itens) "
        "deve ser a mesma do SAC.\n"
        "- Não inclua prefácios, comentários meta ou explicações sobre o texto.\n"
        "- Inicie diretamente com o endereçamento formal (ex.: ILUSTRÍSSIMO...).\n"
        f"- No fecho, use a data real: São Paulo, {signed_date}.\n"
        "- Não use placeholders como [Data Atual].\n"
        "- Nunca invente CNPJ, razão social ou endereço da reclamada.\n"
        f"{PLAIN_TEXT_RULES}"
        "Tom formal, claro e fundamentado no SAC e na análise."
    )


def rewrite_prompt(
    *,
    draft: str,
    signed_date: str,
    defendant_legal_block: str = "",
    sac_summary: str = "",
) -> str:
    legal_section = f"{defendant_legal_block}\n\n" if defendant_legal_block else ""
    sac_section = (
        f"{sac_authority_rules()}\nRELATO DO SAC:\n{sac_summary.strip()}\n\n"
        if sac_summary.strip()
        else ""
    )
    return (
        "Reescreva a resposta abaixo com mais detalhes jurídicos, "
        "SEM alterar a conclusão do SAC (o que a empresa concede ou nega).\n\n"
        f"{legal_section}"
        f"{sac_section}"
        "Regras obrigatórias:\n"
        "- Retorne SOMENTE o texto final da resposta ao Procon.\n"
        "- Proibido inventar envio de produtos, brindes, reembolsos ou acordo "
        "que contradigam o SAC.\n"
        "- Proibido prefácios como 'Aqui está uma versão reestruturada' ou separadores '---'.\n"
        "- Inicie diretamente com o endereçamento formal.\n"
        f"- No fecho, use a data real: São Paulo, {signed_date}.\n"
        "- Não use placeholders como [Data Atual].\n"
        "- Nunca invente CNPJ, razão social ou endereço da reclamada.\n"
        f"{PLAIN_TEXT_RULES}\n"
        f"RESPOSTA ATUAL:\n{draft}"
    )


def sac_consistency_prompt(*, sac_summary: str, response_text: str) -> str:
    return (
        "Revise a resposta ao Procon quanto ao alinhamento com o SAC.\n\n"
        f"{sac_authority_rules()}\n"
        f"RELATO DO SAC:\n{sac_summary.strip()}\n\n"
        f"RESPOSTA AO PROCON:\n{response_text.strip()}\n\n"
        "Se a resposta contradizer o SAC em fatos ou conclusão (ex.: SAC nega envio de "
        "brinde e a resposta afirma que enviou, concedeu ou acordou envio), reescreva a "
        "resposta inteira alinhada ao SAC, em tom formal ao Procon. "
        "Se já estiver alinhada, repita a resposta sem mudanças. "
        "Retorne SOMENTE o texto da resposta ao Procon."
    )


def portal_summary_prompt(*, final_response: str) -> str:
    return (
        "Resuma a resposta abaixo para o campo de resposta do portal do Procon-SP, "
        f"com no máximo {MAX_PORTAL_CHARACTERS} caracteres, mantendo os argumentos centrais.\n"
        "Não use markdown. Retorne apenas o texto final.\n\n"
        f"RESPOSTA COMPLETA:\n{final_response}"
    )
