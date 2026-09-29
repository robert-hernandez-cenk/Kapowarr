import unittest

from Tbackend.db_helper import TempDatabase

from backend.base.definitions import DownloadType
from backend.implementations.external_client_manager import ExternalClients
from backend.internals.db import get_db


def insert_client(download_type: DownloadType, enabled: bool) -> None:
    get_db().execute(
        """
        INSERT INTO external_download_clients(
            enabled, download_type, client_type, title, base_url
        ) VALUES (?, ?, 'SABnzbd', 'SAB', 'http://sab:8080');
        """,
        (enabled, download_type.value)
    )
    return


class has_enabled_client(unittest.TestCase):
    def test_true_with_enabled_client(self):
        with TempDatabase():
            insert_client(DownloadType.USENET, True)
            self.assertTrue(
                ExternalClients.has_enabled_client(DownloadType.USENET)
            )

    def test_false_without_any_client(self):
        with TempDatabase():
            self.assertFalse(
                ExternalClients.has_enabled_client(DownloadType.USENET)
            )

    def test_false_with_disabled_client(self):
        with TempDatabase():
            insert_client(DownloadType.USENET, False)
            self.assertFalse(
                ExternalClients.has_enabled_client(DownloadType.USENET)
            )

    def test_false_for_other_download_type(self):
        with TempDatabase():
            insert_client(DownloadType.TORRENT, True)
            self.assertFalse(
                ExternalClients.has_enabled_client(DownloadType.USENET)
            )
