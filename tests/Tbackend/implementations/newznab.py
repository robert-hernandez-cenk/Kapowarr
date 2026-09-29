import unittest
from asyncio import TimeoutError as AsyncTimeoutError
from datetime import datetime, timezone
from unittest.mock import patch

from aiohttp import ClientError

from backend.base.custom_exceptions import ClientNotWorking, CredentialInvalid
from backend.base.definitions import (BrokenClientReason, DownloadType,
                                      QueryKeys, SearchAction, SpecialVersion)
from backend.base.helpers import CommaList
from backend.implementations.indexer_clients.usenet.Newznab import (
    NewznabError, NewznabIndexer, newznab_api_url, parse_newznab_response)
from backend.implementations.query_builder_manager import QueryBuilders
from backend.implementations.query_builders.DDL import DDLQueryBuilder
from backend.implementations.query_builders.Usenet import UsenetQueryBuilder

MODULE = "backend.implementations.indexer_clients.usenet.Newznab"

SEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
<channel>
<title>example</title>
<newznab:response offset="0" total="150"/>
<item>
<title>Batman 001 (2016) (Digital) (Zone-Empire)</title>
<link>https://indexer.example/getnzb/abc.nzb&amp;i=1&amp;r=KEY</link>
<pubDate>Tue, 15 Sep 2026 10:00:00 +0000</pubDate>
<enclosure url="https://indexer.example/getnzb/abc.nzb&amp;i=1&amp;r=KEY" length="0" type="application/x-nzb"/>
<newznab:attr name="category" value="7030"/>
<newznab:attr name="size" value="52428800"/>
</item>
<item>
<title>Batman 002 (2016) (Digital) (Zone-Empire)</title>
<link>https://indexer.example/getnzb/def.nzb</link>
<pubDate>Mon, 01 Jun 2026 10:00:00 +0000</pubDate>
<enclosure url="https://indexer.example/getnzb/def.nzb" length="1000" type="application/x-nzb"/>
</item>
</channel>
</rss>"""

ERROR_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<error code="100" description="Incorrect user credentials"/>'
LIMIT_XML = '<error code="500" description="Request limit reached"/>'


class FakeSession:
    "Stands in for AsyncSession. Responses that are exceptions are raised."

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get_text(self, url, params={}, headers={}, quiet_fail=False):
        self.calls.append((url, dict(params)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            if quiet_fail:
                return ''
            raise response
        return response

    async def close(self):
        return

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_indexer(session):
    indexer = NewznabIndexer.__new__(NewznabIndexer)
    indexer._id = 7
    indexer._title = "NZBIdx"
    indexer._url = "https://indexer.example"
    indexer._enabled = True
    indexer._api_key = "KEY"
    indexer._categories = CommaList("7030")
    indexer.session = session
    indexer.rate_limited = False
    return indexer


def local_naive(dt):
    return dt.astimezone().replace(tzinfo=None)


class parse_newznab(unittest.TestCase):
    def test_items_and_paging(self):
        page = parse_newznab_response(SEARCH_XML)
        self.assertEqual((page.offset, page.total), (0, 150))
        self.assertEqual(len(page.items), 2)

        first = page.items[0]
        self.assertEqual(
            first.title, "Batman 001 (2016) (Digital) (Zone-Empire)"
        )
        self.assertEqual(
            first.link, "https://indexer.example/getnzb/abc.nzb&i=1&r=KEY"
        )
        self.assertEqual(first.size, 52428800)
        self.assertEqual(
            first.pub_date,
            local_naive(datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc))
        )
        self.assertEqual(page.items[1].size, 1000)

    def test_error_response(self):
        with self.assertRaises(NewznabError) as cm:
            parse_newznab_response(ERROR_XML)
        self.assertEqual(cm.exception.code, 100)

    def test_invalid_xml(self):
        with self.assertRaises(NewznabError) as cm:
            parse_newznab_response("<html>nope")
        self.assertEqual(cm.exception.code, -1)

    def test_api_url(self):
        self.assertEqual(
            newznab_api_url("https://x.org"), "https://x.org/api"
        )
        self.assertEqual(
            newznab_api_url("https://x.org/api"), "https://x.org/api"
        )


class newznab_indexer(unittest.IsolatedAsyncioTestCase):
    async def test_search_builds_results(self):
        session = FakeSession([SEARCH_XML])
        result = await make_indexer(session).search(
            {"query": "Batman #1", "page": 1, "total_available_variations": 2}
        )

        self.assertTrue(result.next_page_available)
        self.assertEqual(len(result.results), 2)
        first = result.results[0]
        self.assertEqual(first["series"], "Batman")
        self.assertEqual(first["issue_number"], 1.0)
        self.assertEqual(first["indexer_id"], 7)
        self.assertEqual(first["indexer_title"], "NZBIdx")
        self.assertEqual(first["size"], 52428800)

        url, params = session.calls[0]
        self.assertEqual(url, "https://indexer.example/api")
        self.assertEqual(params["t"], "search")
        self.assertEqual(params["q"], "Batman #1")
        self.assertEqual(params["offset"], 0)
        self.assertEqual(params["cat"], "7030")
        self.assertEqual(params["apikey"], "KEY")

    async def test_second_page_offset(self):
        session = FakeSession([SEARCH_XML])
        await make_indexer(session).search(
            {"query": "Batman", "page": 2, "total_available_variations": 1}
        )
        self.assertEqual(session.calls[0][1]["offset"], 100)

    async def test_rate_limit_stops_indexer(self):
        session = FakeSession([LIMIT_XML])
        indexer = make_indexer(session)
        query = {"query": "Batman", "page": 1, "total_available_variations": 1}

        first = await indexer.search(query)
        second = await indexer.search(query)

        self.assertEqual(first.results, [])
        self.assertFalse(first.next_page_available)
        self.assertEqual(second.results, [])
        self.assertEqual(len(session.calls), 1)

    async def test_no_response(self):
        session = FakeSession([ClientError()])
        result = await make_indexer(session).search(
            {"query": "Batman", "page": 1, "total_available_variations": 1}
        )
        self.assertEqual(result.results, [])
        self.assertFalse(result.next_page_available)

    async def test_discover_stops_at_last_check(self):
        session = FakeSession([SEARCH_XML])
        results = await make_indexer(session).discover(datetime(2026, 8, 1))

        self.assertEqual(
            [r["display_title"] for r in results],
            ["Batman 001 (2016) (Digital) (Zone-Empire)"]
        )
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("q", session.calls[0][1])


class newznab_test(unittest.TestCase):
    def test_valid(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession([SEARCH_XML])):
            NewznabIndexer.test(
                "https://indexer.example", api_key="KEY", categories="7030"
            )

    def test_bad_key(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession([ERROR_XML])):
            with self.assertRaises(CredentialInvalid):
                NewznabIndexer.test(
                    "https://indexer.example", api_key="BAD", categories="7030"
                )

    def test_missing_key(self):
        with self.assertRaises(CredentialInvalid):
            NewznabIndexer.test("https://indexer.example", categories="7030")

    def test_not_newznab(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession(["<html></html>"])):
            with self.assertRaises(ClientNotWorking):
                NewznabIndexer.test(
                    "https://indexer.example", api_key="KEY", categories="7030"
                )

    def test_connection_error(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession([ClientError()])):
            with self.assertRaises(ClientNotWorking):
                NewznabIndexer.test(
                    "https://indexer.example", api_key="KEY", categories="7030"
                )

    def test_timeout(self):
        with patch(
            f"{MODULE}.AsyncSession",
            return_value=FakeSession([AsyncTimeoutError()])
        ):
            with self.assertRaises(ClientNotWorking) as cm:
                NewznabIndexer.test(
                    "https://indexer.example", api_key="KEY", categories="7030"
                )
        self.assertEqual(
            cm.exception.reason, BrokenClientReason.CONNECTION_ERROR
        )


class usenet_query_builder(unittest.TestCase):
    def test_registered_and_same_queries_as_ddl(self):
        self.assertIs(
            QueryBuilders.get_builder(DownloadType.USENET), UsenetQueryBuilder
        )
        keys = QueryKeys(["Batman"], 2016, 1, SpecialVersion.NORMAL, None)
        self.assertEqual(
            UsenetQueryBuilder().next_query(SearchAction.SEARCH_VOLUME, keys),
            DDLQueryBuilder().next_query(SearchAction.SEARCH_VOLUME, keys)
        )
