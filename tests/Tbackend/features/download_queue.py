import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.base.definitions import DownloadClientIdentifier, SeedingHandling
from backend.features.download_queue import (DownloadHandler,
                                             get_external_post_processor,
                                             import_completed_download)
from backend.features.post_processing import (PostProcessorTorrentsComplete,
                                              PostProcessorTorrentsCopy,
                                              PostProcessorUsenet)


def fake_download(identifier):
    return SimpleNamespace(identifier=identifier, files=["/downloads/x"])


class external_post_processor(unittest.TestCase):
    def test_usenet_always_imports_on_completion(self):
        for seeding_handling in SeedingHandling:
            with self.subTest(seeding_handling=seeding_handling):
                self.assertIsInstance(
                    get_external_post_processor(
                        fake_download(DownloadClientIdentifier.USENET),
                        seeding_handling
                    ),
                    PostProcessorUsenet
                )

    def test_torrent_follows_seeding_handling(self):
        torrent = fake_download(DownloadClientIdentifier.TORRENT)
        self.assertIsInstance(
            get_external_post_processor(torrent, SeedingHandling.COPY),
            PostProcessorTorrentsCopy
        )
        processor = get_external_post_processor(
            torrent, SeedingHandling.COMPLETE
        )
        self.assertIsInstance(processor, PostProcessorTorrentsComplete)
        self.assertNotIsInstance(processor, PostProcessorUsenet)


class download_handler_logging(unittest.TestCase):
    def test_add_log_is_redacted(self):
        handler = MagicMock()
        handler.link_in_queue.return_value = True
        link = "https://idx/getnzb/a.nzb?apikey=SECRET"
        with patch("backend.features.download_queue.LOGGER") as logger:
            DownloadHandler.add(handler, link, 1, 2)

        message = " ".join(map(str, logger.info.call_args_list[0].args))
        self.assertNotIn("SECRET", message)
        self.assertIn("apikey=<redacted>", message)


class completed_download_import(unittest.TestCase):
    def test_successful_import(self):
        pp = MagicMock()
        self.assertTrue(import_completed_download(pp))
        pp.success.assert_called_once()
        pp.ctx.remove_from_queue.assert_not_called()

    def test_crash_during_import_is_contained(self):
        pp = MagicMock()
        pp.success.side_effect = NotADirectoryError(20, "Not a directory")

        with patch("backend.features.download_queue.LOGGER") as logger:
            self.assertFalse(import_completed_download(pp))

        logger.exception.assert_called_once()
        pp.ctx.remove_from_queue.assert_called_once()
        # Files may already be in the library, so nothing may be deleted
        pp.ctx.delete_file.assert_not_called()
        pp.failed.assert_not_called()
        pp.perm_failed.assert_not_called()
