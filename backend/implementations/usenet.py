# -*- coding: utf-8 -*-

"""
Fetching and inspecting NZB files
"""

from dataclasses import dataclass
from re import IGNORECASE, compile
from typing import Dict, Mapping, Union
from urllib.parse import unquote
from xml.etree.ElementTree import ParseError, fromstring

from requests.exceptions import RequestException
from requests.structures import CaseInsensitiveDict

from backend.base.custom_exceptions import DownloadLinkBroken
from backend.base.helpers import Session, redact_url_secrets
from backend.base.logging import LOGGER

NZB_NAMESPACE = "http://www.newzbin.com/DTD/2003/nzb"
UNKNOWN_RELEASE_NAME = "Unknown release"
content_disposition_filename_regex = compile(
    r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
    IGNORECASE
)


@dataclass(frozen=True)
class NzbFile:
    name: str
    "The name of the release"

    filename: str
    "The filename to give the NZB file when uploading it"

    content: bytes


_nzb_cache: Dict[str, NzbFile] = {}
"""
NZB link to the fetched file. Filled by the prepper (that needs the release
name) and emptied by the download client (that uploads the file), so that the
NZB is only grabbed from the indexer once.
"""


def is_nzb(content: bytes) -> bool:
    """Check whether some content is an NZB file.

    Args:
        content (bytes): The content to check.

    Returns:
        bool: Whether it is an NZB file.
    """
    try:
        root = fromstring(content)
    except ParseError:
        return False
    return root.tag in (f"{{{NZB_NAMESPACE}}}nzb", "nzb")


def extract_nzb_name(
    headers: Mapping[str, str],
    content: bytes
) -> Union[str, None]:
    """Find the release name of an NZB file. Tries the `X-DNZB-Name` header,
    then the filename in the `Content-Disposition` header, then the name in
    the meta data of the NZB file.

    Args:
        headers (Mapping[str, str]): The headers of the response that
            delivered the NZB file.
        content (bytes): The NZB file.

    Returns:
        Union[str, None]: The name, or `None` if it couldn't be found.
    """
    headers = CaseInsensitiveDict(headers)

    header_name = (headers.get("X-DNZB-Name") or "").strip()
    if header_name:
        return header_name

    match = content_disposition_filename_regex.search(
        headers.get("Content-Disposition") or ""
    )
    if match:
        filename = unquote(match.group(1)).strip()
        if filename.lower().endswith(".nzb"):
            filename = filename[:-4].strip()
        if filename:
            return filename

    try:
        root = fromstring(content)
    except ParseError:
        return None

    for tag in (f"{{{NZB_NAMESPACE}}}meta", "meta"):
        for meta in root.iter(tag):
            if meta.get("type") in (
                "name", "title") and (
                meta.text or "").strip():
                return (meta.text or "").strip()

    return None


def fetch_nzb(link: str) -> NzbFile:
    """Download an NZB file, or get it from the cache if it was already
    downloaded.

    Args:
        link (str): The link to the NZB file.

    Raises:
        DownloadLinkBroken: The link doesn't lead to an NZB file.

    Returns:
        NzbFile: The NZB file.
    """
    if link in _nzb_cache:
        return _nzb_cache[link]

    try:
        with Session() as session:
            response = session.get(link)

    except RequestException:
        raise DownloadLinkBroken(redact_url_secrets(link))

    if not response.ok or not is_nzb(response.content):
        raise DownloadLinkBroken(redact_url_secrets(link))

    name = (
        extract_nzb_name(response.headers, response.content)
        or UNKNOWN_RELEASE_NAME
    )
    LOGGER.debug("Fetched NZB for release: %s", name)

    nzb = NzbFile(name=name, filename=f"{name}.nzb", content=response.content)
    _nzb_cache[link] = nzb
    return nzb


def pop_cached_nzb(link: str) -> Union[NzbFile, None]:
    """Take an NZB file out of the cache.

    Args:
        link (str): The link to the NZB file.

    Returns:
        Union[NzbFile, None]: The NZB file, or `None` if it isn't cached.
    """
    return _nzb_cache.pop(link, None)
