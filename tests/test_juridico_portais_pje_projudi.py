"""Testes de detecção de captcha (PJe) e login (Projudi) com página mockada."""

import pytest

from classificacao_procons.juridico.acessos import PortalCredential
from classificacao_procons.juridico.portais import pje, projudi
from classificacao_procons.juridico.portais.base import (
    PortalError,
    PortalRequiresInteraction,
)


class FakeElement:
    def __init__(self) -> None:
        self.value: str | None = None

    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        pass

    def inner_text(self) -> str:
        return ""


class FakeFrame:
    def __init__(self, url: str) -> None:
        self.url = url


class FakePage:
    def __init__(self, body: str, *, selectors: dict | None = None, frames=None) -> None:
        self._body = body
        self._selectors = selectors or {}
        self.frames = frames or [FakeFrame("https://projudi.tjpr.jus.br/projudi/")]

    def content(self) -> str:
        return self._body

    def query_selector(self, selector: str):
        for key, element in self._selectors.items():
            if key in selector:
                return element
        return None


class TestPjeCaptcha:
    def test_should_detect_csjt_captcha(self) -> None:
        page = FakePage("Solução em conformidade com a Resolução n° 139/2014 do CSJT.")
        assert pje._has_captcha(page) is True

    def test_should_detect_generic_captcha_text(self) -> None:
        page = FakePage("Digite os caracteres exibidos na imagem")
        assert pje._has_captcha(page) is True

    def test_should_report_no_captcha_on_clean_page(self) -> None:
        page = FakePage("Movimentações do processo")
        assert pje._has_captcha(page) is False

    def test_regional_from_alias(self) -> None:
        assert pje._regional_from_alias("trt2") == "2"
        assert pje._regional_from_alias("trt15") == "15"
        assert pje._regional_from_alias("tjsp") is None


class TestProjudiLogin:
    CRED = PortalCredential("TJ-PR", "PROJUDI", "user", "pass")

    def test_should_raise_captcha_when_recaptcha_present(self) -> None:
        page = FakePage('<div class="g-recaptcha"></div>')

        def goto(*_a, **_k):
            pass

        page.goto = goto  # type: ignore[attr-defined]
        page.wait_for_timeout = lambda *_a: None  # type: ignore[attr-defined]
        with pytest.raises(PortalRequiresInteraction, match="captcha"):
            projudi._login(page, host="https://projudi.tjpr.jus.br/projudi/", credential=self.CRED)

    def test_should_raise_captcha_when_turing_frame_present(self) -> None:
        page = FakePage(
            "página",
            frames=[FakeFrame("https://global.turing.captcha.gtimg.com/template/drag_ele_gl")],
        )
        page.goto = lambda *_a, **_k: None  # type: ignore[attr-defined]
        page.wait_for_timeout = lambda *_a: None  # type: ignore[attr-defined]
        with pytest.raises(PortalRequiresInteraction, match="captcha"):
            projudi._login(page, host="https://projudi.tjba.jus.br/projudi/", credential=self.CRED)

    def test_should_raise_when_login_form_missing(self) -> None:
        page = FakePage("página sem formulário")
        page.goto = lambda *_a, **_k: None  # type: ignore[attr-defined]
        page.wait_for_timeout = lambda *_a: None  # type: ignore[attr-defined]
        with pytest.raises(PortalError, match="Formulário de login"):
            projudi._login(page, host="https://projudi.tjpr.jus.br/projudi/", credential=self.CRED)

    def test_projudi_host_mapping(self) -> None:
        assert projudi.projudi_host("TJPR").endswith("tjpr.jus.br/projudi/")
        assert projudi.projudi_host("TJBA").endswith("tjba.jus.br/projudi/")
        assert projudi.projudi_host("TJXX") is None
