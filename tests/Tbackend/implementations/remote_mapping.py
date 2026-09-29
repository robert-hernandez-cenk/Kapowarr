import unittest

from Tbackend.db_helper import TempDatabase

from backend.implementations.remote_mapping import RemoteMappings
from backend.internals.db import get_db


class remote_to_local(unittest.TestCase):
    def test_translation_and_passthrough(self):
        with TempDatabase():
            cursor = get_db()
            client_id = cursor.execute("""
                INSERT INTO external_download_clients(
                    download_type, client_type, title, base_url, api_token
                ) VALUES (3, 'SABnzbd', 'SAB', 'http://sab:8080', 'TOKEN');
            """).lastrowid
            cursor.execute("""
                INSERT INTO remote_mappings(
                    external_download_client_id, remote_path, local_path
                ) VALUES (?, '/sab/complete/', '/local/complete/');
                """,
                (client_id,)
            )

            self.assertEqual(
                RemoteMappings.remote_to_local(
                    client_id, "/sab/complete/kapowarr/Batman"
                ),
                "/local/complete/kapowarr/Batman"
            )
            self.assertEqual(
                RemoteMappings.remote_to_local(client_id, "/other/Batman"),
                "/other/Batman"
            )
            self.assertEqual(
                RemoteMappings.remote_to_local(
                    client_id + 1, "/sab/complete/kapowarr/Batman"
                ),
                "/sab/complete/kapowarr/Batman"
            )
