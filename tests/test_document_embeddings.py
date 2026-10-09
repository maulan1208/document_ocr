import unittest

from app.services.document_embeddings import (
    MAX_CHUNK_CHARACTERS,
    chunk_document_text,
)


class DocumentChunkingTests(unittest.TestCase):
    def test_chunks_preserve_page_numbers_and_overlap(self):
        body = " ".join(f"từ{i}" for i in range(500))
        chunks = chunk_document_text(f"[Trang 3]\n{body}")

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(page_number == 3 for page_number, _ in chunks))
        self.assertTrue(all(content.startswith("[Trang 3]\n") for _, content in chunks))

        first_words = chunks[0][1].removeprefix("[Trang 3]\n").split()
        second_words = chunks[1][1].removeprefix("[Trang 3]\n").split()
        self.assertTrue(set(first_words[-20:]) & set(second_words[:20]))

        for _, content in chunks:
            page_content = content.removeprefix("[Trang 3]\n")
            self.assertLessEqual(len(page_content), MAX_CHUNK_CHARACTERS)

    def test_chunks_text_without_page_markers(self):
        self.assertEqual(
            chunk_document_text("Văn bản ngắn."),
            [(None, "Văn bản ngắn.")],
        )

    def test_ignores_empty_pages(self):
        self.assertEqual(
            chunk_document_text("[Trang 1]\n\n[Trang 2]\nCó nội dung."),
            [(2, "[Trang 2]\nCó nội dung.")],
        )


if __name__ == "__main__":
    unittest.main()
