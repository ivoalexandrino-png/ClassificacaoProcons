"""Testes da análise caso a caso (heurística e Gemini com mocks)."""

from datetime import date, datetime
from unittest.mock import patch

from classificacao_procons.gemini.client import GeminiClientError
from classificacao_procons.juridico import analise as analise_module
from classificacao_procons.juridico.analise import (
    ANALYSIS_SOURCE_GEMINI,
    ANALYSIS_SOURCE_HEURISTIC,
    analyze_case,
    build_heuristic_analysis,
)
from classificacao_procons.juridico.models import (
    ACTION_CONTESTAR,
    NOTIFICATION_TYPE_CITACAO,
    CaseCommunication,
    CaseMovement,
    ParsedIntimacao,
    Providencia,
)

INTIMACAO = ParsedIntimacao(
    process_number="1001234-83.2026.8.26.0100",
    notification_type=NOTIFICATION_TYPE_CITACAO,
    tribunal="TJSP",
    court_unit="4a Vara Civel de Sao Paulo",
    summary="Citação para contestar em 15 dias úteis.",
)

PROVIDENCIA = Providencia(
    action_type=ACTION_CONTESTAR,
    description="Apresentar contestação",
    requires_action=True,
    due_date=date(2026, 8, 7),
    hearing_datetime=datetime(2026, 8, 5, 14, 30),
    requires_legal_document=True,
)

COMMUNICATIONS = [
    CaseCommunication(
        text="CITAÇÃO da parte ré para contestar.",
        communication_type="Citação",
        organ="4ª Vara Cível",
        available_date="2026-07-15",
    ),
]

MOVEMENTS = [
    CaseMovement(movement_name="Expedição de citação", movement_datetime=datetime(2026, 7, 15)),
]


class TestBuildHeuristicAnalysis:
    def test_should_include_case_context_and_due_date(self) -> None:
        analysis = build_heuristic_analysis(
            intimacao=INTIMACAO,
            providencia=PROVIDENCIA,
            communications=COMMUNICATIONS,
            movements=MOVEMENTS,
        )

        assert analysis.source == ANALYSIS_SOURCE_HEURISTIC
        assert "1001234-83.2026.8.26.0100" in analysis.text
        assert "Apresentar contestação" in analysis.text
        assert "2026-08-07" in analysis.text
        assert "05/08/2026 14:30" in analysis.text
        assert "Expedição de citação" in analysis.text

    def test_should_handle_empty_communications_and_movements(self) -> None:
        analysis = build_heuristic_analysis(
            intimacao=INTIMACAO,
            providencia=Providencia(
                action_type=ACTION_CONTESTAR,
                description="Apresentar contestação",
                requires_action=True,
            ),
            communications=[],
            movements=[],
        )
        assert "nenhuma comunicação encontrada" in analysis.text
        assert "nenhum andamento disponível" in analysis.text
        assert "sem prazo identificado" in analysis.text


class TestAnalyzeCase:
    def test_should_fall_back_to_heuristic_without_api_key(self) -> None:
        with patch.object(analise_module, "get_api_key_from_env", return_value=None):
            analysis = analyze_case(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                communications=COMMUNICATIONS,
                movements=MOVEMENTS,
            )
        assert analysis.source == ANALYSIS_SOURCE_HEURISTIC

    def test_should_use_gemini_when_api_key_is_available(self) -> None:
        with (
            patch.object(
                analise_module,
                "list_generate_content_models",
                return_value=["gemini-3.5-flash"],
            ),
            patch.object(
                analise_module,
                "_gemini_request",
                return_value="O que aconteceu: citação recebida. Providência: contestar.",
            ) as gemini_request,
        ):
            analysis = analyze_case(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                communications=COMMUNICATIONS,
                movements=MOVEMENTS,
                api_key="chave-teste",
            )

        assert analysis.source == ANALYSIS_SOURCE_GEMINI
        assert "citação recebida" in analysis.text
        prompt = gemini_request.call_args.kwargs["parts"][0]["text"]
        assert "1001234-83.2026.8.26.0100" in prompt
        assert "CITAÇÃO da parte ré" in prompt
        assert "Expedição de citação" in prompt

    def test_should_fall_back_to_heuristic_when_gemini_fails(self) -> None:
        with patch.object(
            analise_module,
            "list_generate_content_models",
            side_effect=GeminiClientError("Gemini indisponível"),
        ):
            analysis = analyze_case(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                communications=COMMUNICATIONS,
                movements=MOVEMENTS,
                api_key="chave-teste",
            )
        assert analysis.source == ANALYSIS_SOURCE_HEURISTIC
        assert "Apresentar contestação" in analysis.text
