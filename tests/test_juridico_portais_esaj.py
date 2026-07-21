"""Testes da lógica de login/2FA do cliente e-SAJ (Playwright mockado)."""

import pytest

from classificacao_procons.juridico.acessos import PortalCredential
from classificacao_procons.juridico.portais import esaj
from classificacao_procons.juridico.portais.esaj import (
    PortalError,
    PortalRequiresInteraction,
    _login,
)

CRED = PortalCredential("TJ-SP", "E-SAJ", "40712473807", "senha-nova")


class FakeElement:
    def __init__(self) -> None:
        self.filled: str | None = None

    def fill(self, value: str) -> None:
        self.filled = value

    def click(self) -> None:
        pass


class FakePage:
    """Página e-SAJ simulada: controla o que cada etapa "vê"."""

    def __init__(self, *, after_login_body: str, requires_token: bool) -> None:
        self._after_login_body = after_login_body
        self._requires_token = requires_token
        self.token_submitted: str | None = None
        self.elements: dict[str, FakeElement] = {}

    def goto(self, *args, **kwargs) -> None:
        pass

    def wait_for_timeout(self, *_args) -> None:
        pass

    def fill(self, _selector: str, _value: str) -> None:
        pass

    def click(self, _selector: str) -> None:
        pass

    def content(self) -> str:
        return self._after_login_body

    def query_selector(self, selector: str):
        if selector in ("#btnEnviarToken", "#btnReceberToken") and self._requires_token:
            return FakeElement()
        if selector in ("#token", "input[name=token]"):
            element = self.elements.setdefault("token", FakeElement())
            return element
        return None

    def keyboard_press(self, *_args) -> None:
        pass


class TestLogin:
    def test_should_raise_when_credentials_are_refused(self) -> None:
        page = FakePage(after_login_body="Usuário ou senha inválidos.", requires_token=False)
        with pytest.raises(PortalError, match="recusou as credenciais"):
            _login(page, CRED)

    def test_should_require_interaction_when_token_needed_without_provider(self) -> None:
        page = FakePage(after_login_body="Informe o código enviado", requires_token=True)
        with pytest.raises(PortalRequiresInteraction, match="2FA"):
            _login(page, CRED)

    def test_should_submit_token_from_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # exige token na 1ª verificação; depois de enviar, não exige mais
        page = FakePage(after_login_body="Informe o código enviado", requires_token=True)
        states = iter([True, False])

        def fake_requires(_page):
            return next(states)

        monkeypatch.setattr(esaj, "_requires_token", fake_requires)

        submitted: dict[str, str] = {}

        def fake_submit(_page, code):
            submitted["code"] = code

        monkeypatch.setattr(esaj, "_submit_token", fake_submit)

        _login(page, CRED, token_provider=lambda login: "123456")
        assert submitted["code"] == "123456"

    def test_should_raise_when_provider_returns_no_code(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        page = FakePage(after_login_body="Informe o código enviado", requires_token=True)
        monkeypatch.setattr(esaj, "_requires_token", lambda _page: True)
        with pytest.raises(PortalRequiresInteraction, match="não recebido"):
            _login(page, CRED, token_provider=lambda login: None)
