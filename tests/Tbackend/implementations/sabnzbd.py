import unittest
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import ClientNotWorking, CredentialInvalid
from backend.base.definitions import BrokenClientReason, DownloadState
from backend.implementations.external_clients.usenet.SABnzbd import (
    SABnzbd, parse_sab_jobs)
from backend.implementations.usenet import NzbFile

MODULE = "backend.implementations.external_clients.usenet.SABnzbd"

QUEUE_JSON = {"queue": {"kbpersec": "2048.0", "slots": [
    {"nzo_id": "nzo_a", "filename": "Batman Issue 001", "cat": "kapowarr",
     "status": "Downloading", "mb": "50.0", "mbleft": "25.0",
     "percentage": "50"},
    {"nzo_id": "nzo_b", "filename": "Batman Issue 002", "cat": "kapowarr",
     "status": "Queued", "mb": "40.0", "mbleft": "40.0", "percentage": "0"}
]}}
HISTORY_JSON = {"history": {"slots": [
    {"nzo_id": "nzo_c", "name": "Batman Issue 003", "category": "kapowarr",
     "status": "Completed", "bytes": 52428800,
     "storage": "/downloads/complete/kapowarr/Batman Issue 003",
     "fail_message": ""},
    {"nzo_id": "nzo_d", "name": "Batman Issue 004", "category": "kapowarr",
     "status": "Failed", "bytes": 0, "storage": None,
     "fail_message": "Out of retention"},
    {"nzo_id": "nzo_e", "name": "Batman Issue 005", "category": "kapowarr",
     "status": "Extracting", "bytes": 1000, "storage": "",
     "fail_message": ""}
]}}
EMPTY_QUEUE = {"queue": {"kbpersec": "0", "slots": []}}
EMPTY_HISTORY = {"history": {"slots": []}}


def make_client():
    client = SABnzbd.__new__(SABnzbd)
    client._id = 3
    client._title = "SAB"
    client._enabled = True
    client._base_url = "http://sab:8080"
    client._username = None
    client._password = None
    client._api_token = "TOKEN"
    client.ssn = MagicMock()
    client.jobs = {}
    client.last_update = 0.0
    client.missing_checks = {}
    return client


def json_response(data):
    response = MagicMock()
    response.json.return_value = data
    return response


class parse_jobs(unittest.TestCase):
    def test_states_and_fields(self):
        jobs = parse_sab_jobs(QUEUE_JSON, HISTORY_JSON)

        self.assertEqual(
            jobs["nzo_a"]["state"],
            DownloadState.DOWNLOADING_STATE)
        self.assertEqual(jobs["nzo_a"]["progress"], 50.0)
        self.assertEqual(jobs["nzo_a"]["size"], 50 * 1024 * 1024)
        self.assertEqual(jobs["nzo_a"]["speed"], 2048.0 * 1024)
        self.assertEqual(jobs["nzo_a"]["name"], "Batman Issue 001")
        self.assertEqual(jobs["nzo_a"]["category"], "kapowarr")

        self.assertEqual(jobs["nzo_b"]["state"], DownloadState.QUEUED_STATE)
        self.assertEqual(jobs["nzo_b"]["speed"], 0.0)

        self.assertEqual(jobs["nzo_c"]["state"], DownloadState.IMPORTING_STATE)
        self.assertEqual(
            jobs["nzo_c"]["storage"],
            "/downloads/complete/kapowarr/Batman Issue 003"
        )
        self.assertEqual(jobs["nzo_c"]["progress"], 100.0)

        self.assertEqual(jobs["nzo_d"]["state"], DownloadState.FAILED_STATE)
        self.assertEqual(jobs["nzo_d"]["fail_message"], "Out of retention")

        self.assertEqual(
            jobs["nzo_e"]["state"],
            DownloadState.DOWNLOADING_STATE)
        self.assertEqual(jobs["nzo_e"]["progress"], 99.0)
        self.assertIsNone(jobs["nzo_e"]["storage"])


class sabnzbd_client(unittest.TestCase):
    def test_get_download_refreshes(self):
        client = make_client()
        with patch.object(SABnzbd, "_api", side_effect=[QUEUE_JSON, HISTORY_JSON]):
            status = client.get_download("nzo_c")
        self.assertEqual(status["state"], DownloadState.IMPORTING_STATE)

    def test_history_is_read_without_category(self):
        client = make_client()
        api = MagicMock(side_effect=[QUEUE_JSON, HISTORY_JSON])
        with patch.object(SABnzbd, "_api", api):
            client.get_download("nzo_c")

        history_params = api.call_args_list[1].args[3]
        self.assertEqual(history_params["mode"], "history")
        self.assertNotIn("category", history_params)
        self.assertEqual(history_params["limit"], 200)

    def test_missing_job_needs_two_checks(self):
        client = make_client()
        with patch.object(
            SABnzbd, "_api",
            side_effect=[EMPTY_QUEUE, EMPTY_HISTORY, EMPTY_QUEUE, EMPTY_HISTORY]
        ):
            first = client.get_download("nzo_gone")
            client.last_update = 0.0
            second = client.get_download("nzo_gone")

        self.assertEqual(first["state"], DownloadState.QUEUED_STATE)
        self.assertIsNone(second)

    def test_find_download_returns_job_id(self):
        client = make_client()
        with patch.object(
            SABnzbd, "_api", side_effect=[QUEUE_JSON, HISTORY_JSON]
        ):
            self.assertEqual(client.find_download("Batman Issue 003"), "nzo_c")

    def test_find_download_ignores_category(self):
        client = make_client()
        queue = {"queue": {"kbpersec": "0", "slots": [
            {"nzo_id": "nzo_x", "filename": "Batman Issue 009", "cat": "*",
             "status": "Queued", "mb": "1", "percentage": "0"}
        ]}}
        with patch.object(SABnzbd, "_api", side_effect=[queue, EMPTY_HISTORY]):
            self.assertEqual(client.find_download("Batman Issue 009"), "nzo_x")

    def test_find_download_without_match(self):
        client = make_client()
        with patch.object(
            SABnzbd, "_api", side_effect=[QUEUE_JSON, HISTORY_JSON]
        ):
            self.assertIsNone(client.find_download("Superman Issue 001"))

    def test_add_download_uploads_even_with_same_name_job(self):
        client = make_client()
        client.jobs = parse_sab_jobs(QUEUE_JSON, HISTORY_JSON)
        nzb = NzbFile("Batman 001", "Batman 001.nzb", b"<nzb/>")
        api = MagicMock(return_value={"status": True, "nzo_ids": ["nzo_new"]})
        with patch.object(SABnzbd, "_api", api), \
                patch(f"{MODULE}.pop_cached_nzb", return_value=nzb):
            nzo_id = client.add_download(
                "https://idx/a.nzb", "/downloads", "Batman Issue 001"
            )

        self.assertEqual(nzo_id, "nzo_new")
        api.assert_called_once()
        self.assertEqual(api.call_args.args[3]["mode"], "addfile")

    def test_add_download_uploads_cached_nzb(self):
        client = make_client()
        nzb = NzbFile("Batman 001", "Batman 001.nzb", b"<nzb/>")
        api = MagicMock(side_effect=[
            {"status": True, "nzo_ids": ["nzo_new"]}
        ])
        with patch.object(SABnzbd, "_api", api), \
                patch(f"{MODULE}.pop_cached_nzb", return_value=nzb), \
                patch(f"{MODULE}.fetch_nzb") as fetch:
            nzo_id = client.add_download(
                "https://idx/a.nzb", "/downloads", "Batman Issue 001"
            )

        self.assertEqual(nzo_id, "nzo_new")
        fetch.assert_not_called()
        args, kwargs = api.call_args
        params = args[3]
        self.assertEqual(params["mode"], "addfile")
        self.assertEqual(params["cat"], "kapowarr")
        self.assertEqual(params["nzbname"], "Batman Issue 001")
        self.assertEqual(
            kwargs["files"]["name"],
            ("Batman 001.nzb", b"<nzb/>", "application/x-nzb")
        )

    def test_add_download_fails_without_nzo_id(self):
        client = make_client()
        nzb = NzbFile("Batman 001", "Batman 001.nzb", b"<nzb/>")
        with patch.object(
            SABnzbd, "_api",
            side_effect=[{"status": False}]
        ), patch(f"{MODULE}.pop_cached_nzb", return_value=nzb):
            with self.assertRaises(ClientNotWorking):
                client.add_download("https://idx/a.nzb", "/downloads", "X")

    def test_delete_download_calls_queue_and_history(self):
        client = make_client()
        client.jobs = {"nzo_a": {}}
        api = MagicMock(return_value={"status": True})
        with patch.object(SABnzbd, "_api", api):
            client.delete_download("nzo_a", delete_files=False)

        modes = [c.args[3]["mode"] for c in api.call_args_list]
        self.assertEqual(modes, ["queue", "history"])
        for c in api.call_args_list:
            self.assertEqual(c.args[3]["name"], "delete")
            self.assertEqual(c.args[3]["value"], "nzo_a")
            self.assertEqual(c.args[3]["del_files"], 0)
        self.assertNotIn("nzo_a", client.jobs)


class sabnzbd_test(unittest.TestCase):
    def run_test_with(self, *responses):
        with patch(f"{MODULE}.Session") as session_cls:
            ssn = session_cls.return_value.__enter__.return_value
            ssn.request.side_effect = [json_response(r) for r in responses]
            SABnzbd.test("http://sab:8080", None, None, "TOKEN")

    def test_valid(self):
        self.run_test_with(
            {"version": "4.3.2"}, EMPTY_QUEUE,
            {"categories": ["*", "kapowarr"]}
        )

    def test_missing_category(self):
        with self.assertRaises(ClientNotWorking) as cm:
            self.run_test_with(
                {"version": "4.3.2"}, EMPTY_QUEUE,
                {"categories": ["*", "tv"]}
            )
        self.assertEqual(
            cm.exception.reason, BrokenClientReason.MISSING_CATEGORY
        )

    def test_bad_key(self):
        with self.assertRaises(CredentialInvalid):
            self.run_test_with(
                {"version": "4.3.2"},
                {"status": False, "error": "API Key Incorrect"}
            )

    def test_not_sabnzbd(self):
        with self.assertRaises(ClientNotWorking):
            self.run_test_with({"something": "else"})
