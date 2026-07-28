"""Testes de vínculos declarados PA→CIP."""

from pathlib import Path

from classificacao_procons.pa_cip_links import (
    load_pa_cip_protocol_links,
    normalize_board_protocol,
)


def test_load_pa_cip_protocol_links_should_read_file(tmp_path: Path) -> None:
    path = tmp_path / "links.json"
    path.write_text('{"1681159/2026": "1624924/2026"}', encoding="utf-8")
    assert load_pa_cip_protocol_links(links_path=path)["1681159/2026"] == "1624924/2026"


def test_normalize_board_protocol_should_extract_from_noisy_text() -> None:
    assert normalize_board_protocol("CIP 1624924/2026") == "1624924/2026"
    assert normalize_board_protocol("1624924 / 2026") == "1624924/2026"


def test_repo_links_file_should_include_silvia_case() -> None:
    links = load_pa_cip_protocol_links()
    assert links.get("1681159/2026") == "1624924/2026"
