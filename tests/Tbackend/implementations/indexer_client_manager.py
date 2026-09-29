import unittest
from unittest.mock import patch

from Tbackend.db_helper import TempDatabase

from backend.base.custom_exceptions import InvalidKeyValue
from backend.base.definitions import DownloadType, IndexerClientField as ICF
from backend.implementations.indexer_client_manager import (
    IndexerClients, _validate_indexer_data)
from backend.internals.db import get_db
from backend.internals.db_migration import DatabaseMigrationHandler

MODULE = "backend.implementations.indexer_client_manager"


class validate_usenet_fields(unittest.TestCase):
    def test_categories_string_is_normalised(self):
        result = _validate_indexer_data(
            {"categories": " 7030, 7000 "}, (ICF.CATEGORIES,)
        )
        self.assertEqual(result, {"categories": "7030,7000"})

    def test_categories_list_is_accepted(self):
        result = _validate_indexer_data(
            {"categories": ["7030", 7000]}, (ICF.CATEGORIES,)
        )
        self.assertEqual(result, {"categories": "7030,7000"})

    def test_categories_rejects_bad_values(self):
        for value in ("comics", "", "7030,abc", None, 7030):
            with self.subTest(value=value):
                with self.assertRaises(InvalidKeyValue):
                    _validate_indexer_data(
                        {"categories": value}, (ICF.CATEGORIES,)
                    )

    def test_api_key_is_stripped_and_required(self):
        self.assertEqual(
            _validate_indexer_data({"api_key": " abc "}, (ICF.API_KEY,)),
            {"api_key": "abc"}
        )
        for value in ("", "   ", None, 123):
            with self.subTest(value=value):
                with self.assertRaises(InvalidKeyValue):
                    _validate_indexer_data({"api_key": value}, (ICF.API_KEY,))


class usenet_enums(unittest.TestCase):
    def test_usenet_download_type(self):
        self.assertEqual(DownloadType.USENET.value, 3)


class indexer_usenet_columns(unittest.TestCase):
    def test_migration_adds_columns(self):
        with TempDatabase():
            cursor = get_db()
            cursor.execute("DROP TABLE indexer_clients;")
            cursor.execute("""
                CREATE TABLE indexer_clients(
                    id INTEGER PRIMARY KEY,
                    enabled BOOL NOT NULL DEFAULT 1,
                    download_type INTEGER NOT NULL,
                    client_type VARCHAR(255) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    url TEXT NOT NULL,
                    gc_service_preference TEXT,
                    gc_avoid_large_downloads BOOL
                );
            """)
            DatabaseMigrationHandler.handlers[51]()
            columns = {
                row[1]
                for row in cursor.execute(
                    "PRAGMA table_info(indexer_clients);"
                ).fetchall()
            }
            self.assertIn("api_key", columns)
            self.assertIn("categories", columns)

    def test_getcomics_round_trip_with_new_columns(self):
        IndexerClients.trigger_client_registration()
        with TempDatabase():
            client = IndexerClients.get_client(1)
            data = client.get_indexer_data()
            self.assertIsNone(data["api_key"])
            self.assertIsNone(data["categories"])

            with patch.object(type(client), "test"):
                client.update_indexer({
                    "title": "GetComics Renamed",
                    "enabled": True,
                    "url": "https://getcomics.org",
                    "gc_service_preference": data["gc_service_preference"],
                    "gc_avoid_large_downloads": False
                })

            self.assertEqual(
                IndexerClients.get_client(1).get_indexer_data()["title"],
                "GetComics Renamed"
            )


class indexer_logging(unittest.TestCase):
    def assertKeyNotLogged(self, logger):
        self.assertTrue(logger.info.called)
        for call in logger.info.call_args_list:
            self.assertNotIn("SECRETKEY", " ".join(map(str, call.args)))

    def test_add_and_update_do_not_log_api_key(self):
        IndexerClients.trigger_client_registration()
        ClientClass = IndexerClients.clients[DownloadType.USENET]["Newznab"]
        with TempDatabase(), \
                patch.object(ClientClass, "test"), \
                patch(f"{MODULE}.LOGGER") as logger:
            client = IndexerClients.add(
                DownloadType.USENET, "Newznab", True, "NZBIdx",
                "https://idx", api_key="SECRETKEY", categories="7030"
            )
            self.assertKeyNotLogged(logger)

            logger.reset_mock()
            client.update_indexer({
                "title": "NZBIdx", "enabled": True, "url": "https://idx",
                "api_key": "SECRETKEY", "categories": "7030"
            })
            self.assertKeyNotLogged(logger)
