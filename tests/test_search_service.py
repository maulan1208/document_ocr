import unittest
from unittest.mock import patch

from app.services.search_service import (
    _query_terms,
    _select_relevant_passages,
    is_latest_query,
)
from app.services.document_metadata import normalize_search_text


class _EmptyMappings:
    def mappings(self):
        return self

    def all(self):
        return []


class _SearchDatabase:
    def execute(self, statement, parameters):
        self.statement = str(statement)
        self.parameters = parameters
        return _EmptyMappings()


class VietnameseSearchQueryTests(unittest.TestCase):
    def test_search_can_be_scoped_to_one_conversation(self):
        from app.services.search_service import search_documents

        db = _SearchDatabase()
        with patch(
            "app.services.search_service.create_embeddings",
            return_value=[[0.0] * 1536],
        ):
            search_documents(db, "thưởng", conversation_id=42)

        self.assertEqual(db.parameters["conversation_id"], 42)
        self.assertEqual(db.parameters["embedding_model"], "text-embedding-3-small")
        self.assertIn("conversation_id = CAST(:conversation_id AS BIGINT)", db.statement)
        self.assertIn("c.embedding <=> search_query.embedding", db.statement)
        self.assertIn("lexical_matches", db.statement)
        self.assertIn("semantic_matches", db.statement)

    def test_semantic_search_runs_when_query_has_no_lexical_terms(self):
        from app.services.search_service import search_documents

        db = _SearchDatabase()
        with patch(
            "app.services.search_service.create_embeddings",
            return_value=[[0.0] * 1536],
        ) as embed:
            search_documents(db, "và của là")

        embed.assert_called_once_with(["và của là"])
        self.assertEqual(db.parameters["normalized_ts_query"], "")
        self.assertIn("semantic_matches", db.statement)

    def test_ignores_latest_intent_words_when_searching(self):
        query = "chính sách thưởng mới nhất"

        self.assertEqual(_query_terms(query), ["thưởng"])
        self.assertTrue(is_latest_query(query))

    def test_detects_latest_intent_without_diacritics(self):
        self.assertTrue(is_latest_query("chinh sach thuong moi nhat"))

    def test_normalizes_vietnamese_accents_for_search(self):
        self.assertEqual(
            normalize_search_text("Chính sách thưởng"),
            "chinh sach thuong",
        )

    def test_keeps_content_words_for_regular_search(self):
        self.assertEqual(
            _query_terms("Mức thưởng theo doanh số"),
            ["thưởng", "doanh", "số"],
        )

    def test_why_question_retrieves_explanation_instead_of_only_table_of_contents(self):
        document_text = (
            "[Trang 1]\n"
            "Nội Dung Bài Học\n1. Tại sao cần guardrails?\n"
            "[Trang 2]\n"
            "Tại sao cần guardrails? Agent mạnh nhưng không được kiểm soát "
            "có thể gây nguy hiểm.\n"
            "[Trang 3]\n"
            "Prompt injection có thể khiến agent bỏ qua quy tắc và làm lộ "
            "dữ liệu nhạy cảm."
        )

        snippet = _select_relevant_passages(
            document_text,
            "Tại sao cần guardrails?",
            ["guardrails"],
        )

        self.assertIn("Agent mạnh nhưng không được kiểm soát", snippet)
        self.assertIn("làm lộ dữ liệu nhạy cảm", snippet)
        self.assertNotEqual(snippet, document_text[:3000])


if __name__ == "__main__":
    unittest.main()
