"""Numeração única CNJ (Res. 65/2008): parsing, tribunal e alias DataJud."""

from __future__ import annotations

import re

PROCESS_NUMBER_PATTERN = re.compile(
    r"(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})",
)

_UF_BY_ESTADUAL_TR: dict[str, str] = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA", "06": "CE",
    "07": "DF", "08": "ES", "09": "GO", "10": "MA", "11": "MT", "12": "MS",
    "13": "MG", "14": "PA", "15": "PB", "16": "PR", "17": "PE", "18": "PI",
    "19": "RJ", "20": "RN", "21": "RS", "22": "RO", "23": "RR", "24": "SC",
    "25": "SE", "26": "SP", "27": "TO",
}

_MILITAR_ESTADUAL_BY_TR: dict[str, str] = {"13": "TJMMG", "21": "TJMRS", "26": "TJMSP"}


def extract_process_number(text: str) -> str | None:
    """Encontra o primeiro número de processo CNJ no texto, normalizado."""
    match = PROCESS_NUMBER_PATTERN.search(text)
    if not match:
        return None
    sequential, check, year, segment, tribunal, origin = match.groups()
    return f"{sequential}-{check}.{year}.{segment}.{tribunal}.{origin}"


def process_number_digits(process_number: str) -> str:
    """Só os 20 dígitos, formato aceito pela API do DataJud."""
    return re.sub(r"\D", "", process_number)


def _segments(process_number: str) -> tuple[str, str] | None:
    match = PROCESS_NUMBER_PATTERN.fullmatch(process_number.strip())
    if not match:
        return None
    return match.group(4), match.group(5)


def tribunal_acronym(process_number: str) -> str | None:
    """Sigla do tribunal a partir dos dígitos J.TR do número CNJ."""
    segments = _segments(process_number)
    if segments is None:
        return None
    court_segment, tribunal_code = segments

    if court_segment == "1":
        return "STF"
    if court_segment == "3":
        return "STJ"
    if court_segment == "4":
        return f"TRF{int(tribunal_code)}" if tribunal_code != "00" else None
    if court_segment == "5":
        return "TST" if tribunal_code == "00" else f"TRT{int(tribunal_code)}"
    if court_segment == "6":
        if tribunal_code == "00":
            return "TSE"
        uf = _UF_BY_ESTADUAL_TR.get(tribunal_code)
        return f"TRE-{uf}" if uf else None
    if court_segment == "7":
        return "STM"
    if court_segment == "8":
        uf = _UF_BY_ESTADUAL_TR.get(tribunal_code)
        if uf is None:
            return None
        return "TJDFT" if uf == "DF" else f"TJ{uf}"
    if court_segment == "9":
        return _MILITAR_ESTADUAL_BY_TR.get(tribunal_code)
    return None


def datajud_alias(process_number: str) -> str | None:
    """Alias do índice da API pública do DataJud (ex.: tjsp, trf3, trt2)."""
    acronym = tribunal_acronym(process_number)
    if acronym in (None, "STF"):
        return None
    return acronym.lower()
