# -*- coding: utf-8 -*-

from time import time
from typing import Any, Dict, Tuple, Union

from requests.exceptions import RequestException

from backend.base.custom_exceptions import ClientNotWorking, CredentialInvalid
from backend.base.definitions import (BrokenClientReason, Constants,
                                      DownloadState, DownloadType,
                                      ExternalClientField as ECF)
from backend.base.helpers import Session
from backend.base.logging import LOGGER
from backend.implementations.external_client_manager import (
    BaseExternalClient, ExternalClients)
from backend.implementations.usenet import fetch_nzb, pop_cached_nzb

SAB_STATE_MAPPING: Dict[str, DownloadState] = {
    'Queued': DownloadState.QUEUED_STATE,
    'Grabbing': DownloadState.QUEUED_STATE,
    'Fetching': DownloadState.QUEUED_STATE,
    'Propagating': DownloadState.QUEUED_STATE,
    'Downloading': DownloadState.DOWNLOADING_STATE,
    'Paused': DownloadState.PAUSED_STATE,
    'Checking': DownloadState.DOWNLOADING_STATE,
    'QuickCheck': DownloadState.DOWNLOADING_STATE,
    'Verifying': DownloadState.DOWNLOADING_STATE,
    'Repairing': DownloadState.DOWNLOADING_STATE,
    'Extracting': DownloadState.DOWNLOADING_STATE,
    'Moving': DownloadState.DOWNLOADING_STATE,
    'Running': DownloadState.DOWNLOADING_STATE,
    'Completed': DownloadState.IMPORTING_STATE,
    'Failed': DownloadState.FAILED_STATE
}

POST_PROCESSING_STATUSES = (
    'Checking', 'QuickCheck', 'Verifying', 'Repairing',
    'Extracting', 'Moving', 'Running'
)

MISSING_CHECKS_BEFORE_REMOVED = 2
"""
How many status checks in a row a job needs to be missing from SABnzbd before
it's considered deleted. Guards against the moment a job moves from the queue
to the history.
"""


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_sab_jobs(
    queue: Dict[str, Any],
    history: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """Convert the queue and history responses of SABnzbd into statuses.

    Args:
        queue (Dict[str, Any]): Response of `mode=queue`.
        history (Dict[str, Any]): Response of `mode=history`.

    Returns:
        Dict[str, Dict[str, Any]]: nzo_id to status.
    """
    result: Dict[str, Dict[str, Any]] = {}

    queue_data = queue.get("queue") or {}
    speed = _to_float(queue_data.get("kbpersec")) * 1024
    for slot in queue_data.get("slots") or []:
        status = slot.get("status") or ""
        result[slot["nzo_id"]] = {
            "name": slot.get("filename") or "",
            "category": slot.get("cat"),
            "size": round(_to_float(slot.get("mb")) * 1024 * 1024),
            "progress": _to_float(slot.get("percentage")),
            "speed": speed if status == "Downloading" else 0.0,
            "state": SAB_STATE_MAPPING.get(
                status, DownloadState.DOWNLOADING_STATE
            ),
            "storage": None,
            "fail_message": None
        }

    for slot in (history.get("history") or {}).get("slots") or []:
        status = slot.get("status") or ""
        result[slot["nzo_id"]] = {
            "name": slot.get("name") or "",
            "category": slot.get("category"),
            "size": int(_to_float(slot.get("bytes"))),
            "progress": 99.0 if status in POST_PROCESSING_STATUSES else 100.0,
            "speed": 0.0,
            "state": SAB_STATE_MAPPING.get(
                status, DownloadState.DOWNLOADING_STATE
            ),
            "storage": slot.get("storage") or None,
            "fail_message": slot.get("fail_message") or None
        }

    return result


@ExternalClients.register_client(
    DownloadType.USENET, 'SABnzbd',
    (ECF.TITLE, ECF.ENABLED, ECF.BASE_URL, ECF.API_TOKEN)
)
class SABnzbd(BaseExternalClient):
    def __init__(self, client_id: int) -> None:
        super().__init__(client_id)

        self.ssn = Session()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.last_update: float = 0.0
        self.missing_checks: Dict[str, int] = {}
        return

    @staticmethod
    def _api(
        ssn: Session,
        base_url: str,
        api_token: Union[str, None],
        params: Dict[str, Any],
        files: Union[Dict[str, Tuple[str, bytes, str]], None] = None
    ) -> Dict[str, Any]:
        """Make a call to the SABnzbd API.

        Args:
            ssn (Session): The session to use.
            base_url (str): The base URL of the SABnzbd instance.
            api_token (Union[str, None]): The API key.
            params (Dict[str, Any]): The params of the call (e.g. `mode`).
            files (Union[Dict[str, Tuple[str, bytes, str]], None], optional):
                Files to upload. Makes the call a POST.
                Defaults to None.

        Raises:
            ClientNotWorking: Can't connect, or it's not SABnzbd.
            CredentialInvalid: The API key is invalid.

        Returns:
            Dict[str, Any]: The JSON response.
        """
        try:
            response = ssn.request(
                "POST" if files else "GET",
                f"{base_url}/api",
                params={
                    "output": "json",
                    "apikey": api_token or "",
                    **params
                },
                files=files
            )

        except RequestException:
            LOGGER.error("Can't connect to SABnzbd instance at %s", base_url)
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)

        try:
            result = response.json()
        except ValueError:
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        if not isinstance(result, dict):
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        error = result.get("error")
        if error:
            if "api key" in str(error).lower():
                raise CredentialInvalid
            LOGGER.error("SABnzbd returned an error: %s", error)
            raise ClientNotWorking(
                BrokenClientReason.FAILED_PROCESSING_RESPONSE
            )

        return result

    def _refresh(self) -> None:
        """Fetch the queue and the history from SABnzbd. The history is read
        without a category filter, so that a job whose category SABnzbd
        rewrote is never lost.
        """
        queue = self._api(
            self.ssn, self.base_url, self.api_token,
            {"mode": "queue"}
        )
        history = self._api(
            self.ssn, self.base_url, self.api_token,
            {"mode": "history", "limit": 200}
        )
        self.jobs = parse_sab_jobs(queue, history)
        self.last_update = time()
        return

    def find_download(self, name: str) -> Union[str, None]:
        """Find a job in SABnzbd by its name, in the queue or the history.

        Args:
            name (str): The name of the job.

        Returns:
            Union[str, None]: The `nzo_id` of the job, or `None` if there is
                no job with that name.
        """
        self._refresh()
        for nzo_id, job in self.jobs.items():
            if job["name"] == name:
                return nzo_id
        return None

    def add_download(
        self,
        download_link: str,
        target_folder: str,
        download_name: Union[str, None]
    ) -> str:
        # The target folder is decided by the category in SABnzbd.
        # Keep the NZB cached until the upload actually succeeds, so that a
        # retry after a connection error doesn't grab it from the indexer
        # again.
        nzb = fetch_nzb(download_link)

        params: Dict[str, Any] = {
            "mode": "addfile",
            "cat": Constants.EXTERNAL_DOWNLOAD_TAG
        }
        if download_name:
            params["nzbname"] = download_name

        result = self._api(
            self.ssn, self.base_url, self.api_token,
            params,
            files={"name": (nzb.filename, nzb.content, "application/x-nzb")}
        )

        nzo_ids = result.get("nzo_ids") or []
        if not result.get("status") or not nzo_ids:
            LOGGER.error("SABnzbd did not accept the NZB: %s", result)
            raise ClientNotWorking(
                BrokenClientReason.FAILED_PROCESSING_RESPONSE
            )

        pop_cached_nzb(download_link)

        # Make the first status check fetch fresh data
        self.last_update = 0.0
        return nzo_ids[0]

    def get_download(self, download_id: str) -> Union[Dict[str, Any], None]:
        if self.last_update + Constants.EXTERNAL_CLIENT_UPDATE_INTERVAL < time():
            self._refresh()

        job = self.jobs.get(download_id)
        if job is not None:
            self.missing_checks.pop(download_id, None)
            return job

        self.missing_checks[download_id] = (
            self.missing_checks.get(download_id, 0) + 1
        )
        if self.missing_checks[download_id] >= MISSING_CHECKS_BEFORE_REMOVED:
            self.missing_checks.pop(download_id, None)
            return None

        return {
            "name": "",
            "category": None,
            "size": -1,
            "progress": 0.0,
            "speed": 0.0,
            "state": DownloadState.QUEUED_STATE,
            "storage": None,
            "fail_message": None
        }

    def delete_download(self, download_id: str, delete_files: bool) -> None:
        # The job is either in the queue or in the history. Deleting an
        # unknown ID is a no-op in SABnzbd.
        for mode in ("queue", "history"):
            self._api(
                self.ssn, self.base_url, self.api_token,
                {
                    "mode": mode,
                    "name": "delete",
                    "value": download_id,
                    "del_files": int(delete_files)
                }
            )

        self.jobs.pop(download_id, None)
        self.missing_checks.pop(download_id, None)
        return

    def on_shutdown(self) -> None:
        self.ssn.close()
        return

    @classmethod
    def test(
        cls,
        base_url: str,
        username: Union[str, None] = None,
        password: Union[str, None] = None,
        api_token: Union[str, None] = None
    ) -> None:
        with Session() as ssn:
            version = cls._api(ssn, base_url, api_token, {"mode": "version"})
            if "version" not in version:
                raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

            # Version doesn't need the API key, the queue does
            cls._api(ssn, base_url, api_token, {"mode": "queue", "limit": 1})

            categories = cls._api(
                ssn, base_url, api_token, {"mode": "get_cats"}
            ).get("categories") or []
            if Constants.EXTERNAL_DOWNLOAD_TAG not in categories:
                raise ClientNotWorking(BrokenClientReason.MISSING_CATEGORY)

        return
