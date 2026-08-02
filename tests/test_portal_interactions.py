"""Testes de parsing da aba Interações & Respostas."""

from unittest.mock import patch

import pytest

from classificacao_procons.portal.client import PortalFetchOptions, ProconPortalError
from classificacao_procons.portal.interactions import (
    PortalConsumerInteractions,
    fetch_consumer_interactions,
    parse_consumer_interactions_from_tab_text,
)

SAMPLE_TAB_TEXT = """
Protocolo 1623103/2026
Interações & Respostas
Procon
Notificação automática do órgão.
Consumidor
Olá, segue foto do produto.
IMG_3492.png
Empresa
Resposta enviada anteriormente.
Consumidor
Preciso de retorno sobre o reembolso.
"""

PA_CONVERTED_TAB_TEXT = """
Interações & Respostas
PROCON
24/07/2026 11:59
Atendimento Convertido em Processo Administrativo em 24/07/2026 11:59
GABRIELE CELETE CUSTODIO JESUS
24/07/2026 11:59
Ainda não recebi a caixa com os brindes . Estou aguardando para verificar se os brindes vão vir .
B4A Serviços de Tecnologia e Comércio S.A
24/07/2026 11:56
Prezados, não há qualquer violação ao CDC.
gabriele celete.pdf
Indicação_merged.pdf
"""


class TestParseConsumerInteractionsFromTabText:
    def test_should_keep_only_consumer_blocks(self) -> None:
        result = parse_consumer_interactions_from_tab_text(
            SAMPLE_TAB_TEXT,
            protocol_number="1623103/2026",
        )
        assert result.protocol_number == "1623103/2026"
        assert len(result.messages) == 2
        assert "foto do produto" in result.messages[0].body
        assert "reembolso" in result.messages[1].body
        assert any("IMG_3492" in label for label in result.attachment_labels)
        assert len(result.procon_notices) == 1
        assert "Notificação automática" in result.procon_notices[0]

    def test_should_return_empty_messages_when_no_consumer_blocks(self) -> None:
        text = "Procon\nAviso.\nEmpresa\nResposta."
        result = parse_consumer_interactions_from_tab_text(text, protocol_number="1/2026")
        assert result.messages == ()

    def test_should_extract_consumer_by_full_name_after_pa_conversion(self) -> None:
        result = parse_consumer_interactions_from_tab_text(
            PA_CONVERTED_TAB_TEXT,
            protocol_number="1656146/2026",
        )
        assert len(result.messages) == 1
        assert "brindes" in result.messages[0].body
        assert result.messages[0].author_label.startswith("GABRIELE")
        assert any("Processo Administrativo" in notice for notice in result.procon_notices)
        assert any("gabriele celete.pdf" in label for label in result.attachment_labels)


class TestFetchConsumerInteractionsFallback:
    def test_should_try_processo_administrativo_when_reclamacao_fails(self) -> None:
        options = PortalFetchOptions(
            access_code="code-123",
            download_dir="downloads",
        )
        expected = PortalConsumerInteractions(
            protocol_number="1656146/2026",
            messages=(),
            attachment_labels=(),
        )

        with patch(
            "classificacao_procons.portal.interactions._fetch_consumer_interactions_for_kind",
        ) as fetch_mock:
            fetch_mock.side_effect = [
                ProconPortalError("Código inválido"),
                expected,
            ]
            result = fetch_consumer_interactions(
                options,
                protocol_hint="1656146/2026",
                complaint_kind="reclamacao",
            )

        assert result == expected
        assert fetch_mock.call_count == 2
        assert fetch_mock.call_args_list[0].kwargs["complaint_kind"] == "reclamacao"
        assert fetch_mock.call_args_list[1].kwargs["complaint_kind"] == "processo_administrativo"

    def test_should_raise_when_all_kinds_fail(self) -> None:
        options = PortalFetchOptions(
            access_code="bad",
            download_dir="downloads",
        )
        with patch(
            "classificacao_procons.portal.interactions._fetch_consumer_interactions_for_kind",
            side_effect=ProconPortalError("falha"),
        ):
            with pytest.raises(ProconPortalError, match="falha"):
                fetch_consumer_interactions(options)
