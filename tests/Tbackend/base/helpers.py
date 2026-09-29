import unittest
from unittest.mock import MagicMock, patch

from backend.base.helpers import Session, redact_url_secrets


class nzb_link_redaction(unittest.TestCase):
    def test_redacts_apikey_parameter(self):
        link = "https://idx/getnzb/a.nzb?t=get&id=abc&apikey=KEY123"
        result = redact_url_secrets(link)
        self.assertIn("apikey=<redacted>", result)
        self.assertNotIn("KEY123", result)
        self.assertIn("id=abc", result)

    def test_redacts_api_key_parameter(self):
        link = "https://idx/getnzb/a.nzb?api_key=SECRET456"
        result = redact_url_secrets(link)
        self.assertIn("api_key=<redacted>", result)
        self.assertNotIn("SECRET456", result)

    def test_redacts_r_parameter(self):
        link = "https://api.nzb.su/getnzb/GUID.nzb&i=123&r=KEY789"
        result = redact_url_secrets(link)
        self.assertIn("r=<redacted>", result)
        self.assertNotIn("KEY789", result)
        self.assertIn("i=<redacted>", result)

    def test_redacts_i_parameter(self):
        link = "https://api.nzb.su/getnzb/GUID.nzb?i=456&r=KEY"
        result = redact_url_secrets(link)
        self.assertIn("i=<redacted>", result)
        self.assertNotIn("456", result)

    def test_case_insensitive_redaction(self):
        link = "https://idx/a.nzb?ApiKey=UPPER&r=LOWER&API_KEY=MIX"
        result = redact_url_secrets(link)
        self.assertNotIn("UPPER", result)
        self.assertNotIn("LOWER", result)
        self.assertNotIn("MIX", result)
        self.assertEqual(result.count("<redacted>"), 3)

    def test_leaves_keyless_link_unchanged(self):
        link = "https://idx/getnzb/a.nzb?t=get&id=abc"
        result = redact_url_secrets(link)
        self.assertEqual(result, link)

    def test_does_not_redact_unrelated_parameters_ending_in_r_or_i(self):
        # Parameters whose names end in 'r' or 'i' should not be redacted
        # unless they are exactly 'r' or 'i'
        link = ("https://idx/a.nzb?dir=/tmp/x&user=bob&ui=dark&referer=http"
                "&counter=5&download_dir=/path&id=abc&apikey=SECRET&r=KEY&i=ID")
        result = redact_url_secrets(link)

        # Unrelated parameters should be unchanged
        self.assertIn("dir=/tmp/x", result)
        self.assertIn("user=bob", result)
        self.assertIn("ui=dark", result)
        self.assertIn("referer=http", result)
        self.assertIn("counter=5", result)
        self.assertIn("download_dir=/path", result)
        self.assertIn("id=abc", result)

        # Sensitive parameters should be redacted
        self.assertIn("apikey=<redacted>", result)
        self.assertIn("r=<redacted>", result)
        self.assertIn("i=<redacted>", result)

        # Original secret values should not appear
        self.assertNotIn("SECRET", result)
        self.assertNotIn("r=KEY", result)
        self.assertNotIn("i=ID", result)


class session_logging(unittest.TestCase):
    def test_4xx_warning_is_redacted(self):
        link = "https://idx/api?t=search&apikey=SECRET"
        response = MagicMock()
        response.status_code = 404
        response.request.method = "GET"
        response.request.url = link
        response.text = "not found"

        with patch("backend.implementations.flaresolverr.FlareSolverr") as fs, \
                patch("backend.base.helpers.RSession.request",
                      return_value=response), \
                patch("backend.base.helpers.LOGGER") as logger:
            fs.return_value.get_ua_cookies.return_value = ("ua", "")
            Session().request("GET", link)

        self.assertTrue(logger.warning.called)
        for call in logger.warning.call_args_list + logger.debug.call_args_list:
            self.assertNotIn("SECRET", " ".join(map(str, call.args)))
        self.assertIn(
            "apikey=<redacted>",
            " ".join(map(str, logger.warning.call_args.args))
        )
