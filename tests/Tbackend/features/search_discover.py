import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.base.custom_exceptions import ExternalClientNotFound
from backend.base.definitions import DownloadType
from backend.features.search_discover import _get_all_new_releases

MODULE = "backend.features.search_discover"
SEARCH_FULL = "backend.features.search_full"


def indexer_of(download_type, link):
    indexer = MagicMock()
    indexer.download_type = download_type
    indexer.get_indexer_data.return_value = {"enabled": True}
    indexer.discover = AsyncMock(return_value=[{"link": link}])
    indexer.shutdown = AsyncMock()
    return indexer


class new_releases(unittest.IsolatedAsyncioTestCase):
    async def releases(self, clients):
        ddl = indexer_of(DownloadType.DDL, "gc")
        usenet_a = indexer_of(DownloadType.USENET, "nzb_a")
        usenet_b = indexer_of(DownloadType.USENET, "nzb_b")
        with patch(f"{MODULE}.IndexerClients") as indexers, \
                patch(f"{SEARCH_FULL}.ExternalClients", clients), \
                patch(f"{MODULE}.Settings") as settings, \
                patch(f"{SEARCH_FULL}.LOGGER"):
            settings.return_value.sv.last_rss_sync = 0
            indexers.get_all_clients.return_value = [ddl, usenet_a, usenet_b]
            results = await _get_all_new_releases()

        return [r["link"] for r in results], usenet_a

    async def test_usenet_skipped_without_usenet_client(self):
        clients = MagicMock()
        clients.get_least_used_client.side_effect = ExternalClientNotFound(-1)
        links, usenet_a = await self.releases(clients)

        self.assertEqual(links, ["gc"])
        usenet_a.discover.assert_not_called()
        clients.get_least_used_client.assert_called_once_with(
            DownloadType.USENET
        )

    async def test_usenet_kept_with_usenet_client(self):
        links, _ = await self.releases(MagicMock())
        self.assertEqual(links, ["gc", "nzb_a", "nzb_b"])
