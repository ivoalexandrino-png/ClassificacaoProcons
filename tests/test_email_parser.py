"""Testes do parser de e-mails Procon-SP."""

import pytest

from classificacao_procons.email.parser import (
    PROCON_SP_SENDER,
    PROCON_SP_SUBJECT,
    ProconEmailParseError,
    is_procon_cip_notification,
    normalize_email_address,
    parse_procon_notification_body,
)

SAMPLE_HTML = """
<html>
<body>
<p>Prezado fornecedor,</p>
<p>Foi emitida uma Carta de Informações Preliminares (CIP).</p>
<p>
  Para acessar a reclamação, utilize o link abaixo e informe o código de acesso:
</p>
<p>
  <a href="https://fornecedor2.procon.sp.gov.br/login">Acessar o portal do fornecedor</a>
</p>
<p>Código de acesso: ABC123-XYZ789</p>
<p>Atenciosamente,<br/>Fundação Procon-SP</p>
</body>
</html>
"""

SAMPLE_TEXT = """
Prezado fornecedor,

Foi emitida uma Carta de Informações Preliminares (CIP).

Link: https://fornecedor2.procon.sp.gov.br/login

Código de acesso: ABC123-XYZ789

Atenciosamente,
Fundação Procon-SP
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

    def test_should_not_match_when_sender_differs(self) -> None:
        assert not is_procon_cip_notification(
            subject=PROCON_SP_SUBJECT,
            sender="outro@example.com",
        )

    def test_should_normalize_subject_with_extra_whitespace(self) -> None:
        assert is_procon_cip_notification(
            subject="  Fundação Procon-SP - Notificação de emissão de CIP  ",
            sender=PROCON_SP_SENDER,
        )


class TestNormalizeEmailAddress:
    def test_should_extract_address_from_display_name_format(self) -> None:
        assert (
            normalize_email_address("Fundação Procon-SP <procon.naoresponder@procon.sp.gov.br>")
            == PROCON_SP_SENDER
        )

    def test_should_return_plain_address_lowercased(self) -> None:
        assert normalize_email_address("User@Example.COM") == "user@example.com"


class TestParseProconNotificationBody:
    def test_should_extract_link_and_code_from_html(self) -> None:
        result = parse_procon_notification_body(html=SAMPLE_HTML)
        assert result.portal_url == "https://fornecedor2.procon.sp.gov.br/login"
        assert result.access_code == "ABC123-XYZ789"

    def test_should_extract_link_and_code_from_plain_text(self) -> None:
        result = parse_procon_notification_body(text=SAMPLE_TEXT)
        assert result.portal_url == "https://fornecedor2.procon.sp.gov.br/login"
        assert result.access_code == "ABC123-XYZ789"

    def test_should_prefer_anchor_href_over_plain_text_url(self) -> None:
        html = """
        <a href="https://fornecedor2.procon.sp.gov.br/login?ref=email">Portal</a>
        Código: TOKEN-998877
        """
        result = parse_procon_notification_body(html=html)
        assert result.portal_url == "https://fornecedor2.procon.sp.gov.br/login?ref=email"
        assert result.access_code == "TOKEN-998877"

    def test_should_fallback_to_default_login_url_when_link_missing(self) -> None:
        html = "<p>Código de acesso: ONLYCODE-123456</p>"
        result = parse_procon_notification_body(html=html)
        assert result.portal_url == "https://fornecedor2.procon.sp.gov.br/login"
        assert result.access_code == "ONLYCODE-123456"

    def test_should_raise_when_body_is_empty(self) -> None:
        with pytest.raises(ProconEmailParseError, match="Corpo do e-mail vazio"):
            parse_procon_notification_body()

    def test_should_raise_when_code_is_missing(self) -> None:
        html = '<a href="https://fornecedor2.procon.sp.gov.br/login">Portal</a>'
        with pytest.raises(ProconEmailParseError, match="Código de acesso não encontrado"):
            parse_procon_notification_body(html=html)

    def test_should_extract_code_with_chave_de_acesso_label(self) -> None:
        text = """
        Link: https://fornecedor2.procon.sp.gov.br/login
        Chave de acesso: 9F2K8L1M4N
        """
        result = parse_procon_notification_body(text=text)
        assert result.access_code == "9F2K8L1M4N"

    def test_should_ignore_short_false_positive_codes(self) -> None:
        text = """
        Link: https://fornecedor2.procon.sp.gov.br/login
        Código de acesso: AB12
        """
        with pytest.raises(ProconEmailParseError):
            parse_procon_notification_body(text=text)
