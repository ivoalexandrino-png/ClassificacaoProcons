"""Testes do CLI litigio-agent."""

import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from classificacao_procons.litigio_cli import main


class TestLitigioCliParse:
    def test_should_print_providencia_json_from_stdin(self) -> None:
        stdin_text = "Intime-se no prazo de 15 dias para manifestação."
        buffer = io.StringIO()

        with patch("sys.stdin", io.StringIO(stdin_text)), redirect_stdout(buffer):
            exit_code = main(["parse", "--tipo-documento", "Despacho"])

        assert exit_code == 0
        data = json.loads(buffer.getvalue())
        assert data["tipo"] == "manifestacao"
        assert data["prazo_dias"] == 15

    def test_should_read_texto_from_file_when_arquivo_is_given(self, tmp_path) -> None:
        arquivo = tmp_path / "intimacao.txt"
        arquivo.write_text("Tomar ciência do despacho proferido.", encoding="utf-8")
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            exit_code = main(["parse", "--arquivo", str(arquivo)])

        assert exit_code == 0
        data = json.loads(buffer.getvalue())
        assert data["tipo"] == "ciencia"
        assert data["requer_atencao"] is False


class TestLitigioCliMonitorValidation:
    def test_should_return_error_when_oab_args_are_missing(self, capsys) -> None:
        exit_code = main(["monitor", "--numero-oab", "", "--uf-oab", ""])

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "obrigat" in captured.err

    def test_should_print_help_when_no_command_given(self, capsys) -> None:
        exit_code = main([])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "litígio" in captured.out.lower() or "litigio" in captured.out.lower()
