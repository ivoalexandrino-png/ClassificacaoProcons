"""Orquestração de provedores de IA para resposta ao Procon."""

from __future__ import annotations

from pathlib import Path

from classificacao_procons.gemini.client import (
    GeminiClientError,
    GeneratedResponse,
    _gemini_request,
    _ordered_model_candidates,
    _pdf_part,
    apply_multa_replacement,
    enforce_portal_character_limit,
    finalize_procon_response_text,
    get_api_key_from_env,
    get_model_from_env,
    list_generate_content_models,
    normalize_model_name,
    resolve_gemini_model,
)
from classificacao_procons.llm import prompts
from classificacao_procons.llm.defendant_legal import (
    defendant_legal_prompt_block,
    replace_unauthorized_cnpjs,
    resolve_defendant_legal_profile,
)
from classificacao_procons.llm.openai_client import (
    chat_completion,
    resolve_openai_model,
)
from classificacao_procons.llm.openai_client import (
    get_api_key_from_env as get_openai_api_key_from_env,
)
from classificacao_procons.llm.pdf_text import extract_pdf_text_soft, resolve_complaint_text

_OPENAI_SYSTEM = (
    "Você é advogado(a) especializado em defesa do fornecedor em reclamações no Procon-SP. "
    "Siga instruções de formato à risca."
)


def _is_quota_or_rate_limit_error(exc: BaseException) -> bool:
    message = str(exc).casefold()
    markers = (
        "http 429",
        "resource_exhausted",
        "quota",
        "rate limit",
        "limite",
        "cota",
    )
    return any(marker in message for marker in markers)


def _is_retryable_across_models(exc: BaseException) -> bool:
    message = str(exc)
    return _is_quota_or_rate_limit_error(exc) or any(
        code in message for code in ("HTTP 503", "HTTP 502", "HTTP 504")
    )


def _gemini_text_with_model_fallback(
    *,
    api_key: str,
    model_candidates: list[str],
    parts: list[dict[str, object]],
) -> tuple[str, str]:
    last_error: GeminiClientError | None = None
    for candidate_model in model_candidates:
        try:
            text = _gemini_request(api_key=api_key, model=candidate_model, parts=parts)
            return text, candidate_model
        except GeminiClientError as exc:
            last_error = exc
            if not _is_retryable_across_models(exc):
                raise
    if last_error is not None:
        raise last_error
    raise GeminiClientError("Gemini indisponível para todos os modelos candidatos.")


def _apply_defendant_legal_guards(text: str, *, complaint_text: str) -> str:
    profile = resolve_defendant_legal_profile(complaint_text=complaint_text)
    return replace_unauthorized_cnpjs(text, profile=profile)


def _complaint_text_for_legal_guards(*, embedded: str, analysis: str) -> str:
    if embedded.strip():
        return embedded.strip()
    if analysis.strip():
        return analysis.strip()[:12_000]
    return ""


def _generate_with_gemini(
    *,
    complaint_pdf_path: Path,
    sac_summary: str,
    supporting_file_names: list[str],
    consumer_name: str,
    protocol_number: str,
    api_key: str,
    model: str | None,
) -> GeneratedResponse:
    selected_model = model
    available_models: list[str] = []
    if not selected_model:
        available_models = list_generate_content_models(api_key=api_key)
        selected_model = resolve_gemini_model(
            available_models=available_models,
            preferred=get_model_from_env(),
        )
    model_candidates = (
        [normalize_model_name(selected_model)]
        if model
        else _ordered_model_candidates(
            available_models=available_models,
            preferred=get_model_from_env(),
        )
    )

    signed = prompts.signed_date_label()
    supporting_list = "\n".join(f"- {name}" for name in supporting_file_names) or "- (nenhum)"
    complaint_text_embedded = extract_pdf_text_soft(complaint_pdf_path)

    analysis_prompt = prompts.analysis_prompt(
        consumer_name=consumer_name,
        protocol_number=protocol_number,
        complaint_excerpt="",
        use_pdf_attachment=True,
    )
    analysis, selected_model = _gemini_text_with_model_fallback(
        api_key=api_key,
        model_candidates=model_candidates,
        parts=[{"text": analysis_prompt}, _pdf_part(complaint_pdf_path)],
    )

    complaint_text = _complaint_text_for_legal_guards(
        embedded=complaint_text_embedded,
        analysis=analysis,
    )
    legal_profile = resolve_defendant_legal_profile(complaint_text=complaint_text)
    defendant_block = defendant_legal_prompt_block(legal_profile)

    draft, selected_model = _gemini_text_with_model_fallback(
        api_key=api_key,
        model_candidates=[selected_model, *model_candidates],
        parts=[
            {
                "text": prompts.draft_prompt(
                    analysis=analysis,
                    sac_summary=sac_summary,
                    supporting_list=supporting_list,
                    signed_date=signed,
                    defendant_legal_block=defendant_block,
                ),
            },
        ],
    )
    draft = finalize_procon_response_text(draft)
    draft = _apply_defendant_legal_guards(draft, complaint_text=complaint_text)

    final_response, _ = _gemini_text_with_model_fallback(
        api_key=api_key,
        model_candidates=[selected_model, *model_candidates],
        parts=[
            {
                "text": prompts.rewrite_prompt(
                    draft=draft,
                    signed_date=signed,
                    defendant_legal_block=defendant_block,
                ),
            },
        ],
    )
    final_response = finalize_procon_response_text(final_response)
    final_response = apply_multa_replacement(final_response)
    final_response = _apply_defendant_legal_guards(final_response, complaint_text=complaint_text)

    portal_summary, _ = _gemini_text_with_model_fallback(
        api_key=api_key,
        model_candidates=[selected_model, *model_candidates],
        parts=[{"text": prompts.portal_summary_prompt(final_response=final_response)}],
    )
    portal_summary = finalize_procon_response_text(portal_summary)
    portal_summary = enforce_portal_character_limit(portal_summary)
    portal_summary = _apply_defendant_legal_guards(portal_summary, complaint_text=complaint_text)

    return GeneratedResponse(
        analysis=analysis,
        draft=draft,
        final_response=final_response,
        portal_summary=portal_summary,
    )


def _generate_with_openai(
    *,
    complaint_pdf_path: Path,
    sac_summary: str,
    supporting_file_names: list[str],
    consumer_name: str,
    protocol_number: str,
    api_key: str,
    model: str | None,
) -> GeneratedResponse:
    selected_model = resolve_openai_model(preferred=model)
    vision_key = get_api_key_from_env()
    complaint_text = resolve_complaint_text(
        complaint_pdf_path,
        gemini_api_key=vision_key,
        gemini_model=None,
    )
    signed = prompts.signed_date_label()
    supporting_list = "\n".join(f"- {name}" for name in supporting_file_names) or "- (nenhum)"
    legal_profile = resolve_defendant_legal_profile(complaint_text=complaint_text)
    defendant_block = defendant_legal_prompt_block(legal_profile)

    analysis = chat_completion(
        api_key=api_key,
        model=selected_model,
        system_prompt=_OPENAI_SYSTEM,
        user_prompt=prompts.analysis_prompt(
            consumer_name=consumer_name,
            protocol_number=protocol_number,
            complaint_excerpt=complaint_text,
            use_pdf_attachment=False,
        ),
    )

    draft = chat_completion(
        api_key=api_key,
        model=selected_model,
        system_prompt=_OPENAI_SYSTEM,
        user_prompt=prompts.draft_prompt(
            analysis=analysis,
            sac_summary=sac_summary,
            supporting_list=supporting_list,
            signed_date=signed,
            defendant_legal_block=defendant_block,
        ),
    )
    draft = finalize_procon_response_text(draft)
    draft = _apply_defendant_legal_guards(draft, complaint_text=complaint_text)

    final_response = chat_completion(
        api_key=api_key,
        model=selected_model,
        system_prompt=_OPENAI_SYSTEM,
        user_prompt=prompts.rewrite_prompt(
            draft=draft,
            signed_date=signed,
            defendant_legal_block=defendant_block,
        ),
    )
    final_response = finalize_procon_response_text(final_response)
    final_response = apply_multa_replacement(final_response)
    final_response = _apply_defendant_legal_guards(final_response, complaint_text=complaint_text)

    portal_summary = chat_completion(
        api_key=api_key,
        model=selected_model,
        system_prompt=_OPENAI_SYSTEM,
        user_prompt=prompts.portal_summary_prompt(final_response=final_response),
    )
    portal_summary = finalize_procon_response_text(portal_summary)
    portal_summary = enforce_portal_character_limit(portal_summary)
    portal_summary = _apply_defendant_legal_guards(portal_summary, complaint_text=complaint_text)

    return GeneratedResponse(
        analysis=analysis,
        draft=draft,
        final_response=final_response,
        portal_summary=portal_summary,
    )


def generate_procon_response(
    *,
    complaint_pdf_path: Path,
    sac_summary: str,
    supporting_file_names: list[str],
    consumer_name: str,
    protocol_number: str,
    api_key: str | None = None,
    model: str | None = None,
) -> GeneratedResponse:
    """Elabora resposta ao Procon usando Gemini e, se necessário, OpenAI como fallback."""
    if not complaint_pdf_path.exists():
        raise GeminiClientError(f"PDF da reclamação não encontrado: {complaint_pdf_path}")

    gemini_key = api_key or get_api_key_from_env()
    openai_key = get_openai_api_key_from_env()
    if not gemini_key and not openai_key:
        raise GeminiClientError(
            "Nenhum provedor de IA configurado. Defina GEMINI_API_KEY e/ou OPENAI_API_KEY.",
        )

    errors: list[str] = []

    if gemini_key:
        try:
            return _generate_with_gemini(
                complaint_pdf_path=complaint_pdf_path,
                sac_summary=sac_summary,
                supporting_file_names=supporting_file_names,
                consumer_name=consumer_name,
                protocol_number=protocol_number,
                api_key=gemini_key,
                model=model,
            )
        except GeminiClientError as exc:
            if openai_key and _is_quota_or_rate_limit_error(exc):
                errors.append(f"Gemini: {exc}")
            else:
                raise

    if openai_key:
        try:
            return _generate_with_openai(
                complaint_pdf_path=complaint_pdf_path,
                sac_summary=sac_summary,
                supporting_file_names=supporting_file_names,
                consumer_name=consumer_name,
                protocol_number=protocol_number,
                api_key=openai_key,
                model=None,
            )
        except GeminiClientError as exc:
            errors.append(f"OpenAI: {exc}")

    if errors:
        raise GeminiClientError(
            "Falha em todos os provedores de IA configurados. "
            + " | ".join(errors),
        )
    raise GeminiClientError("GEMINI_API_KEY não configurada e fallback OpenAI indisponível.")
