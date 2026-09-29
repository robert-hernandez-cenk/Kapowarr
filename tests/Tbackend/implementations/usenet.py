import unittest
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import DownloadLinkBroken
from backend.implementations import usenet
from backend.implementations.usenet import (extract_nzb_name, fetch_nzb,
                                            is_nzb, pop_cached_nzb,
                                            redact_nzb_link)

NZB_CONTENT = b"""<?xml version="1.0" encoding="iso-8859-1" ?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
<head><meta type="name">Batman 001 (2016) (Meta)</meta></head>
<file poster="a@b" date="1" subject="x"><groups><group>alt.binaries.comics</group></groups>
<segments><segment bytes="1" number="1">id@x</segment></segments></file>
</nzb>"""


def fake_response(content, headers=None, ok=True):
    response = MagicMock()
    response.ok = ok
    response.content = content
    response.headers = headers or {}
    return response


class nzb_name(unittest.TestCase):
    def test_header_wins(self):
        self.assertEqual(
            extract_nzb_name(
                {"X-DNZB-Name": " Batman 001 (2016) ",
                 "Content-Disposition": 'attachment; filename="Other.nzb"'},
                NZB_CONTENT
            ),
            "Batman 001 (2016)"
        )

    def test_content_disposition(self):
        self.assertEqual(
            extract_nzb_name(
                {"content-disposition": 'attachment; filename="Batman 001 (2016).nzb"'},
                b"<nzb/>"
            ),
            "Batman 001 (2016)"
        )

    def test_meta_name(self):
        self.assertEqual(
            extract_nzb_name({}, NZB_CONTENT), "Batman 001 (2016) (Meta)"
        )

    def test_nothing_found(self):
        self.assertIsNone(extract_nzb_name({}, b"<nzb/>"))

    def test_is_nzb(self):
        self.assertTrue(is_nzb(NZB_CONTENT))
        self.assertTrue(is_nzb(b"<nzb/>"))
        self.assertFalse(is_nzb(b'<error code="100" description="x"/>'))
        self.assertFalse(is_nzb(b"not xml"))


class nzb_fetching(unittest.TestCase):
    def setUp(self):
        usenet._nzb_cache.clear()

    def test_fetch_caches_and_pop_clears(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(
                NZB_CONTENT, {"X-DNZB-Name": "Batman 001 (2016)"}
            )

            first = fetch_nzb("https://idx/a.nzb")
            second = fetch_nzb("https://idx/a.nzb")

        self.assertIs(first, second)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(first.name, "Batman 001 (2016)")
        self.assertEqual(first.filename, "Batman 001 (2016).nzb")
        self.assertEqual(first.content, NZB_CONTENT)
        self.assertIs(pop_cached_nzb("https://idx/a.nzb"), first)
        self.assertIsNone(pop_cached_nzb("https://idx/a.nzb"))

    def test_error_response_is_broken_link(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(
                b'<error code="300" description="No such item"/>'
            )
            with self.assertRaises(DownloadLinkBroken):
                fetch_nzb("https://idx/gone.nzb")

    def test_http_error_is_broken_link(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(b"", ok=False)
            with self.assertRaises(DownloadLinkBroken):
                fetch_nzb("https://idx/404.nzb")

    def test_unnamed_nzb_gets_fallback_name(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(b"<nzb/>")
            self.assertEqual(
                fetch_nzb("https://idx/b.nzb").name, "Unknown release"
            )

    def test_broken_link_with_apikey_redacts(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(
                b'<error code="300" description="No such item"/>'
            )
            link = "https://idx/getnzb/a.nzb?t=get&id=abc&apikey=SECRET"
            with self.assertRaises(DownloadLinkBroken) as cm:
                fetch_nzb(link)
            self.assertNotIn("SECRET", str(cm.exception.link))
            self.assertIn("apikey=<redacted>", str(cm.exception.link))


class nzb_link_redaction(unittest.TestCase):
    def test_redacts_apikey_parameter(self):
        link = "https://idx/getnzb/a.nzb?t=get&id=abc&apikey=KEY123"
        result = redact_nzb_link(link)
        self.assertIn("apikey=<redacted>", result)
        self.assertNotIn("KEY123", result)
        self.assertIn("id=abc", result)

    def test_redacts_api_key_parameter(self):
        link = "https://idx/getnzb/a.nzb?api_key=SECRET456"
        result = redact_nzb_link(link)
        self.assertIn("api_key=<redacted>", result)
        self.assertNotIn("SECRET456", result)

    def test_redacts_r_parameter(self):
        link = "https://api.nzb.su/getnzb/GUID.nzb&i=123&r=KEY789"
        result = redact_nzb_link(link)
        self.assertIn("r=<redacted>", result)
        self.assertNotIn("KEY789", result)
        self.assertIn("i=<redacted>", result)

    def test_redacts_i_parameter(self):
        link = "https://api.nzb.su/getnzb/GUID.nzb?i=456&r=KEY"
        result = redact_nzb_link(link)
        self.assertIn("i=<redacted>", result)
        self.assertNotIn("456", result)

    def test_case_insensitive_redaction(self):
        link = "https://idx/a.nzb?ApiKey=UPPER&r=LOWER&API_KEY=MIX"
        result = redact_nzb_link(link)
        self.assertNotIn("UPPER", result)
        self.assertNotIn("LOWER", result)
        self.assertNotIn("MIX", result)
        self.assertEqual(result.count("<redacted>"), 3)

    def test_leaves_keyless_link_unchanged(self):
        link = "https://idx/getnzb/a.nzb?t=get&id=abc"
        result = redact_nzb_link(link)
        self.assertEqual(result, link)
