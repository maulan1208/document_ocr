import unittest
from datetime import date

from app.services.document_metadata import extract_document_dates


class DocumentDateExtractionTests(unittest.TestCase):
    def test_extracts_issued_and_effective_dates(self):
        text = (
            "CHÍNH SÁCH THƯỞNG\n"
            "Ban hành ngày 15/03/2024\n"
            "Có hiệu lực từ ngày 01 tháng 04 năm 2024"
        )

        self.assertEqual(
            extract_document_dates(text),
            {
                "issued_date": date(2024, 3, 15),
                "effective_date": date(2024, 4, 1),
            },
        )

    def test_extracts_application_period_as_effective_date(self):
        expected = {
            "issued_date": None,
            "effective_date": date(2026, 3, 23),
        }
        self.assertEqual(
            extract_document_dates("Thời gian áp dụng: 23/03/2026"),
            expected,
        )
        self.assertEqual(
            extract_document_dates("Ngày áp dụng: 23/03/2026"),
            expected,
        )

    def test_does_not_treat_trial_dates_as_policy_dates(self):
        text = "Giai đoạn thử nghiệm từ 02/12/2024 đến 30/12/2024"

        self.assertEqual(
            extract_document_dates(text),
            {"issued_date": None, "effective_date": None},
        )


if __name__ == "__main__":
    unittest.main()
