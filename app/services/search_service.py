import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.document_metadata import normalize_search_text
from app.services.document_embeddings import (
    EMBEDDING_MODEL,
    create_embeddings,
)

SEARCH_STOPWORDS = {
    "ap", "bao", "ban", "biet", "cac", "cai", "cap", "cho", "chinh",
    "co", "cua", "dang", "gi", "gan", "hay", "hien", "hiennay",
    "hienhanh", "hientai", "khong", "la", "lieu", "long", "moi", "nay",
    "nhat", "nhu", "noi", "nhung", "sach", "tai", "the", "tich", "toi",
    "tom", "trong", "va", "ve", "vui", "duoc", "nao", "theo", "muc",
    "sao", "can", "ly", "do",
}

PAGE_MARKER = re.compile(r"(?=\[Trang\s+\d+\])", re.IGNORECASE)
PAGE_LABEL = re.compile(r"^\[Trang\s+(\d+)\]\s*", re.IGNORECASE)
TABLE_OF_CONTENTS_MARKERS = (
    "noi dung bai hoc",
    "muc tieu ngay",
    "muc luc",
    "deliverable cuoi ngay",
)


def _normalize_word(word: str) -> str:
    decomposed = unicodedata.normalize("NFD", word.lower())
    return "".join(
        character
        for character in decomposed.replace("đ", "d")
        if unicodedata.category(character) != "Mn"
    )


def _query_terms(query: str) -> list[str]:
    words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    meaningful_words = [
        word for word in words if _normalize_word(word) not in SEARCH_STOPWORDS
    ]
    if meaningful_words:
        return list(dict.fromkeys(meaningful_words))

    normalized_words = {_normalize_word(word) for word in words}
    if {"chinh", "sach"} <= normalized_words:
        return ["chính", "sách"]
    return []


def is_latest_query(query: str) -> bool:
    normalized_query = _normalize_word(query)
    return (
        "moi nhat" in normalized_query
        or "gan day" in normalized_query
        or "hien hanh" in normalized_query
        or "hien tai" in normalized_query
        or "cap nhat" in normalized_query
        or "dang ap dung" in normalized_query
        or "latest" in normalized_query
        or "most recent" in normalized_query
    )


def _select_relevant_passages(text: str, query: str, terms: list[str]) -> str:
    pages = [page.strip() for page in PAGE_MARKER.split(text) if page.strip()]
    if not pages:
        pages = [text.strip()]

    normalized_terms = [normalize_search_text(term).lower() for term in terms]
    asks_why = bool(
        re.search(r"\b(tai sao|vi sao|ly do|why)\b", _normalize_word(query))
    )
    ranked_pages: list[tuple[int, int, str]] = []

    for index, page in enumerate(pages):
        label_match = PAGE_LABEL.match(page)
        page_number = int(label_match.group(1)) if label_match else index + 1
        body = PAGE_LABEL.sub("", page).strip()
        normalized_body = normalize_search_text(body).lower()
        term_score = sum(
            min(2, len(re.findall(rf"\b{re.escape(term)}\b", normalized_body)))
            for term in normalized_terms
        )
        lines = [
            normalize_search_text(line).lower()
            for line in body.splitlines()
        ]
        intent_score = (
            4
            if asks_why
            and any(
                re.search(r"\b(tai sao|vi sao|ly do|why)\b", line)
                and any(
                    re.search(rf"\b{re.escape(term)}\b", line)
                    for term in normalized_terms
                )
                for line in lines
            )
            else 0
        )
        outline_penalty = (
            4
            if any(marker in normalized_body for marker in TABLE_OF_CONTENTS_MARKERS)
            else 0
        )
        ranked_pages.append(
            (term_score + intent_score - outline_penalty, index, page)
        )

    matched_pages = sorted(
        (page for page in ranked_pages if page[0] > 0),
        key=lambda page: (-page[0], page[1]),
    )
    if not matched_pages:
        return text[:3000]

    if asks_why:
        best_match_index = matched_pages[0][1]
        selected_indexes = {
            index
            for index in range(best_match_index, min(best_match_index + 3, len(pages)))
        }
    else:
        selected_indexes = {page[1] for page in matched_pages[:3]}

    return "\n\n".join(
        page[:1800]
        for _, index, page in sorted(ranked_pages, key=lambda page: page[1])
        if index in selected_indexes
    )

def search_documents(
    db: Session,
    query: str,
    limit: int = 5,
    document_id: int | None = None,
    conversation_id: int | None = None,
) -> list[dict]:
    terms = _query_terms(query)
    normalized_ts_query = " | ".join(
        normalize_search_text(term) for term in terms
    )
    prefer_latest = is_latest_query(query)
    query_embedding = create_embeddings([query])[0]
    sql = text("""
        WITH search_query AS (
            SELECT
                to_tsquery('simple', :normalized_ts_query) AS text_query,
                CAST(:query_embedding AS vector(1536)) AS embedding
        ),
        lexical_matches AS (
            SELECT
                ranked.id,
                ranked.document_id,
                1.0 / (60 + ranked.search_rank) AS score
            FROM (
                SELECT
                    c.id,
                    c.document_id,
                    row_number() OVER (
                        ORDER BY ts_rank(
                            to_tsvector('simple', c.search_text),
                            search_query.text_query
                        ) DESC
                    ) AS search_rank
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                CROSS JOIN search_query
                WHERE d.status = 'processed'
                  AND c.embedding_model = :embedding_model
                  AND search_query.text_query <> ''::tsquery
                  AND to_tsvector('simple', c.search_text)
                      @@ search_query.text_query
                  AND (
                      CAST(:document_id AS BIGINT) IS NULL
                      OR d.id = CAST(:document_id AS BIGINT)
                  )
                  AND (
                      CAST(:conversation_id AS BIGINT) IS NULL
                      OR d.conversation_id = CAST(:conversation_id AS BIGINT)
                  )
                ORDER BY ts_rank(
                    to_tsvector('simple', c.search_text),
                    search_query.text_query
                ) DESC
                LIMIT :candidate_limit
            ) AS ranked
        ),
        semantic_matches AS (
            SELECT
                ranked.id,
                ranked.document_id,
                1.0 / (60 + ranked.search_rank) AS score
            FROM (
                SELECT
                    c.id,
                    c.document_id,
                    row_number() OVER (
                        ORDER BY c.embedding <=> search_query.embedding
                    ) AS search_rank
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                CROSS JOIN search_query
                WHERE d.status = 'processed'
                  AND c.embedding_model = :embedding_model
                  AND (
                      CAST(:document_id AS BIGINT) IS NULL
                      OR d.id = CAST(:document_id AS BIGINT)
                  )
                  AND (
                      CAST(:conversation_id AS BIGINT) IS NULL
                      OR d.conversation_id = CAST(:conversation_id AS BIGINT)
                  )
                ORDER BY c.embedding <=> search_query.embedding
                LIMIT :candidate_limit
            ) AS ranked
        ),
        chunk_scores AS (
            SELECT
                matches.id,
                matches.document_id,
                SUM(matches.score) AS score
            FROM (
                SELECT * FROM lexical_matches
                UNION ALL
                SELECT * FROM semantic_matches
            ) AS matches
            GROUP BY matches.id, matches.document_id
        ),
        document_scores AS (
            SELECT
                cs.document_id,
                SUM(cs.score) AS relevance,
                COALESCE(d.effective_date, d.issued_date) AS sort_date
            FROM chunk_scores AS cs
            JOIN documents AS d ON d.id = cs.document_id
            GROUP BY cs.document_id, d.effective_date, d.issued_date
        ),
        top_documents AS (
            SELECT
                document_id,
                relevance,
                row_number() OVER (
                    ORDER BY
                        CASE WHEN :prefer_latest THEN sort_date END DESC NULLS LAST,
                        relevance DESC,
                        sort_date DESC NULLS LAST,
                        document_id DESC
                ) AS document_rank
            FROM document_scores
            ORDER BY
                CASE WHEN :prefer_latest THEN sort_date END DESC NULLS LAST,
                relevance DESC,
                sort_date DESC NULLS LAST,
                document_id DESC
            LIMIT :limit
        ),
        ranked_chunks AS (
            SELECT
                cs.id,
                cs.document_id,
                cs.score,
                row_number() OVER (
                    PARTITION BY cs.document_id ORDER BY cs.score DESC, cs.id
                ) AS chunk_rank
            FROM chunk_scores AS cs
        )
        SELECT
            d.id,
            d.original_filename,
            d.page_count,
            d.extraction_method,
            d.issued_date,
            d.effective_date,
            c.content AS snippet,
            td.document_rank,
            rc.chunk_rank
        FROM top_documents AS td
        JOIN documents AS d ON d.id = td.document_id
        JOIN ranked_chunks AS rc ON rc.document_id = td.document_id
        JOIN document_chunks AS c ON c.id = rc.id
        WHERE rc.chunk_rank <= 3
        ORDER BY td.document_rank, rc.chunk_rank
    """)

    rows = db.execute(
        sql,
        {
            "normalized_ts_query": normalized_ts_query,
            "query_embedding": "[" + ",".join(map(str, query_embedding)) + "]",
            "embedding_model": EMBEDDING_MODEL,
            "document_id": document_id,
            "conversation_id": conversation_id,
            "prefer_latest": prefer_latest,
            "limit": limit,
            "candidate_limit": max(limit * 10, 50),
        },
    ).mappings().all()

    results = {}
    for row in rows:
        result = results.setdefault(
            row["id"],
            {
                "id": row["id"],
                "filename": row["original_filename"],
                "page_count": row["page_count"],
                "extraction_method": row["extraction_method"],
                "issued_date": row["issued_date"],
                "effective_date": row["effective_date"],
                "snippets": [],
            },
        )
        result["snippets"].append(row["snippet"])

    for result in results.values():
        result["snippet"] = "\n\n".join(result.pop("snippets"))
    return list(results.values())

def build_context(results: list[dict]) -> str:
    if not results:
        return ""

    sections = []

    for item in results:
        sections.append(
            f"[Nguồn: {item['filename']} | "
            f"ID tài liệu: {item['id']} | "
            f"Ngày hiệu lực: {item.get('effective_date') or 'không xác định'} | "
            f"Ngày ban hành: {item.get('issued_date') or 'không xác định'}]\n"
            f"{item['snippet']}"
        )

    return "\n\n".join(sections)