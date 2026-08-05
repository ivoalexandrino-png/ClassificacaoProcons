"""Testes de prompts e alinhamento ao SAC."""

from classificacao_procons.llm.prompts import (
    analysis_prompt,
    draft_prompt,
    rewrite_prompt,
    sac_authority_rules,
    sac_consistency_prompt,
)
from classificacao_procons.llm.sac_alignment import (
    effective_sac_text_length,
    should_run_sac_consistency_pass,
)

_NATHALIA_SAC = (
    "Assinatura semestral; brinde válido só para plano anual. "
    "Empresa não dará prosseguimento ao envio dos itens promocionais."
)


class TestSacAuthorityInPrompts:
    def test_analysis_prompt_should_include_sac_when_provided(self) -> None:
        text = analysis_prompt(
            consumer_name="NATHALIA",
            protocol_number="1707336/2026",
            complaint_excerpt="",
            use_pdf_attachment=True,
            sac_summary=_NATHALIA_SAC,
        )
        assert "PRIORIDADE MÁXIMA" in text
        assert "semestral" in text
        assert "defesa do consumidor" not in text.casefold()

    def test_draft_prompt_should_put_sac_before_analysis(self) -> None:
        text = draft_prompt(
            analysis="Análise genérica",
            sac_summary=_NATHALIA_SAC,
            supporting_list="- doc.pdf",
            signed_date="05/08/2026",
        )
        sac_pos = text.index("RELATO DO SAC")
        analysis_pos = text.index("ANÁLISE")
        assert sac_pos < analysis_pos
        assert "não dará prosseguimento" in text

    def test_rewrite_prompt_should_forbid_contradicting_sac(self) -> None:
        text = rewrite_prompt(
            draft="Rascunho",
            signed_date="05/08/2026",
            sac_summary=_NATHALIA_SAC,
        )
        assert "SEM alterar a conclusão do SAC" in text

    def test_sac_consistency_prompt_should_reference_both_sources(self) -> None:
        text = sac_consistency_prompt(
            sac_summary=_NATHALIA_SAC,
            response_text="Concedemos o envio dos brindes.",
        )
        assert sac_authority_rules()[:20] in text
        assert "Concedemos" in text


class TestSacAlignmentHelpers:
    def test_should_detect_usable_sac_text_length(self) -> None:
        summary = f"### info.txt\n{_NATHALIA_SAC}"
        assert effective_sac_text_length(summary) > 50
        assert should_run_sac_consistency_pass(summary)

    def test_should_skip_consistency_when_sac_empty(self) -> None:
        assert not should_run_sac_consistency_pass("")
