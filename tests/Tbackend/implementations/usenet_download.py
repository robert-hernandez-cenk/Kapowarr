import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import (ClientNotWorking,
                                            CredentialInvalid,
                                            DownloadLinkBroken,
                                            EnqueuingDownloadFailure,
                                            ExternalClientNotFound)
from backend.base.definitions import (BlocklistReason, BrokenClientReason,
                                      DownloadClientIdentifier,
                                      DownloadService, DownloadState,
                                      DownloadType,
                                      EnqueuingDownloadFailureReason)
from backend.implementations.download_clients.Usenet import UsenetDownload
from backend.implementations.download_preppers.usenet.Newznab import \
    NewznabPrepper
from backend.implementations.external_clients.usenet.SABnzbd import SABnzbd
from backend.implementations.usenet import NzbFile

DOWNLOAD_MODULE = "backend.implementations.download_clients.Usenet"
PREPPER_MODULE = "backend.implementations.download_preppers.usenet.Newznab"
LINK = "https://idx/getnzb/a.nzb"


def make_download(client):
    download = UsenetDownload.__new__(UsenetDownload)
    download._external_client = client
    download._external_id = "nzo_1"
    download._state = DownloadState.DOWNLOADING_STATE
    download._progress = 0.0
    download._speed = 0.0
    download._size = -1
    download._files = ["/downloads/Batman"]
    download._download_link = LINK
    download._download_folder = "/downloads"
    download._title = "Batman"
    download._sleep_event = Event()
    download._missing_path_logged = False
    download._restored = False
    return download


def status(state, storage=None, fail_message=None):
    return {
        "size": 10, "progress": 100.0, "speed": 0.0,
        "state": state, "storage": storage, "fail_message": fail_message
    }


def outages():
    return (
        ClientNotWorking(BrokenClientReason.CONNECTION_ERROR),
        CredentialInvalid()
    )


class usenet_download_outages(unittest.TestCase):
    def assertWarnedWithoutLink(self, logger):
        self.assertTrue(logger.warning.called)
        for call in logger.warning.call_args_list:
            self.assertNotIn(LINK, " ".join(map(str, call.args)))

    def test_status_check_survives_outage(self):
        for error in outages():
            with self.subTest(error=type(error).__name__):
                client = MagicMock()
                client.get_download.side_effect = error
                download = make_download(client)

                with patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
                    download.update_status()

                self.assertEqual(
                    download.state, DownloadState.DOWNLOADING_STATE
                )
                self.assertEqual(download.external_id, "nzo_1")
                self.assertWarnedWithoutLink(logger)

    def test_add_survives_outage(self):
        for error in outages():
            with self.subTest(error=type(error).__name__):
                client = MagicMock()
                client.id = 3
                client.add_download.side_effect = error
                download = make_download(client)
                download._external_id = None
                download._state = DownloadState.QUEUED_STATE

                with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"), \
                        patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
                    download.run()

                self.assertIsNone(download.external_id)
                self.assertEqual(download.state, DownloadState.QUEUED_STATE)
                self.assertWarnedWithoutLink(logger)

    def test_status_check_retries_add(self):
        client = MagicMock()
        client.id = 3
        client.add_download.side_effect = [
            ClientNotWorking(BrokenClientReason.CONNECTION_ERROR), "nzo_9"
        ]
        download = make_download(client)
        download._external_id = None
        download._state = DownloadState.QUEUED_STATE

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"), \
                patch(f"{DOWNLOAD_MODULE}.LOGGER"):
            download.run()
            download.update_status()

        self.assertEqual(client.add_download.call_count, 2)
        self.assertEqual(download.external_id, "nzo_9")

    def test_rejected_download_is_failed_and_not_retried(self):
        client = MagicMock()
        client.id = 3
        client.add_download.side_effect = ClientNotWorking(
            BrokenClientReason.FAILED_PROCESSING_RESPONSE
        )
        download = make_download(client)
        download._external_id = None
        download._state = DownloadState.QUEUED_STATE

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"), \
                patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
            download.run()

        self.assertIsNone(download.external_id)
        self.assertEqual(download.state, DownloadState.FAILED_STATE)
        self.assertWarnedWithoutLink(logger)
        client.add_download.assert_called_once()

    def test_connection_error_retries_without_regrabbing(self):
        client = MagicMock()
        client.id = 3
        client.add_download.side_effect = [
            ClientNotWorking(BrokenClientReason.CONNECTION_ERROR), "nzo_9"
        ]
        download = make_download(client)
        download._external_id = None
        download._state = DownloadState.QUEUED_STATE

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"), \
                patch(f"{DOWNLOAD_MODULE}.LOGGER"):
            download.run()

        self.assertIsNone(download.external_id)
        self.assertEqual(download.state, DownloadState.QUEUED_STATE)

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"), \
                patch(f"{DOWNLOAD_MODULE}.LOGGER"):
            download.update_status()

        self.assertEqual(client.add_download.call_count, 2)
        self.assertEqual(download.external_id, "nzo_9")

    def test_failed_download_is_not_retried(self):
        client = MagicMock()
        download = make_download(client)
        download._external_id = None
        download._state = DownloadState.FAILED_STATE

        download.update_status()

        client.add_download.assert_not_called()
        self.assertEqual(download.state, DownloadState.FAILED_STATE)

    def test_remove_survives_outage(self):
        for error in outages():
            with self.subTest(error=type(error).__name__):
                client = MagicMock()
                client.delete_download.side_effect = error
                download = make_download(client)

                with patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
                    download.remove_from_client(delete_files=True)

                self.assertWarnedWithoutLink(logger)

    def test_fail_message_is_logged_once(self):
        client = MagicMock()
        client.get_download.return_value = status(
            DownloadState.FAILED_STATE, fail_message="Out of retention"
        )
        download = make_download(client)

        with patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
            download.update_status()
            download.update_status()

        self.assertEqual(download.state, DownloadState.FAILED_STATE)
        logger.warning.assert_called_once_with(
            "Usenet download failed in client: %s", "Out of retention"
        )

    def test_missing_fail_message(self):
        client = MagicMock()
        client.get_download.return_value = status(DownloadState.FAILED_STATE)
        download = make_download(client)

        with patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
            download.update_status()

        logger.warning.assert_called_once_with(
            "Usenet download failed in client: %s", "unknown reason"
        )


class usenet_download(unittest.TestCase):
    def test_completed_download_uses_mapped_storage(self):
        client = MagicMock()
        client.id = 3
        client.get_download.return_value = status(
            DownloadState.IMPORTING_STATE, "/sab/complete/Batman"
        )
        download = make_download(client)

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings") as mappings, \
                patch(f"{DOWNLOAD_MODULE}.exists", return_value=True):
            mappings.remote_to_local.return_value = "/local/complete/Batman"
            download.update_status()

        mappings.remote_to_local.assert_called_once_with(
            3, "/sab/complete/Batman"
        )
        self.assertEqual(download.state, DownloadState.IMPORTING_STATE)
        self.assertEqual(download.files, ["/local/complete/Batman"])

    def test_missing_local_path_keeps_waiting_and_logs_once(self):
        client = MagicMock()
        client.id = 3
        client.get_download.return_value = status(
            DownloadState.IMPORTING_STATE, "/sab/complete/Batman"
        )
        download = make_download(client)

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings") as mappings, \
                patch(f"{DOWNLOAD_MODULE}.exists", return_value=False), \
                patch(f"{DOWNLOAD_MODULE}.LOGGER") as logger:
            mappings.remote_to_local.return_value = "/local/complete/Batman"
            download.update_status()
            download.update_status()

        self.assertEqual(download.state, DownloadState.DOWNLOADING_STATE)
        self.assertEqual(download.files, ["/downloads/Batman"])
        self.assertEqual(logger.error.call_count, 1)

    def test_deleted_in_client_is_canceled(self):
        client = MagicMock()
        client.get_download.return_value = None
        download = make_download(client)
        download.update_status()
        self.assertEqual(download.state, DownloadState.CANCELED_STATE)

    def test_run_with_broken_nzb_fails(self):
        client = MagicMock()
        client.id = 3
        client.add_download.side_effect = DownloadLinkBroken(LINK)
        download = make_download(client)
        download._external_id = None

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"):
            download.run()

        self.assertEqual(download.state, DownloadState.FAILED_STATE)
        self.assertIsNone(download.external_id)

    def test_run_sets_external_id(self):
        client = MagicMock()
        client.id = 3
        client.add_download.return_value = "nzo_9"
        download = make_download(client)
        download._external_id = None

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"):
            download.run()

        self.assertEqual(download.external_id, "nzo_9")

    def test_restored_download_reuses_existing_job(self):
        client = MagicMock(spec=SABnzbd)
        client.id = 3
        client.find_download.return_value = "nzo_existing"
        download = make_download(client)
        download._external_id = None
        download._restored = True

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"), \
                patch(f"{DOWNLOAD_MODULE}.pop_cached_nzb") as pop:
            download.run()

        client.find_download.assert_called_once_with("Batman")
        client.add_download.assert_not_called()
        pop.assert_called_once_with(LINK)
        self.assertEqual(download.external_id, "nzo_existing")

    def test_restored_download_without_job_is_added(self):
        client = MagicMock(spec=SABnzbd)
        client.id = 3
        client.find_download.return_value = None
        client.add_download.return_value = "nzo_9"
        download = make_download(client)
        download._external_id = None
        download._restored = True

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"):
            download.run()

        client.add_download.assert_called_once()
        self.assertEqual(download.external_id, "nzo_9")

    def test_new_download_always_adds(self):
        client = MagicMock(spec=SABnzbd)
        client.id = 3
        client.find_download.return_value = "nzo_existing"
        client.add_download.return_value = "nzo_9"
        download = make_download(client)
        download._external_id = None

        with patch(f"{DOWNLOAD_MODULE}.RemoteMappings"):
            download.run()

        client.find_download.assert_not_called()
        client.add_download.assert_called_once()
        self.assertEqual(download.external_id, "nzo_9")

    def test_restored_flag(self):
        kwargs = dict(
            download_link=LINK, volume_id=1, covered_issues=1.0,
            download_service=DownloadService.USENET,
            source_name="NZBIdx", web_link=None,
            web_title="Batman 001", web_sub_title=None
        )
        with patch(f"{DOWNLOAD_MODULE}.Settings"), \
                patch(f"{DOWNLOAD_MODULE}.Volume"), \
                patch(f"{DOWNLOAD_MODULE}.ExternalClients"), \
                patch(f"{DOWNLOAD_MODULE}.clean_filestring",
                      return_value="Batman 001"), \
                patch(f"{DOWNLOAD_MODULE}.generate_issue_name",
                      return_value="Batman 001"):
            self.assertFalse(UsenetDownload(**kwargs)._restored)
            self.assertTrue(
                UsenetDownload(**kwargs, external_client=MagicMock())._restored
            )

    def test_no_usenet_client(self):
        with patch(f"{DOWNLOAD_MODULE}.Settings"), \
                patch(f"{DOWNLOAD_MODULE}.Volume"), \
                patch(f"{DOWNLOAD_MODULE}.ExternalClients") as clients:
            clients.get_least_used_client.side_effect = ExternalClientNotFound(
                -1)
            with self.assertRaises(EnqueuingDownloadFailure) as cm:
                UsenetDownload(
                    download_link=LINK, volume_id=1, covered_issues=1.0,
                    download_service=DownloadService.USENET,
                    source_name="NZBIdx", web_link=None,
                    web_title="Batman 001", web_sub_title=None
                )
        self.assertEqual(
            cm.exception.reason, EnqueuingDownloadFailureReason.NO_USENET_CLIENT
        )


class newznab_prepper(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)

        self.indexers = stack.enter_context(
            patch(f"{PREPPER_MODULE}.IndexerClients")
        )
        self.indexers.get_client.return_value.title = "NZBIdx"
        self.external = stack.enter_context(
            patch(f"{PREPPER_MODULE}.ExternalClients")
        )
        self.fetch = stack.enter_context(patch(
            f"{PREPPER_MODULE}.fetch_nzb",
            return_value=NzbFile(
                "Batman 001 (2016)", "Batman 001 (2016).nzb", b"<nzb/>"
            )
        ))
        self.pop = stack.enter_context(
            patch(f"{PREPPER_MODULE}.pop_cached_nzb")
        )
        self.blocklist = stack.enter_context(
            patch(f"{PREPPER_MODULE}.add_to_blocklist")
        )
        stack.enter_context(patch(f"{PREPPER_MODULE}.Volume"))
        self.filter = stack.enter_context(patch(
            f"{PREPPER_MODULE}.download_group_filter", return_value=True
        ))
        stack.enter_context(patch(
            f"{PREPPER_MODULE}.refine_special_version",
            side_effect=lambda volume_data, info: info
        ))
        self.clients = stack.enter_context(
            patch(f"{PREPPER_MODULE}.DownloadClients")
        )

    def prepper(self, force_match=False):
        return NewznabPrepper(LINK, 7, 12, None, force_match)

    def assertReason(self, cm, reason):
        self.assertEqual(cm.exception.reason, reason)

    def test_no_usenet_client(self):
        self.external.has_enabled_client.return_value = False
        with self.assertRaises(EnqueuingDownloadFailure) as cm:
            self.prepper().get_downloads()
        self.assertReason(cm, EnqueuingDownloadFailureReason.NO_USENET_CLIENT)
        self.external.has_enabled_client.assert_called_once_with(
            DownloadType.USENET
        )
        self.fetch.assert_not_called()

    def test_no_usenet_client_does_not_warn_about_client_id(self):
        # has_enabled_client must be used instead of get_least_used_client,
        # so ExternalClientNotFound (and its "client with given ID not
        # found: -1" warning) is never constructed for this check.
        self.external.has_enabled_client.return_value = False
        self.external.get_least_used_client.assert_not_called()
        with patch("backend.base.custom_exceptions.LOGGER") as ce_logger:
            with self.assertRaises(EnqueuingDownloadFailure):
                self.prepper().get_downloads()

        for call in ce_logger.warning.call_args_list:
            message = " ".join(map(str, call.args))
            self.assertNotIn("External client with given ID not found", message)
        self.external.get_least_used_client.assert_not_called()

    def test_broken_nzb_is_blocklisted(self):
        self.fetch.side_effect = DownloadLinkBroken(LINK)
        with self.assertRaises(EnqueuingDownloadFailure) as cm:
            self.prepper().get_downloads()
        self.assertReason(cm, EnqueuingDownloadFailureReason.LINK_BROKEN)
        kwargs = self.blocklist.call_args.kwargs
        self.assertEqual(kwargs["download_link"], LINK)
        self.assertEqual(kwargs["reason"], BlocklistReason.LINK_BROKEN)
        self.assertEqual(kwargs["volume_id"], 12)

    def test_non_matching_release(self):
        self.filter.return_value = False
        with self.assertRaises(EnqueuingDownloadFailure) as cm:
            self.prepper().get_downloads()
        self.assertReason(cm, EnqueuingDownloadFailureReason.NO_MATCHES)
        self.pop.assert_called_with(LINK)

    def test_force_match_skips_filter(self):
        self.filter.return_value = False
        downloads = self.prepper(force_match=True).get_downloads()
        self.assertEqual(len(downloads), 1)

    def test_success(self):
        prepper = self.prepper()
        downloads = prepper.get_downloads()

        self.clients.get_client.assert_called_once_with(
            DownloadClientIdentifier.USENET
        )
        download_class = self.clients.get_client.return_value
        self.assertEqual(downloads, [download_class.return_value])
        kwargs = download_class.call_args.kwargs
        self.assertEqual(kwargs["download_link"], LINK)
        self.assertEqual(kwargs["volume_id"], 12)
        self.assertEqual(kwargs["covered_issues"], 1.0)
        self.assertEqual(kwargs["download_service"], DownloadService.USENET)
        self.assertEqual(kwargs["source_name"], "NZBIdx")
        self.assertIsNone(kwargs["web_link"])
        self.assertEqual(kwargs["web_title"], "Batman 001 (2016)")
        self.assertEqual(prepper.web_title, "Batman 001 (2016)")
