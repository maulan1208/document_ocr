from io import BytesIO
import logging
from zipfile import BadZipFile, ZipFile
from time import perf_counter

import fitz
import pytesseract
from docx import Document as WordDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


class DocumentProcessingError(ValueError):
    pass


def extract_image_text(file_bytes: bytes, page_number: int | None = None) -> str:
    """Nhận diện chữ từ ảnh bằng Tesseract OCR."""
    started_at = perf_counter()
    logger.info("ocr_started page=%s", page_number or 1)

    try:
        image = Image.open(BytesIO(file_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
        text = pytesseract.image_to_string(image, lang="vie+eng").strip()
    except Exception:
        logger.exception(
            "ocr_failed page=%s duration_ms=%.2f",
            page_number or 1,
            (perf_counter() - started_at) * 1000,
        )
        raise

    logger.info(
        "ocr_completed page=%s text_length=%d duration_ms=%.2f",
        page_number or 1,
        len(text),
        (perf_counter() - started_at) * 1000,
    )
    return text


def extract_pdf_text(file_bytes: bytes) -> tuple[str, int, str]:
    """Đọc PDF; OCR các trang không có text."""
    pdf = fitz.open(stream=file_bytes, filetype="pdf")

    page_texts = []
    ocr_pages = 0

    try:
        for page in pdf:
            text = page.get_text("text").strip()

            # Nếu trang gần như không có text, thử OCR.
            if len(text) < 20:
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    alpha=False,
                )
                image_bytes = pix.tobytes("png")
                text = extract_image_text(image_bytes, page.number + 1)
                ocr_pages += 1

            page_texts.append(f"[Trang {page.number + 1}]\n{text}")

        if ocr_pages == 0:
            method = "text"
        elif ocr_pages == len(pdf):
            method = "ocr"
        else:
            method = "mixed"

        return "\n\n".join(page_texts), len(pdf), method

    finally:
        pdf.close()


def extract_txt_text(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        if file_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                return file_bytes.decode("utf-16")
            except UnicodeDecodeError as utf16_error:
                raise DocumentProcessingError(
                    "File TXT phải dùng mã hóa UTF-8 hoặc UTF-16 hợp lệ."
                ) from utf16_error
        raise DocumentProcessingError(
            "File TXT phải dùng mã hóa UTF-8 hoặc UTF-16 có BOM."
        ) from error


def extract_docx_text(file_bytes: bytes) -> str:
    try:
        with ZipFile(BytesIO(file_bytes)) as archive:
            if not {
                "[Content_Types].xml",
                "word/document.xml",
            }.issubset(archive.namelist()):
                raise DocumentProcessingError(
                    "File không có cấu trúc DOCX hợp lệ."
                )
        document = WordDocument(BytesIO(file_bytes))
    except DocumentProcessingError:
        raise
    except (
        BadZipFile,
        PackageNotFoundError,
        KeyError,
        XMLSyntaxError,
        ValueError,
    ) as error:
        raise DocumentProcessingError(
            "File không có cấu trúc DOCX hợp lệ."
        ) from error

    content = []
    for element in document.element.body.iterchildren():
        if isinstance(element, CT_P):
            paragraph = Paragraph(element, document)
            if paragraph.text.strip():
                content.append(paragraph.text.strip())
        elif isinstance(element, CT_Tbl):
            table = Table(element, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    content.append(" | ".join(cells))
    return "\n".join(content)


def process_document(file_bytes: bytes, file_type: str) -> tuple[str, int, str]:
    """Điểm gọi thống nhất cho PDF và ảnh."""
    started_at = perf_counter()
    logger.info(
        "document_processing_started file_type=%s file_size_bytes=%d",
        file_type,
        len(file_bytes),
    )

    try:
        if file_type == "pdf":
            result = extract_pdf_text(file_bytes)
        elif file_type in {"png", "jpg", "jpeg", "tiff", "tif"}:
            text = extract_image_text(file_bytes)
            result = text, 1, "ocr"
        elif file_type == "txt":
            result = extract_txt_text(file_bytes), 1, "text"
        elif file_type == "docx":
            result = extract_docx_text(file_bytes), 1, "text"
        else:
            raise DocumentProcessingError("Định dạng file chưa được hỗ trợ.")
    except Exception:
        logger.exception(
            "document_processing_failed file_type=%s duration_ms=%.2f",
            file_type,
            (perf_counter() - started_at) * 1000,
        )
        raise

    text, page_count, method = result
    logger.info(
        "document_processing_completed file_type=%s pages=%d method=%s "
        "text_length=%d duration_ms=%.2f",
        file_type,
        page_count,
        method,
        len(text),
        (perf_counter() - started_at) * 1000,
    )
    return result