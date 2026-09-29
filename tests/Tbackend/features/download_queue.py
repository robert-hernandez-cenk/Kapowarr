import unittest
from types import SimpleNamespace

from backend.base.definitions import DownloadClientIdentifier, SeedingHandling
from backend.features.download_queue import get_external_post_processor
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
