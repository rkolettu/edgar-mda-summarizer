import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402


class Item7Tests(unittest.TestCase):
    def test_prefers_body_over_table_of_contents(self):
        filing = (
            "Item 7. Management's Discussion and Analysis ........ Item 8. Financial Statements "
            "Item 7. Management's Discussion and Analysis "
            + "Revenue and operating results. " * 100
            + "Item 8. Financial Statements"
        )
        result = main.extract_item7(filing)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Item 7. Management's Discussion and Analysis Revenue"))
        self.assertNotIn("Item 8", result)

    @patch.object(main, "summarize")
    @patch.object(main, "sec_get")
    @patch.object(main, "find_latest_10k")
    @patch.object(main, "resolve_company")
    def test_missing_item7_does_not_call_model(self, company, filing, sec_get, summarize):
        company.return_value = {"ticker": "TEST", "cik": 123, "name": "Test Corp"}
        filing.return_value = {
            "company_name": "Test Corp", "accession_number": "000-00-1",
            "primary_doc": "filing.htm", "filing_date": "2026-01-01", "report_date": "2025-12-31",
        }
        sec_get.return_value.text = "<html><body>No MD&A heading here.</body></html>"

        with self.assertRaises(HTTPException) as caught:
            main.run_pipeline("TEST")

        self.assertEqual(caught.exception.status_code, 422)
        summarize.assert_not_called()


class SecRequestTests(unittest.TestCase):
    @patch.dict(os.environ, {"SEC_USER_AGENT": ""})
    @patch.object(main.requests, "get")
    def test_missing_user_agent_fails_before_request(self, get):
        with self.assertRaises(HTTPException) as caught:
            main.sec_get(main.TICKERS_URL)
        self.assertEqual(caught.exception.status_code, 500)
        get.assert_not_called()

    @patch.dict(os.environ, {"SEC_USER_AGENT": "Research App (contact@example.com)"})
    @patch.object(main.requests, "get")
    def test_configured_user_agent_sent_to_sec(self, get):
        get.return_value = Mock()
        main.sec_get(main.TICKERS_URL)
        get.assert_called_once_with(
            main.TICKERS_URL,
            headers={"User-Agent": "Research App (contact@example.com)"},
            timeout=main.REQUEST_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
