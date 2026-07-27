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


def signed_date_label(*, signed_date: date | None = None) -> str:
    reference = signed_date or date.today()
    return reference.strftime("%d/%m/%Y")


def analysis_prompt(
    *,
    consumer_name: str,
    protocol_number: str,
    complaint_excerpt: str,
    use_pdf_attachment: bool,
) -> str:
    source = (
        "Analise o PDF da reclamação anexo"
        if use_pdf_attachment
        else "Analise o texto da reclamação abaixo"
    )
    body = (
        "Você é advogado(a) de defesa do consumidor em resposta ao Procon-SP.\n"
        f"Consumidor: {consumer_name}\n"
        f"Protocolo: {protocol_number}\n\n"
        f"{source} e produza:\n"
        "1) resumo objetivo dos fatos alegados;\n"
        "2) pontos jurídicos relevantes;\n"
        "3) riscos e oportunidades de defesa.\n"
        "Responda em português do Brasil."
    )
    if use_pdf_attachment:
        return body
    return f"{body}\n\nTEXTO DA RECLAMAÇÃO:\n{complaint_excerpt}"


def draft_prompt(
    *,
    analysis: str,
    sac_summary: str,
    supporting_list: str,
    signed_date: str,
    defendant_legal_block: str = "",
) -> str:
    legal_section = f"{defendant_legal_block}\n\n" if defendant_legal_block else ""
    return (
        "Com base na análise abaixo e no relato do SAC, redija uma resposta inicial ao Procon.\n\n"
        f"{legal_section}"
        f"ANÁLISE:\n{analysis}\n\n"
        f"RELATO DO SAC:\n{sac_summary}\n\n"
        f"DOCUMENTOS ANEXADOS PELO SAC:\n{supporting_list}\n\n"
        "Regras obrigatórias:\n"
        "- Retorne SOMENTE o texto da resposta oficial ao Procon.\n"
        "- Não inclua prefácios, comentários meta ou explicações sobre o texto.\n"
        "- Inicie diretamente com o endereçamento formal (ex.: ILUSTRÍSSIMO...).\n"
        f"- No fecho, use a data real: São Paulo, {signed_date}.\n"
        "- Não use placeholders como [Data Atual].\n"
        "- Nunca invente CNPJ, razão social ou endereço da reclamada.\n"
        f"{PLAIN_TEXT_RULES}"
        "A resposta deve ser formal, clara e fundamentada nos documentos."
    )


def rewrite_prompt(
    *,
    draft: str,
    signed_date: str,
    defendant_legal_block: str = "",
) -> str:
    legal_section = f"{defendant_legal_block}\n\n" if defendant_legal_block else ""
    return (
        "Reescreva a resposta abaixo tornando-a mais detalhada, persuasiva e bem fundamentada, "
        "sem inventar fatos que não estejam na análise ou no relato do SAC.\n\n"
        f"{legal_section}"
        "Regras obrigatórias:\n"
        "- Retorne SOMENTE o texto final da resposta ao Procon.\n"
        "- Proibido prefácios como 'Aqui está uma versão reestruturada' ou separadores '---'.\n"
        "- Inicie diretamente com o endereçamento formal.\n"
        f"- No fecho, use a data real: São Paulo, {signed_date}.\n"
        "- Não use placeholders como [Data Atual].\n"
        "- Nunca invente CNPJ, razão social ou endereço da reclamada.\n"
        f"{PLAIN_TEXT_RULES}\n"
        f"RESPOSTA ATUAL:\n{draft}"
    )


def portal_summary_prompt(*, final_response: str) -> str:
    return (
        "Resuma a resposta abaixo para o campo de resposta do portal do Procon-SP, "
        f"com no máximo {MAX_PORTAL_CHARACTERS} caracteres, mantendo os argumentos centrais.\n"
        "Não use markdown. Retorne apenas o texto final.\n\n"
        f"RESPOSTA COMPLETA:\n{final_response}"
    )
