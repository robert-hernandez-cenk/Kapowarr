# -*- coding: utf-8 -*-

from os.path import basename, exists, join
from threading import Event
from typing import Any, Dict, Protocol, Tuple, Union, runtime_checkable

from backend.base.custom_exceptions import (ClientNotWorking,
                                            CredentialInvalid,
                                            DownloadLinkBroken,
                                            EnqueuingDownloadFailure,
                                            ExternalClientNotFound,
                                            IssueNotFound)
from backend.base.definitions import (BrokenClientReason,
                                      DownloadClientIdentifier,
                                      DownloadService, DownloadState,
                                      DownloadType,
                                      EnqueuingDownloadFailureReason,
                                      ExternalDownload, ExternalDownloadClient)
from backend.base.logging import LOGGER
from backend.implementations.download_client_manager import DownloadClients
from backend.implementations.download_clients.base import BaseDirectDownload
from backend.implementations.external_client_manager import ExternalClients
from backend.implementations.naming import (clean_filestring,
                                            generate_issue_name)
from backend.implementations.remote_mapping import RemoteMappings
from backend.implementations.usenet import pop_cached_nzb
from backend.implementations.volumes import Volume
from backend.internals.settings import Settings


@runtime_checkable
class FindsDownloadsByName(Protocol):
    """
    An external client that can find a download by name. Used to pick up a job
    again after a restart, instead of adding it a second time.
    """

    def find_download(self, name: str) -> Union[str, None]:
        ...


@DownloadClients.register_client(DownloadClientIdentifier.USENET)
class UsenetDownload(ExternalDownload, BaseDirectDownload):
    @property
    def external_client(self) -> ExternalDownloadClient:
        return self._external_client

    @external_client.setter
    def external_client(self, value: ExternalDownloadClient) -> None:
        self._external_client = value
        return

    @property
    def external_id(self) -> Union[str, None]:
        return self._external_id

    @property
    def sleep_event(self) -> Event:
        return self._sleep_event

    def __init__(
        self,
        download_link: str,

        volume_id: int,
        covered_issues: Union[float, Tuple[float, float], None],

        download_service: DownloadService,
        source_name: str,

        web_link: Union[str, None],
        web_title: Union[str, None],
        web_sub_title: Union[str, None],

        forced_match: bool = False,
        external_client: Union[ExternalDownloadClient, None] = None
    ) -> None:
        # The link contains the API key of the indexer, so don't log it
        LOGGER.debug('Creating Usenet download: %s', web_title)

        settings = Settings().sv
        volume = Volume(volume_id)

        self._download_link = self._pure_link = download_link
        self._volume_id = volume_id
        self._issue_id = None
        self._covered_issues = covered_issues
        self._download_service = download_service
        self._source_name = source_name
        self._web_link = web_link
        self._web_title = web_title
        self._web_sub_title = web_sub_title

        self._id = None
        self._state = DownloadState.QUEUED_STATE
        self._progress = 0.0
        self._speed = 0.0
        self._size = -1
        self._download_thread = None
        self._download_folder = settings.download_folder
        self._sleep_event = Event()
        self._missing_path_logged = False

        self._external_id: Union[str, None] = None
        # A download restored from the database is given its client
        self._restored = external_client is not None
        if external_client:
            self._external_client = external_client
        else:
            try:
                self._external_client = ExternalClients.get_least_used_client(
                    DownloadType.USENET
                )
            except ExternalClientNotFound:
                raise EnqueuingDownloadFailure(
                    EnqueuingDownloadFailureReason.NO_USENET_CLIENT
                )

        try:
            if isinstance(covered_issues, float):
                self._issue_id = volume.get_issue_from_number(covered_issues).id

        except IssueNotFound as e:
            if not forced_match:
                raise e

        release_name = clean_filestring(web_title or '') or 'Unknown release'

        self._filename_body = ''
        if settings.rename_downloaded_files:
            try:
                self._filename_body = generate_issue_name(
                    volume.get_data(),
                    covered_issues
                )

            except IssueNotFound as e:
                if not forced_match:
                    raise e

        if not self._filename_body:
            self._filename_body = release_name

        # Also the name of the job in the download client
        self._title = basename(self._filename_body)

        # Placeholder until the client reports where the files are
        self._files = [join(self._download_folder, release_name)]
        return

    def run(self) -> None:
        self._add_to_client()
        return

    def _add_to_client(self) -> None:
        """Add the download to the external client, or pick up the job that
        is already there if the download was restored from the database.
        If the client is unreachable or the credentials are wrong,
        `external_id` stays `None` and the state stays QUEUED, so that a
        later status check tries again. Any other rejection by the client
        (e.g. a duplicate or a bad NZB) fails the download instead, so it
        isn't retried and re-grabbed from the indexer forever.
        """
        try:
            if (
                self._restored
                and isinstance(self.external_client, FindsDownloadsByName)
            ):
                existing_id = self.external_client.find_download(self.title)
                if existing_id:
                    LOGGER.info(
                        "Download already in client, reusing job: %s",
                        self.title
                    )
                    self._external_id = existing_id
                    pop_cached_nzb(self.download_link)
                    return

            self._external_id = self.external_client.add_download(
                self.download_link,
                RemoteMappings.local_to_remote(
                    self._external_client.id,
                    self._download_folder
                ),
                self.title
            )

        except DownloadLinkBroken:
            self._state = DownloadState.FAILED_STATE

        except CredentialInvalid:
            LOGGER.warning(
                "Can't add Usenet download to the client, will try again: %s",
                self.title
            )

        except ClientNotWorking as e:
            if e.reason == BrokenClientReason.CONNECTION_ERROR:
                LOGGER.warning(
                    "Can't add Usenet download to the client, "
                    "will try again: %s",
                    self.title
                )
            else:
                LOGGER.warning(
                    "Usenet download was rejected by the client, "
                    "won't try again: %s",
                    self.title
                )
                self._state = DownloadState.FAILED_STATE

        return

    def update_status(self) -> None:
        if not self.external_id:
            if self.state == DownloadState.QUEUED_STATE:
                self._add_to_client()
            return

        try:
            status = self.external_client.get_download(self.external_id)

        except (ClientNotWorking, CredentialInvalid):
            LOGGER.warning(
                "Can't get the status of Usenet download from the client: %s",
                self.title
            )
            return

        if status is None:
            self._state = DownloadState.CANCELED_STATE
            return

        self._progress = status['progress']
        self._speed = status['speed']
        if status['size'] > 0:
            self._size = status['size']

        if self.state in (
            DownloadState.CANCELED_STATE,
            DownloadState.SHUTDOWN_STATE
        ):
            return

        new_state: DownloadState = status['state']
        if new_state == DownloadState.IMPORTING_STATE:
            new_state = self._resolve_completed_files(status.get('storage'))

        elif (
            new_state == DownloadState.FAILED_STATE
            and self.state != DownloadState.FAILED_STATE
        ):
            LOGGER.warning(
                "Usenet download failed in client: %s",
                status.get("fail_message") or "unknown reason"
            )

        self._state = new_state
        return

    def _resolve_completed_files(
        self,
        storage: Union[str, None]
    ) -> DownloadState:
        """Find the files of a completed download locally.

        Args:
            storage (Union[str, None]): Where the client says the files are.

        Returns:
            DownloadState: `IMPORTING_STATE` if the files were found,
                otherwise `DOWNLOADING_STATE` so that it's checked again later.
        """
        if not storage:
            return DownloadState.DOWNLOADING_STATE

        local_path = RemoteMappings.remote_to_local(
            self.external_client.id,
            storage
        )
        if not exists(local_path):
            if not self._missing_path_logged:
                LOGGER.error(
                    "Download is complete in the Usenet client at '%s', "
                    "which Kapowarr translates to '%s', but that path does not "
                    "exist. Check the Remote Path Mappings setting.",
                    storage, local_path
                )
                self._missing_path_logged = True
            return DownloadState.DOWNLOADING_STATE

        self._files = [local_path]
        return DownloadState.IMPORTING_STATE

    def remove_from_client(self, delete_files: bool) -> None:
        if not self.external_id:
            return

        try:
            self.external_client.delete_download(
                self.external_id, delete_files
            )

        except (ClientNotWorking, CredentialInvalid):
            LOGGER.warning(
                "Can't remove Usenet download from the client: %s",
                self.title
            )

        return

    def stop(
        self,
        state: DownloadState = DownloadState.CANCELED_STATE
    ) -> None:
        self._state = state
        self._sleep_event.set()
        return

    def as_dict(self) -> Dict[str, Any]:
        return {
            **super().as_dict(),
            'client': self.external_client.id if self._external_client else None
        }
