"""Geração e unificação de PDFs para resposta ao Procon."""

from __future__ import annotations

from pathlib import Path

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import DriveFileInfo

MAX_UNIFIED_PDF_BYTES = 9 * 1024 * 1024
DEJAVU_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
PDF_EXTENSION = ".pdf"
PDF_MAGIC = b"%PDF"


def local_supporting_file_name(file_info: DriveFileInfo) -> str:
    """Garante extensão local para anexos do Drive (ex.: PDF sem sufixo .pdf)."""
    name = file_info.name.strip()
    if Path(name).suffix:
        return name
    if file_info.mime_type in {"application/pdf"}:
        return f"{name}.pdf"
    if file_info.mime_type == "image/jpeg":
        return f"{name}.jpg"
    if file_info.mime_type == "image/png":
        return f"{name}.png"
    if file_info.mime_type.startswith("image/"):
        return f"{name}.img"
    return name


def is_mergeable_supporting_file(file_info: DriveFileInfo) -> bool:
    """Retorna True para anexos SAC que entram no PDF unificado (sem TXT)."""
    name = file_info.name.casefold()
    if name.endswith(".txt"):
        return False
    if file_info.mime_type.startswith("text/"):
        return False
    if name.endswith(PDF_EXTENSION) or file_info.mime_type == "application/pdf":
        return True
    if file_info.mime_type.startswith("image/"):
        return True
    return any(name.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _resolve_supporting_file_kind(path: Path) -> str | None:
    suffix = path.suffix.casefold()
    if suffix == PDF_EXTENSION:
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    try:
        header = path.read_bytes()[:4]
    except OSError:
        return None
    if header.startswith(PDF_MAGIC):
        return "pdf"
    return None


def text_to_pdf(*, text: str, destination: Path, title: str) -> Path:
    """Converte texto UTF-8 em PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    destination.parent.mkdir(parents=True, exist_ok=True)
    font_name = "Helvetica"
    if DEJAVU_FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont("DejaVu", str(DEJAVU_FONT_PATH)))
        font_name = "DejaVu"

    doc = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    title_style = ParagraphStyle(
        "Title",
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceAfter=12,
    )
    body_style = ParagraphStyle(
        "Body",
        fontName=font_name,
        fontSize=11,
        leading=15,
    )
    safe_title = _escape_reportlab_text(title)
    safe_body = _escape_reportlab_text(text).replace("\n", "<br/>")
    story = [
        Paragraph(safe_title, title_style),
        Spacer(1, 0.4 * cm),
        Paragraph(safe_body, body_style),
    ]
    doc.build(story)
    return destination


def image_to_pdf(*, image_path: Path, destination: Path) -> Path:
    """Converte PNG/JPG em PDF de uma página."""
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as image:
        converted = image.convert("RGB")
        converted.save(destination, "PDF", resolution=120.0)
    return destination


def merge_pdf_files(*, sources: list[Path], destination: Path) -> Path:
    """Une PDFs na ordem informada."""
    from pypdf import PdfReader, PdfWriter

    if not sources:
        raise DriveClientError("Nenhum PDF informado para unificação.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for source in sources:
        if not source.exists():
            raise DriveClientError(f"PDF não encontrado para unificação: {source}")
        reader = PdfReader(str(source))
        for page in reader.pages:
            writer.add_page(page)

    with destination.open("wb") as output_file:
        writer.write(output_file)

    size = destination.stat().st_size
    if size > MAX_UNIFIED_PDF_BYTES:
        raise DriveClientError(
            f"PDF unificado excede 9MB ({size} bytes). "
            "Reduza anexos do SAC ou comprima manualmente.",
        )
    return destination


def build_unified_response_pdf(
    *,
    response_text: str,
    complaint_pdf: Path,
    supporting_files: list[Path],
    destination: Path,
    title: str = "Resposta ao Procon",
) -> Path:
    """Monta PDF unificado: resposta + reclamação + anexos SAC."""
    work_dir = destination.parent
    response_pdf = work_dir / "resposta-completa.pdf"
    text_to_pdf(text=response_text, destination=response_pdf, title=title)

    parts: list[Path] = [response_pdf]
    if complaint_pdf.exists():
        parts.append(complaint_pdf)

    for index, supporting_path in enumerate(supporting_files, start=1):
        kind = _resolve_supporting_file_kind(supporting_path)
        if kind == "pdf":
            parts.append(supporting_path)
            continue
        if kind == "image":
            converted = work_dir / f"anexo-sac-{index}.pdf"
            image_to_pdf(image_path=supporting_path, destination=converted)
            parts.append(converted)
            continue

    return merge_pdf_files(sources=parts, destination=destination)


def _escape_reportlab_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
