"""Testes da CLI procon-juridico (comando parse, offline)."""

import json

from classificacao_procons.juridico.cli import main

_INTIMACAO = (
    "Processo nº 1023456-78.2026.8.26.0100 - TJSP\n"
    "3ª Vara Cível de São Paulo\n"
    "Intimada a parte para contestar no prazo de 15 dias úteis.\n"
    "Considera-se publicado em 17/07/2026.\n"
)


class TestParseCommand:
    def test_should_parse_file_and_print_json(self, tmp_path, capsys) -> None:
        path = tmp_path / "intimacao.txt"
        path.write_text(_INTIMACAO, encoding="utf-8")

        exit_code = main(["parse", "--file", str(path)])
        assert exit_code == 0

        output = json.loads(capsys.readouterr().out)
        assert output["intimacao"]["process_number"] == "1023456-78.2026.8.26.0100"
        assert output["providencia"]["tipo"] == "Contestar"
        assert output["providencia"]["prazo_final"] == "2026-08-07"

    def test_should_error_on_missing_file(self, capsys) -> None:
        exit_code = main(["parse", "--file", "/nao/existe.txt"])
        assert exit_code == 1
        assert "error" in capsys.readouterr().err

    def test_should_error_when_no_process_number(self, tmp_path, capsys) -> None:
        path = tmp_path / "vazio.txt"
        path.write_text("texto sem processo", encoding="utf-8")
        exit_code = main(["parse", "--file", str(path)])
        assert exit_code == 1
