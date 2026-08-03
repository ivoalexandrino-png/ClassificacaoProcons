"""Elaboração com PDF da reclamação digitalizado (sem camada de texto)."""

from pathlib import Path
from unittest.mock import patch

from classificacao_procons.llm.procon_response import _generate_with_gemini


@patch("classificacao_procons.llm.procon_response._gemini_text_with_model_fallback")
@patch("classificacao_procons.llm.procon_response.resolve_complaint_text")
def test_should_elaborate_when_complaint_pdf_has_no_embedded_text(
    resolve_text_mock,
    gemini_text_mock,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "cip.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    resolve_text_mock.return_value = "Reclamação transcrita via Gemini."
    gemini_text_mock.side_effect = [
        ("Análise", "gemini-2.0-flash"),
        ("Rascunho", "gemini-2.0-flash"),
        ("Resposta final", "gemini-2.0-flash"),
        ("Resumo portal", "gemini-2.0-flash"),
    ]

    result = _generate_with_gemini(
        complaint_pdf_path=pdf_path,
        sac_summary="SAC",
        supporting_file_names=[],
        consumer_name="DANIELLE",
        protocol_number="2607057200100125303",
        api_key="gemini-key",
        model="gemini-2.0-flash",
    )

    assert result.final_response == "Resposta final"
    resolve_text_mock.assert_called_once()
    assert gemini_text_mock.call_count == 4
