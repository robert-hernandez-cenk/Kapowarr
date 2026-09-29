# -*- coding: utf-8 -*-

"""
Indexer client for Newznab compatible Usenet indexers
(NZBGeek, NZB.su, DrunkenSlug, etc.)
"""

from asyncio import run
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Union
from xml.etree.ElementTree import Element, ParseError, fromstring

from aiohttp import ClientError

from backend.base.custom_exceptions import ClientNotWorking, CredentialInvalid
from backend.base.definitions import (BrokenClientReason, DownloadType,
                                      IndexerClientField as ICF, QueryResult,
                                      SearchQuery, SearchResultData)
from backend.base.file_extraction import extract_filename_data
from backend.base.helpers import AsyncSession
from backend.base.logging import LOGGER
from backend.implementations.indexer_client_manager import (BaseIndexerClient,
                                                            IndexerClients)

NEWZNAB_NAMESPACE = "http://www.newznab.com/DTD/2010/feeds/attributes/"
PAGE_SIZE = 100
DISCOVER_MAX_PAGES = 5
AUTH_ERROR_CODES = (100, 101, 102)
LIMIT_ERROR_CODES = (429, 500, 501)


class NewznabError(Exception):
    "The Newznab API returned an error, or a response that couldn't be parsed"

    def __init__(self, code: int, description: str) -> None:
        super().__init__(f"Newznab error {code}: {description}")
        self.code = code
        self.description = description
        return


@dataclass
class NewznabItem:
    title: str
    link: str
    size: int
    pub_date: Union[datetime, None]


@dataclass
class NewznabPage:
    items: List[NewznabItem]
    offset: int
    total: int


def newznab_api_url(url: str) -> str:
    """Get the API endpoint of a Newznab indexer.

    Args:
        url (str): The URL of the indexer, with or without `/api` at the end.

    Returns:
        str: The URL of the API endpoint.
    """
    if url.endswith("/api"):
        return url
    return f"{url}/api"


def _to_int(value: Union[str, None], default: int) -> int:
    try:
        return int(value)  # type: ignore
    except (TypeError, ValueError):
        return default


def _parse_pub_date(value: Union[str, None]) -> Union[datetime, None]:
    """Parse an RSS pubDate into a naive datetime in local time, so it can be
    compared with the naive datetimes that the rest of Kapowarr uses.
    """
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError):
        return None

    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone().replace(tzinfo=None)


def _parse_item(item: Element) -> Union[NewznabItem, None]:
    title = (item.findtext("title") or "").strip()
    enclosure = item.find("enclosure")

    link = ""
    if enclosure is not None:
        link = (enclosure.get("url") or "").strip()
    if not link:
        link = (item.findtext("link") or "").strip()

    if not title or not link:
        return None

    size = -1
    for attr in item.findall(f"{{{NEWZNAB_NAMESPACE}}}attr"):
        if attr.get("name") == "size":
            size = _to_int(attr.get("value"), -1)
    if size <= 0 and enclosure is not None:
        size = _to_int(enclosure.get("length"), -1)
    if size <= 0:
        size = -1

    return NewznabItem(
        title=title,
        link=link,
        size=size,
        pub_date=_parse_pub_date(item.findtext("pubDate"))
    )


def parse_newznab_response(xml_text: str) -> NewznabPage:
    """Parse a Newznab search response.

    Args:
        xml_text (str): The body of the response.

    Raises:
        NewznabError: The indexer returned an error, or the response is not
            a Newznab response. Code `-1` when the response couldn't be parsed.

    Returns:
        NewznabPage: The items and paging info.
    """
    try:
        root = fromstring(xml_text)
    except ParseError:
        raise NewznabError(-1, "Response is not valid XML")

    if root.tag == "error":
        raise NewznabError(
            _to_int(root.get("code"), -1),
            root.get("description") or ""
        )

    channel = root.find("channel")
    if channel is None:
        raise NewznabError(-1, "Response has no channel")

    items: List[NewznabItem] = []
    for item_el in channel.findall("item"):
        item = _parse_item(item_el)
        if item is not None:
            items.append(item)

    response = channel.find(f"{{{NEWZNAB_NAMESPACE}}}response")
    offset, total = 0, len(items)
    if response is not None:
        offset = _to_int(response.get("offset"), 0)
        total = _to_int(response.get("total"), offset + len(items))

    return NewznabPage(items=items, offset=offset, total=total)


@IndexerClients.register_client(
    DownloadType.USENET, 'Newznab',
    (ICF.TITLE, ICF.ENABLED, ICF.URL, ICF.API_KEY, ICF.CATEGORIES),
    allow_multiple_instances=True
)
class NewznabIndexer(BaseIndexerClient):
    def __init__(self, indexer_id: int) -> None:
        super().__init__(indexer_id)

        self.session: Union[AsyncSession, None] = None
        self.rate_limited = False
        "Whether the indexer reported that its request limit is reached"

        return

    async def _fetch_page(
        self,
        params: Dict[str, Any]
    ) -> Union[NewznabPage, None]:
        """Make a request to the API of the indexer.

        Args:
            params (Dict[str, Any]): Params added on top of the API key,
                categories and page size.

        Returns:
            Union[NewznabPage, None]: The page, or `None` if the request
                failed (which is logged).
        """
        if self.rate_limited:
            return None

        if not self.session:
            self.session = AsyncSession()

        text = await self.session.get_text(
            newznab_api_url(self._url),
            params={
                "apikey": self._api_key or "",
                "cat": ",".join(self._categories or []),
                "limit": PAGE_SIZE,
                **params
            },
            quiet_fail=True
        )
        if not text:
            LOGGER.warning(
                "Newznab indexer %s did not respond", self._title
            )
            return None

        try:
            return parse_newznab_response(text)

        except NewznabError as e:
            if e.code in LIMIT_ERROR_CODES:
                self.rate_limited = True
            LOGGER.warning(
                "Newznab indexer %s returned error %d: %s",
                self._title, e.code, e.description
            )
            return None

    def _to_search_result(self, item: NewznabItem) -> SearchResultData:
        return {
            **extract_filename_data(
                item.title,
                assume_volume_number=False,
                fix_year=True
            ),
            "link": item.link,
            "display_title": item.title,
            "size": item.size,
            "indexer_id": self._id,
            "indexer_title": self._title
        }

    async def search(self, query: SearchQuery) -> QueryResult:
        page = await self._fetch_page({
            "t": "search",
            "q": query["query"],
            "offset": (query["page"] - 1) * PAGE_SIZE
        })
        if page is None:
            return QueryResult([], next_page_available=False)

        return QueryResult(
            [self._to_search_result(item) for item in page.items],
            next_page_available=page.offset + len(page.items) < page.total
        )

    async def discover(self, last_check: datetime) -> List[SearchResultData]:
        results: List[SearchResultData] = []
        for page_index in range(DISCOVER_MAX_PAGES):
            page = await self._fetch_page({
                "t": "search",
                "offset": page_index * PAGE_SIZE
            })
            if page is None or not page.items:
                break

            reached_old_items = False
            for item in page.items:
                if item.pub_date is not None and item.pub_date <= last_check:
                    reached_old_items = True
                    continue
                results.append(self._to_search_result(item))

            if (
                reached_old_items
                or page.offset + len(page.items) >= page.total
            ):
                break

        return results

    async def shutdown(self) -> None:
        if self.session:
            await self.session.close()
        return

    @classmethod
    async def __test(cls, url: str, api_key: str, categories: str) -> None:
        async with AsyncSession() as session:
            try:
                text = await session.get_text(
                    newznab_api_url(url),
                    params={
                        "t": "search",
                        "cat": categories,
                        "limit": 1,
                        "apikey": api_key
                    }
                )

            except ClientError:
                raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)

        try:
            parse_newznab_response(text)

        except NewznabError as e:
            if e.code in AUTH_ERROR_CODES:
                raise CredentialInvalid
            if e.code == -1:
                raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)
            raise ClientNotWorking(
                BrokenClientReason.FAILED_PROCESSING_RESPONSE
            )

        return

    @classmethod
    def test(cls, url: str, **extra_fields: Any) -> None:
        api_key = extra_fields.get(ICF.API_KEY.value)
        if not api_key:
            raise CredentialInvalid

        run(cls.__test(
            url,
            api_key,
            extra_fields.get(ICF.CATEGORIES.value) or ""
        ))
        return
