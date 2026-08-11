"""Testes do cliente Sunday (V1) — transporte fake, nenhuma chamada real."""

from __future__ import annotations

import json
from datetime import date

import pytest

from classificacao_procons.sunday import (
    SundayAuthError,
    SundayClient,
    SundayConfig,
    SundayConfigError,
    SundayForbiddenError,
    SundayNotFoundError,
    SundayRelationIntegrityError,
    SundayValidationError,
    SundayVerifyError,
    normalize_relation_value,
    parse_sunday_date,
)
from classificacao_procons.sunday.http import SundayHttp

TOKEN = "segredo-super-sensivel-nao-vazar"


class FakeTransport:
    """Transporte fake: mapeia (método, caminho) → resposta e grava as chamadas."""

    def __init__(self):
        self.routes: dict[tuple[str, str], tuple[int, object, dict[str, str]]] = {}
        self.calls: list[dict] = []

    def route(
        self,
        method: str,
        path: str,
        body: object,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.routes[(method, path)] = (status, body, headers or {})

    def __call__(self, method, url, body, headers, timeout):
        path = url.split("//", 1)[1].split("/", 1)[1]
        path = "/" + path
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": json.loads(body.decode()) if body else None,
            },
        )
        if (method, path) not in self.routes:
            raise AssertionError(f"rota não esperada: {method} {path}")
        status, payload, response_headers = self.routes[(method, path)]
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return status, text, {key.lower(): value for key, value in response_headers.items()}


@pytest.fixture()
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture()
def client(transport: FakeTransport) -> SundayClient:
    config = SundayConfig(base_url="https://sunday.example", token=TOKEN)
    return SundayClient(config, transport=transport)


def _board_payload(**overrides):
    payload = {
        "id": 80,
        "name": "SANDBOX",
        "template_key": "board",
        "hierarchy_depth": 1,
        "status_set": [
            {"key": "to_do", "label": "A fazer", "color": "neutral", "terminal": False},
            {"key": "done", "label": "Feito", "color": "green", "terminal": True},
        ],
        "area_options": ["Consumidor"],
        "capabilities": {"approvals": False},
    }
    payload.update(overrides)
    return payload


def _columns_payload():
    return [
        {"id": 443, "key": "name", "label": "Texto", "type": "text", "is_system": True},
        {"id": 453, "key": "num", "label": "Número", "type": "number", "is_system": False},
        {
            "id": 456,
            "key": "rel",
            "label": "Relação",
            "type": "board_relation",
            "is_system": False,
            "settings": {"source_board_id": "81"},
        },
        {
            "id": 457,
            "key": "rel_sem_config",
            "label": "Relação sem config",
            "type": "board_relation",
            "is_system": False,
            "settings": {},
        },
    ]


# ------------------------------------------------------------------ segurança


def test_should_send_token_header_when_calling_api(client, transport):
    transport.route("GET", "/auth/me", {"id": 37, "name": "Ivo"})
    client.get_me()
    headers = transport.calls[0]["headers"]
    assert headers["X-Sunday-Token"] == TOKEN
    assert "Authorization" not in headers


def test_should_not_leak_token_in_reprs_and_errors(client, transport):
    transport.route("GET", "/auth/me", {"message": "Unauthorized", "statusCode": 401}, status=401)
    config = SundayConfig(base_url="https://sunday.example", token=TOKEN)
    with pytest.raises(SundayAuthError) as excinfo:
        client.get_me()
    for text in (repr(config), repr(client), repr(SundayHttp(config)), str(excinfo.value)):
        assert TOKEN not in text


def test_should_raise_config_error_when_env_missing(monkeypatch):
    monkeypatch.delenv("SUNDAY_API_URL", raising=False)
    monkeypatch.delenv("SUNDAY_API_TOKEN", raising=False)
    with pytest.raises(SundayConfigError):
        SundayConfig.from_env()


# ------------------------------------------------------------------------ ids


def test_should_normalize_ids_as_strings(client, transport):
    transport.route("GET", "/boards/80", _board_payload())
    board = client.get_board(80)  # aceita int na entrada, expõe string
    assert board.id == "80"
    assert board.status_keys() == ("to_do", "done")


# ---------------------------------------------------------------------- items


def test_should_create_item_with_group_and_dates(client, transport):
    transport.route(
        "POST", "/boards/80/items", {"id": 7659, "name": "Item X", "board_id": 80}, status=201,
    )
    item = client.create_item("80", "Item X", group_id="216", target_date=date(2026, 1, 15))
    assert item.id == "7659"
    sent = transport.calls[0]["body"]
    assert sent == {"name": "Item X", "group_id": "216", "target_date": "2026-01-15"}


def test_should_update_name_via_generic_patch(client, transport):
    transport.route("PATCH", "/boards/items/7659", {"id": 7659, "name": "Novo nome"})
    item = client.update_item("80", "7659", name="Novo nome")
    assert item.name == "Novo nome"
    assert transport.calls[0]["body"] == {"name": "Novo nome"}


def test_should_update_target_date_formatted(client, transport):
    transport.route("PATCH", "/boards/items/7659", {"id": 7659})
    client.update_item("80", "7659", target_date=date(2026, 4, 10))
    assert transport.calls[0]["body"] == {"target_date": "2026-04-10"}


def test_should_update_owner_user_id_as_string(client, transport):
    transport.route("PATCH", "/boards/items/7659", {"id": 7659, "owner_user_id": "37"})
    client.update_item("80", "7659", owner_user_id=37)
    assert transport.calls[0]["body"] == {"owner_user_id": "37"}


def test_should_reject_update_item_without_fields(client):
    with pytest.raises(SundayValidationError):
        client.update_item("80", "7659")


def test_should_not_accept_status_in_generic_update():
    # A assinatura de update_item não tem parâmetro status: PATCH genérico com
    # status responde 200 e é ignorado em silêncio (F0.15) — proibido por design.
    with pytest.raises(TypeError):
        SundayClient(
            SundayConfig(base_url="https://x", token="t"), transport=lambda *a: (200, "{}", {}),
        ).update_item("80", "7659", status="done")


def test_should_delete_item(client, transport):
    transport.route("DELETE", "/boards/items/7659", {})
    client.delete_item("7659")
    assert transport.calls[0]["method"] == "DELETE"


def test_should_get_item_via_board_listing(client, transport):
    transport.route("GET", "/boards/80/items", [{"id": 1}, {"id": 7659, "name": "Alvo"}])
    item = client.get_item("80", "7659")
    assert item is not None and item.name == "Alvo"
    assert client.get_item("80", "999") is None


# --------------------------------------------------------------------- status


def test_should_set_status_via_dedicated_route(client, transport):
    transport.route("GET", "/boards/80", _board_payload())
    transport.route("PATCH", "/boards/items/7659/status", {})
    client.set_status("80", "7659", "done", cascade=True)
    call = transport.calls[-1]
    assert call["path"] == "/boards/items/7659/status"
    assert call["body"] == {"status": "done", "cascade": True}


def test_should_reject_status_key_not_in_status_set(client, transport):
    transport.route("GET", "/boards/80", _board_payload())
    with pytest.raises(SundayValidationError, match="Keys válidas"):
        client.set_status("80", "7659", "assinado")


def test_should_fail_verify_when_status_not_persisted(client, transport):
    transport.route("GET", "/boards/80", _board_payload())
    transport.route("PATCH", "/boards/items/7659/status", {})
    # A releitura mostra o status antigo: HTTP 200 não provou persistência.
    transport.route("GET", "/boards/80/items", [{"id": 7659, "status": "to_do"}])
    with pytest.raises(SundayVerifyError):
        client.set_status("80", "7659", "done", verify=True)


def test_should_fail_verify_when_update_ignored_silently(client, transport):
    transport.route("PATCH", "/boards/items/7659", {"id": 7659, "name": "Novo"})
    transport.route("GET", "/boards/80/items", [{"id": 7659, "name": "Antigo"}])
    with pytest.raises(SundayVerifyError, match="não persistiu"):
        client.update_item("80", "7659", name="Novo", verify=True)


# --------------------------------------------------------------------- values


@pytest.mark.parametrize(
    "value",
    ["texto", 12345, 43.5, True, None, ["a", "b"]],
    ids=["string", "int", "float", "boolean", "null", "list"],
)
def test_should_preserve_json_types_in_custom_values(client, transport, value):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route("PATCH", "/boards/items/7659/values/453", {})
    client.set_custom_value("80", "7659", "453", value)
    assert transport.calls[-1]["body"] == {"value": value}


def test_should_reject_system_column_via_custom_values(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    with pytest.raises(SundayValidationError, match="de sistema"):
        client.set_custom_value("80", "7659", "443", "qualquer")


def test_should_read_value_with_original_type(client, transport):
    transport.route(
        "GET",
        "/boards/items/7659/values",
        [{"column_id": 453, "value": 12345}, {"column_id": 455, "value": True}],
    )
    assert client.get_value("7659", "453") == 12345
    assert client.get_value("7659", "455") is True
    assert client.get_value("7659", "999") is None


def test_should_fail_verify_when_custom_value_differs(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route("PATCH", "/boards/items/7659/values/453", {})
    transport.route("GET", "/boards/items/7659/values", [{"column_id": 453, "value": 999}])
    with pytest.raises(SundayVerifyError):
        client.set_custom_value("80", "7659", "453", 12345, verify=True)


def test_should_raise_not_found_for_unknown_column(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    with pytest.raises(SundayNotFoundError):
        client.set_custom_value("80", "7659", "999", "x")


# ------------------------------------------------------------- board_relation


def test_should_set_relation_one_to_one(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route("PATCH", "/boards/items/7659/values/456", {})
    client.set_relation("80", "7659", "456", "7660", expected_target_board_id="81")
    assert transport.calls[-1]["body"] == {"value": "7660"}


def test_should_set_relation_one_to_many(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route("PATCH", "/boards/items/7659/values/456", {})
    client.set_relation("80", "7659", "456", ["7654", 7664], expected_target_board_id="81")
    assert transport.calls[-1]["body"] == {"value": ["7654", "7664"]}


def test_should_clear_relation_with_null(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route("PATCH", "/boards/items/7659/values/456", {})
    client.set_relation("80", "7659", "456", None, expected_target_board_id="81")
    assert transport.calls[-1]["body"] == {"value": None}


def test_should_reject_relation_to_wrong_board(client, transport):
    # Cenário real da F0.15: coluna configurada para o board 79 (produção) e
    # chamador querendo o 81 — o client rejeita ANTES de chamar a API.
    columns = _columns_payload()
    columns[2]["settings"] = {"source_board_id": "79"}
    transport.route("GET", "/boards/80/columns", columns)
    with pytest.raises(SundayRelationIntegrityError, match="board 79"):
        client.set_relation("80", "7659", "456", "7660", expected_target_board_id="81")
    write_calls = [call for call in transport.calls if call["method"] != "GET"]
    assert write_calls == []


def test_should_reject_relation_on_non_relation_column(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    with pytest.raises(SundayRelationIntegrityError, match="board_relation"):
        client.set_relation("80", "7659", "453", "7660", expected_target_board_id="81")


def test_should_reject_relation_when_column_has_no_source_board(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    with pytest.raises(SundayRelationIntegrityError, match="source_board_id"):
        client.set_relation("80", "7659", "457", "7660", expected_target_board_id="81")


def test_should_verify_relation_after_write(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route("PATCH", "/boards/items/7659/values/456", {})
    transport.route(
        "GET", "/boards/items/7659/values", [{"column_id": 456, "value": ["7654", "7664"]}],
    )
    client.set_relation(
        "80", "7659", "456", ["7654", "7664"], expected_target_board_id="81", verify=True,
    )


def test_should_read_relation_in_any_confirmed_shape(client, transport):
    transport.route("GET", "/boards/items/7659/values", [{"column_id": 456, "value": "7660"}])
    assert client.get_relation("7659", "456") == ("7660",)
    assert normalize_relation_value(["7654", "7664"]) == ("7654", "7664")
    assert normalize_relation_value(None) == ()
    assert normalize_relation_value({"links": [{"item_id": 7}]}) == ("7",)
    assert normalize_relation_value({"item_id": "9"}) == ("9",)


# ------------------------------------------------------------------- comments


def test_should_add_and_list_and_delete_comments(client, transport):
    transport.route(
        "POST",
        "/boards/items/7659/comments",
        {"id": 1, "body": "Oi", "kind": "reply"},
        status=201,
    )
    transport.route("GET", "/boards/items/7659/comments", [{"id": 1, "body": "Oi"}])
    transport.route("DELETE", "/boards/comments/1", {})
    comment = client.add_comment("7659", "Oi", mention_user_ids=["37"])
    assert comment.id == "1"
    assert transport.calls[0]["body"] == {
        "body": "Oi",
        "kind": "reply",
        "mention_user_ids": ["37"],
    }
    assert [c.body for c in client.list_comments("7659")] == ["Oi"]
    client.delete_comment("1")


def test_should_not_expose_comment_edit():
    assert not hasattr(SundayClient, "update_comment")
    assert not hasattr(SundayClient, "edit_comment")


# ---------------------------------------------------------------- attachments


def test_should_add_link_attachment(client, transport):
    transport.route(
        "POST",
        "/boards/items/7659/attachments/link",
        {"id": 5, "url": "https://drive.example/x", "filename": "contrato.pdf"},
        status=201,
    )
    attachment = client.add_link_attachment(
        "7659", "https://drive.example/x", filename="contrato.pdf",
    )
    assert attachment.id == "5"
    assert transport.calls[0]["body"] == {
        "url": "https://drive.example/x",
        "filename": "contrato.pdf",
    }


def test_should_not_expose_binary_upload():
    assert not hasattr(SundayClient, "upload_attachment")


# -------------------------------------------------------------- etag/polling


def test_should_capture_etag_and_send_if_none_match(client, transport):
    transport.route(
        "GET",
        "/boards/80/items",
        [{"id": 7659, "updated_at": "2026-08-11T00:00:00.000Z"}],
        headers={"ETag": 'W/"abc"'},
    )
    result = client.list_items("80")
    assert result.etag == 'W/"abc"'
    assert result.items[0].updated_at == "2026-08-11T00:00:00.000Z"

    transport.route("GET", "/boards/80/items", "", status=304)
    cached = client.list_items("80", etag=result.etag)
    assert cached.not_modified is True
    assert cached.items == ()
    assert transport.calls[-1]["headers"]["If-None-Match"] == 'W/"abc"'


def test_should_support_etag_on_values(client, transport):
    transport.route("GET", "/boards/items/7659/values", "", status=304)
    result = client.list_values("7659", etag='W/"v1"')
    assert result.not_modified is True


# --------------------------------------------------------------------- erros


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, SundayAuthError),
        (403, SundayForbiddenError),
        (404, SundayNotFoundError),
        (400, SundayValidationError),
    ],
)
def test_should_map_http_errors(client, transport, status, exception):
    transport.route(
        "GET", "/auth/me", {"message": "Erro qualquer", "statusCode": status}, status=status,
    )
    with pytest.raises(exception) as excinfo:
        client.get_me()
    assert excinfo.value.status == status


def test_should_surface_business_message_on_400(client, transport):
    transport.route("GET", "/boards/80/columns", _columns_payload())
    transport.route(
        "PATCH",
        "/boards/items/7659/values/453",
        {"message": "System columns são atualizadas via PATCH /boards/items/:id"},
        status=400,
    )
    # Coluna custom no cache, mas a API decide que é sistema: erro chega legível.
    with pytest.raises(SundayValidationError, match="System columns"):
        client.set_custom_value("80", "7659", "453", 1)


# ---------------------------------------------------------------------- datas


def test_should_normalize_technical_noon_utc_to_business_date():
    # Escreve-se 2026-01-15; a API devolve meio-dia UTC. O dia do negócio não muda.
    assert parse_sunday_date("2026-01-15T12:00:00.000Z") == date(2026, 1, 15)
    assert parse_sunday_date("2026-01-15") == date(2026, 1, 15)
    assert parse_sunday_date(None) is None
    assert parse_sunday_date("sem-data") is None


def test_should_verify_target_date_by_date_part(client, transport):
    transport.route("PATCH", "/boards/items/7659", {"id": 7659})
    transport.route(
        "GET",
        "/boards/80/items",
        [{"id": 7659, "target_date": "2026-01-15T12:00:00.000Z"}],
    )
    # verify compara só a parte de data — o horário técnico do Sunday não é do negócio.
    item = client.update_item("80", "7659", target_date=date(2026, 1, 15), verify=True)
    assert item.target_date_as_date() == date(2026, 1, 15)


# ------------------------------------------------------------------ metadata


def test_should_list_groups_and_create_group(client, transport):
    transport.route("GET", "/boards/80/groups", [{"id": 216, "name": "Itens"}])
    transport.route("POST", "/boards/80/groups", {"id": 300, "name": "Fila"}, status=201)
    assert [group.name for group in client.list_groups("80")] == ["Itens"]
    group = client.create_group("80", "Fila", color="blue")
    assert group.id == "300"
    assert transport.calls[-1]["body"] == {"name": "Fila", "color": "blue"}


def test_should_expose_workspace_board_links_distinctly(client, transport):
    transport.route(
        "GET",
        "/workspaces/22",
        {"id": 22, "name": "Support", "boards": [{"id": 57, "board_id": 70, "name": "Weekly"}]},
    )
    workspace = client.get_workspace("22")
    ref = workspace.boards[0]
    assert ref.link_id == "57"
    assert ref.board_id == "70"  # nunca confundir com o link_id (F0.13)
