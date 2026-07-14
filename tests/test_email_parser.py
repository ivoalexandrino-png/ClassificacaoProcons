"""Testes do parser de e-mails Procon-SP."""

import pytest

from classificacao_procons.email.parser import (
    PROCON_SP_SENDER,
    PROCON_SP_SUBJECT,
    ProconEmailParseError,
    is_procon_cip_notification,
    parse_procon_notification_body,
)

REAL_PROCON_HTML = """
<p>Prezados,<br>
<br>
A Diretoria de Atendimento da Fundação Procon-SP informa que foi registrada reclamação
neste órgão em face da sua empresa, cujo prazo final para análise e resposta é 24-07-2026 .<br>
<br>
Solicitamos que acesse o site http://fornecedor2.procon.sp.gov.br e efetue login
utilizando o código fornecido abaixo.
<br>Código: 2*26WwV1UjWM@714<br>
<br>
Protocolo 1653213/2026<br>
<br>
Atenciosamente,<br>
Diretoria de Atendimento<br>
Fundação Procon-SP</p>
"""


class TestIsProconCipNotification:
    def test_should_match_when_subject_and_sender_are_exact(self) -> None:
        assert is_procon_cip_notification(
            subject=PROCON_SP_SUBJECT,
            sender=PROCON_SP_SENDER,
        )

    def test_should_match_when_sender_has_display_name(self) -> None:
        assert is_procon_cip_notification(
            subject=PROCON_SP_SUBJECT,
            sender=f"Procon SP <{PROCON_SP_SENDER}>",
        )

    def test_should_not_match_when_subject_differs(self) -> None:
        assert not is_procon_cip_notification(
            subject="Outro assunto",
            sender=PROCON_SP_SENDER,
        )


class TestParseProconNotificationBody:
    def test_should_extract_real_procon_email_fields(self) -> None:
        result = parse_procon_notification_body(html=REAL_PROCON_HTML)
        assert result.access_code == "2*26WwV1UjWM@714"
        assert result.protocol_number == "1653213/2026"
        assert result.response_deadline == "24-07-2026"
        assert "fornecedor2.procon.sp.gov.br" in result.portal_url

    def test_should_raise_when_body_is_empty(self) -> None:
        with pytest.raises(ProconEmailParseError, match="Corpo do e-mail vazio"):
            parse_procon_notification_body()

    def test_should_raise_when_code_is_missing(self) -> None:
        html = "<p>Protocolo 1653213/2026</p>"
        with pytest.raises(ProconEmailParseError, match="Código de acesso não encontrado"):
            parse_procon_notification_body(html=html)
