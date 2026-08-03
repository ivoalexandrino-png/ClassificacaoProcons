"""Elaboração com PDF da reclamação digitalizado (sem camada de texto)."""

from pathlib import Path
from unittest.mock import patch

from classificacao_procons.llm.procon_response import _generate_with_gemini


@patch("classificacao_procons.llm.procon_response._gemini_text_with_model_fallback")
@patch("classificacao_procons.llm.procon_response.extract_pdf_text_soft", return_value="")
def test_should_elaborate_scanned_pdf_via_analysis_attachment(
    _soft_extract_mock,
    gemini_text_mock,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "cip.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    gemini_text_mock.side_effect = [
        ("Análise lida do PDF anexo.", "gemini-2.0-flash"),
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
    first_call_parts = gemini_text_mock.call_args_list[0].kwargs["parts"]
    pdf_parts = [
        part for part in first_call_parts
        if part.get("inline_data", {}).get("mime_type") == "application/pdf"
    ]
    assert pdf_parts
