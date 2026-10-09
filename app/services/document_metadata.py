import re
import unicodedata
from datetime import date

from sqlalchemy import Engine, text

DOCUMENT_DATE_METADATA_VERSION = 2

DATE_PATTERN = re.compile(
    r"(?P<iso>\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b)"
    r"|(?P<day_first>\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b)"
    r"|(?P<vietnamese>\b(?:ngày\s+)?\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}\b)",
    re.IGNORECASE,
)

EFFECTIVE_CUES = (
    "co hieu luc",
    "hieu luc tu",
    "ngay co hieu luc",
    "ngay hieu luc",
    "ngay ap dung",
    "ap dung tu",
    "thoi gian ap dung",
    "thoi diem ap dung",
    "bat dau ap dung",
    "thi hanh tu",
    "effective from",
)
ISSUED_CUES = (
    "ngay ban hanh",
    "ban hanh ngay",
    "ngay ky",
    "ky ngay",
    "signed on",
    "date of issue",
    "issued on",
)


def _normalize(text_value: str) -> str:
    decomposed = unicodedata.normalize("NFD", text_value.lower())
    return "".join(
        character
        for character in decomposed.replace("đ", "d")
        if unicodedata.category(character) != "Mn"
    )


def normalize_search_text(text_value: str) -> str:
    return _normalize(text_value)


def _parse_date(match: re.Match[str]) -> date | None:
    value = match.group()
    try:
        if match.group("iso"):
            year, month, day = re.split(r"[-/.]", value)
            return date(int(year), int(month), int(day))
        if match.group("day_first"):
            day, month, year = re.split(r"[-/.]", value)
            return date(int(year), int(month), int(day))
        parts = re.findall(r"\d+", value)
        day, month, year = map(int, parts)
        return date(year, month, day)
    except ValueError:
        return None


def extract_document_dates(extracted_text: str) -> dict[str, date | None]:
    issued_dates: list[date] = []
    effective_dates: list[date] = []

    for match in DATE_PATTERN.finditer(extracted_text):
        parsed_date = _parse_date(match)
        if parsed_date is None:
            continue

        line_start = extracted_text.rfind("\n", 0, match.start()) + 1
        line_end = extracted_text.find("\n", match.end())
        if line_end < 0:
            line_end = len(extracted_text)
        line_text = extracted_text[line_start:line_end]
        context_start = line_start
        previous_line_start = extracted_text.rfind("\n", 0, max(0, line_start - 1)) + 1
        previous_line = extracted_text[previous_line_start:line_start].strip()
        if previous_line and not DATE_PATTERN.search(previous_line):
            context_start = previous_line_start
        context = _normalize(extracted_text[context_start:line_end])
        line = _normalize(line_text)

        if any(cue in context for cue in EFFECTIVE_CUES):
            effective_dates.append(parsed_date)
        elif any(cue in context for cue in ISSUED_CUES):
            issued_dates.append(parsed_date)
        elif match.start() < 1500 and "ngay" in line:
            issued_dates.append(parsed_date)

    return {
        "issued_date": max(issued_dates, default=None),
        "effective_date": max(effective_dates, default=None),
    }


def migrate_document_dates(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS issued_date DATE"
        ))
        connection.execute(text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS effective_date DATE"
        ))
        connection.execute(text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT ''"
        ))
        connection.execute(text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS date_metadata_version "
            "INTEGER NOT NULL DEFAULT 0"
        ))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_documents_search_text_fts
            ON documents USING GIN (to_tsvector('simple', search_text))
        """))

        documents = connection.execute(text("""
            SELECT id, extracted_text
            FROM documents
            WHERE date_metadata_version < :version
        """), {"version": DOCUMENT_DATE_METADATA_VERSION}).mappings().all()

        for document in documents:
            extracted_text = document["extracted_text"] or ""
            dates = extract_document_dates(extracted_text)
            connection.execute(
                text("""
                    UPDATE documents
                    SET issued_date = :issued_date,
                        effective_date = :effective_date,
                        search_text = :search_text,
                        date_metadata_version = :version
                    WHERE id = :document_id
                """),
                {
                    "document_id": document["id"],
                    "version": DOCUMENT_DATE_METADATA_VERSION,
                    "search_text": normalize_search_text(extracted_text),
                    **dates,
                },
            )
