"""Testes de parsing da aba Interações & Respostas."""

from classificacao_procons.portal.interactions import parse_consumer_interactions_from_tab_text

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

    def test_should_return_empty_messages_when_no_consumer_blocks(self) -> None:
        text = "Procon\nAviso.\nEmpresa\nResposta."
        result = parse_consumer_interactions_from_tab_text(text, protocol_number="1/2026")
        assert result.messages == ()
