"""Testes do board Acessos no Monday."""

from classificacao_procons.credentials.monday_board import (
    PortalCredentialsRecord,
    _extract_record_from_item,
    find_credentials_for_source,
    to_portal_credentials,
)


def _column_lookup() -> dict[str, str]:
    return {
        "col_login": "login",
        "col_password": "password",
        "col_link": "link",
    }


class TestCredentialsMondayBoard:
    def test_should_extract_record_from_item(self) -> None:
        item = {
            "id": "123",
            "name": "Proconsumidor",
            "column_values": [
                {"id": "col_login", "text": "user@example.com", "value": '"user@example.com"'},
                {"id": "col_password", "text": "secret", "value": '"secret"'},
                {
                    "id": "col_link",
                    "text": "Acesso",
                    "value": '{"url":"https://proconsumidor.mj.gov.br","text":"Acesso"}',
                },
            ],
        }

        record = _extract_record_from_item(item, column_lookup=_column_lookup())

        assert record == PortalCredentialsRecord(
            elemento="Proconsumidor",
            login="user@example.com",
            password="secret",
            portal_url="https://proconsumidor.mj.gov.br",
            monday_item_id="123",
        )

    def test_should_return_none_when_login_or_password_missing(self) -> None:
        item = {
            "id": "123",
            "name": "Campinas",
            "column_values": [
                {"id": "col_login", "text": "only-login", "value": '"only-login"'},
            ],
        }
        assert _extract_record_from_item(item, column_lookup=_column_lookup()) is None

    def test_should_find_credentials_for_source(self) -> None:
        records = [
            PortalCredentialsRecord(
                elemento="Campinas",
                login="campinas-user",
                password="campinas-pass",
                portal_url=None,
                monday_item_id="1",
            ),
            PortalCredentialsRecord(
                elemento="Proconsumidor",
                login="pro-user",
                password="pro-pass",
                portal_url="https://proconsumidor.mj.gov.br",
                monday_item_id="2",
            ),
        ]

        record = find_credentials_for_source(records, source_id="proconsumidor")

        assert record is not None
        assert record.login == "pro-user"

    def test_should_use_default_portal_url_when_link_missing(self) -> None:
        record = PortalCredentialsRecord(
            elemento="Proconsumidor",
            login="pro-user",
            password="pro-pass",
            portal_url=None,
            monday_item_id="2",
        )

        credentials = to_portal_credentials(record, source_id="proconsumidor")

        assert credentials.portal_url == "https://proconsumidor.mj.gov.br/#/login"
        assert credentials.source_id == "proconsumidor"
