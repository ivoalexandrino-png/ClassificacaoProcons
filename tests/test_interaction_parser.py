"""Testes do parser de interação do consumidor."""

import pytest

from classificacao_procons.email.interaction_parser import (
    is_procon_consumer_interaction,
    parse_procon_consumer_interaction_body,
)
from classificacao_procons.email.parser import PROCON_SP_SENDER, ProconEmailParseError

INTERACTION_HTML = """
<p>Prezados,<br>
<br>
Informamos nova interação do consumidor na reclamação abaixo.<br>
<br>
Protocolo 1623103/2026<br>
Código: 2*26WwV1UjWM@714<br>
<br>
Acesse https://fornecedor2.procon.sp.gov.br<br>
</p>
"""


class TestIsProconConsumerInteraction:
    def test_should_match_when_subject_contains_fragment(self) -> None:
        assert is_procon_consumer_interaction(
            subject="Fundação Procon-SP - Interação do Consumidor",
            sender=PROCON_SP_SENDER,
        )

    def test_should_match_naoresponder_variant_sender(self) -> None:
        assert is_procon_consumer_interaction(
            subject="Interação do Consumidor - protocolo",
            sender="Procon <procon.naoresponder2@procon.sp.gov.br>",
        )

    def test_should_not_match_other_subjects(self) -> None:
        assert not is_procon_consumer_interaction(
            subject="Fundação Procon-SP - Notificação de emissão de CIP",
            sender=PROCON_SP_SENDER,
        )


class TestParseProconConsumerInteractionBody:
    def test_should_extract_protocol_and_optional_access_code(self) -> None:
        parsed = parse_procon_consumer_interaction_body(html=INTERACTION_HTML)
        assert parsed.protocol_number == "1623103/2026"
        assert parsed.access_code == "2*26WwV1UjWM@714"

    def test_should_raise_when_protocol_missing(self) -> None:
        with pytest.raises(ProconEmailParseError, match="Protocolo não encontrado"):
            parse_procon_consumer_interaction_body(html="<p>Só código: ABC</p>")
