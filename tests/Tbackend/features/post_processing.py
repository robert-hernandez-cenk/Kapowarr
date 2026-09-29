import unittest
from os import listdir, makedirs
from os.path import exists, isdir, join
from shutil import rmtree
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import patch

from backend.features.post_processing import (PostProcessingContext,
                                              PostProcessorTorrentsComplete,
                                              PostProcessorUsenet,
                                              delete_empty_job_folder)

MODULE = "backend.features.post_processing"


def write_file(path):
    with open(path, "wb") as f:
        f.write(b"comic")
    return path


class move_torrent_to_dest(unittest.TestCase):
    def setUp(self):
        self.root = mkdtemp()
        self.addCleanup(rmtree, self.root, True)
        self.downloads = join(self.root, "downloads")
        self.volume_folder = join(self.root, "library", "Redcoat (2024)")
        makedirs(self.downloads)
        makedirs(self.volume_folder)

        patches = {
            "Volume": patch(f"{MODULE}.Volume"),
            "scan_files": patch(f"{MODULE}.scan_files"),
            "mass_rename": patch(
                f"{MODULE}.mass_rename",
                side_effect=lambda volume_id, filepath_filter, **kw: filepath_filter
            ),
            "Settings": patch(f"{MODULE}.Settings"),
            "commit": patch(f"{MODULE}.commit")
        }
        self.mocks = {}
        for name, p in patches.items():
            self.mocks[name] = p.start()
            self.addCleanup(p.stop)
        self.mocks["Volume"].return_value.vd.folder = self.volume_folder
        self.mocks["Settings"].return_value.sv.rename_downloaded_files = True

    def make_context(self, completed_path):
        download = SimpleNamespace(
            id=1,
            volume_id=14,
            files=[completed_path],
            filename_body="Redcoat (2024) Volume 01 Issue 001"
        )
        return download, PostProcessingContext(download)

    def test_single_file_is_imported_without_extraction(self):
        completed = write_file(join(self.downloads, "Redcoat 001.cbr"))
        download, ctx = self.make_context(completed)

        with patch(f"{MODULE}.extract_files_from_folder") as extract:
            ctx.move_torrent_to_dest()

        expected = join(
            self.volume_folder, "Redcoat (2024) Volume 01 Issue 001.cbr"
        )
        extract.assert_not_called()
        self.assertTrue(exists(expected))
        self.assertEqual(download.files, [expected])
        self.mocks["scan_files"].assert_called_once_with(
            14, filepath_filter=[expected], update_websocket=True
        )
        self.mocks["mass_rename"].assert_called_once()

    def test_folder_is_still_extracted(self):
        job_folder = join(self.downloads, "Redcoat 001")
        makedirs(job_folder)
        write_file(join(job_folder, "Redcoat 001.cbr"))
        download, ctx = self.make_context(job_folder)
        extracted = [join(self.volume_folder, "Redcoat 001.cbr")]

        with patch(
            f"{MODULE}.extract_files_from_folder", return_value=extracted
        ) as extract:
            ctx.move_torrent_to_dest()

        moved_folder = join(
            self.volume_folder, "Redcoat (2024) Volume 01 Issue 001"
        )
        extract.assert_called_once_with(moved_folder, 14)
        self.assertEqual(download.files, extracted)


class empty_job_folder(unittest.TestCase):
    def setUp(self):
        self.root = mkdtemp()
        self.addCleanup(rmtree, self.root, True)
        self.category = join(self.root, "complete", "kapowarr")
        makedirs(self.category)

    def test_empty_folder_named_after_job_is_deleted(self):
        job_folder = join(self.category, "Redcoat Issue 001")
        makedirs(job_folder)
        delete_empty_job_folder(
            join(job_folder, "Redcoat 001.cbr"), "Redcoat Issue 001"
        )
        self.assertFalse(exists(job_folder))
        self.assertTrue(isdir(self.category))

    def test_folder_with_content_is_kept(self):
        job_folder = join(self.category, "Redcoat Issue 001")
        makedirs(job_folder)
        write_file(join(job_folder, "leftover.nfo"))
        delete_empty_job_folder(
            join(job_folder, "Redcoat 001.cbr"), "Redcoat Issue 001"
        )
        self.assertTrue(isdir(job_folder))

    def test_category_folder_is_never_deleted(self):
        # File sat directly in the (now empty) category folder
        delete_empty_job_folder(
            join(self.category, "Redcoat 001.cbr"), "Redcoat Issue 001"
        )
        self.assertTrue(isdir(self.category))
        self.assertEqual(listdir(self.category), [])


class usenet_post_processor(unittest.TestCase):
    def make_download(self, completed_path):
        return SimpleNamespace(
            id=1, files=[completed_path], title="Redcoat Issue 001"
        )

    def test_single_file_job_cleans_up_job_folder(self):
        root = mkdtemp()
        self.addCleanup(rmtree, root, True)
        completed = write_file(join(root, "Redcoat 001.cbr"))
        download = self.make_download(completed)

        with patch.object(PostProcessorTorrentsComplete, "success") as success, \
                patch(f"{MODULE}.delete_empty_job_folder") as cleanup:
            PostProcessorUsenet(download).success()

        success.assert_called_once()
        cleanup.assert_called_once_with(completed, "Redcoat Issue 001")

    def test_folder_job_does_not_trigger_cleanup(self):
        root = mkdtemp()
        self.addCleanup(rmtree, root, True)
        download = self.make_download(root)

        with patch.object(PostProcessorTorrentsComplete, "success"), \
                patch(f"{MODULE}.delete_empty_job_folder") as cleanup:
            PostProcessorUsenet(download).success()

        cleanup.assert_not_called()
