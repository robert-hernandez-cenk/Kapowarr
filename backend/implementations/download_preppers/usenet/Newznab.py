# -*- coding: utf-8 -*-

from typing import List, Union

from backend.base.custom_exceptions import (DownloadLinkBroken,
                                            EnqueuingDownloadFailure,
                                            IssueNotFound)
from backend.base.definitions import (BlocklistReason, Download,
                                      DownloadClientIdentifier,
                                      DownloadPrepper, DownloadService,
                                      DownloadType,
                                      EnqueuingDownloadFailureReason)
from backend.base.file_extraction import (extract_filename_data,
                                          refine_special_version)
from backend.implementations.blocklist import add_to_blocklist
from backend.implementations.download_client_manager import DownloadClients
from backend.implementations.download_prepper_manager import DownloadPreppers
from backend.implementations.external_client_manager import ExternalClients
from backend.implementations.indexer_client_manager import IndexerClients
from backend.implementations.matching import download_group_filter
from backend.implementations.usenet import fetch_nzb, pop_cached_nzb
from backend.implementations.volumes import Volume


@DownloadPreppers.register_prepper(DownloadType.USENET, "Newznab")
class NewznabPrepper(DownloadPrepper):
    @property
    def web_title(self) -> Union[str, None]:
        return self._web_title

    def __init__(
        self,
        link: str,
        indexer_id: int,
        volume_id: int,
        issue_id: Union[int, None] = None,
        force_match: bool = False
    ) -> None:
        self.link = link
        self.indexer_id = indexer_id
        self.volume_id = volume_id
        self.issue_id = issue_id
        self.force_match = force_match

        self._web_title: Union[str, None] = None
        return

    def get_downloads(self) -> List[Download]:
        indexer = IndexerClients.get_client(self.indexer_id)

        if not ExternalClients.has_enabled_client(DownloadType.USENET):
            raise EnqueuingDownloadFailure(
                EnqueuingDownloadFailureReason.NO_USENET_CLIENT
            )

        try:
            nzb = fetch_nzb(self.link)

        except DownloadLinkBroken:
            add_to_blocklist(
                web_link=None,
                web_title=None,
                web_sub_title=None,
                download_link=self.link,
                download_service=DownloadService.USENET,
                volume_id=self.volume_id,
                issue_id=self.issue_id,
                reason=BlocklistReason.LINK_BROKEN
            )
            raise EnqueuingDownloadFailure(
                EnqueuingDownloadFailureReason.LINK_BROKEN
            )

        self._web_title = nzb.name

        volume = Volume(self.volume_id)
        volume_data = volume.get_data()
        info = extract_filename_data(
            nzb.name,
            assume_volume_number=False,
            fix_year=True
        )

        if not (self.force_match or download_group_filter(
            info,
            volume_data,
            volume.get_ending_year(),
            volume.get_issues()
        )):
            pop_cached_nzb(self.link)
            raise EnqueuingDownloadFailure(
                EnqueuingDownloadFailureReason.NO_MATCHES
            )

        info = refine_special_version(volume_data, info)

        try:
            download = DownloadClients.get_client(
                DownloadClientIdentifier.USENET
            )(
                download_link=self.link,
                volume_id=self.volume_id,
                covered_issues=info["issue_number"],
                download_service=DownloadService.USENET,
                source_name=indexer.title,
                web_link=None,
                web_title=nzb.name,
                web_sub_title=None,
                forced_match=self.force_match
            )

        except IssueNotFound:
            pop_cached_nzb(self.link)
            raise EnqueuingDownloadFailure(
                EnqueuingDownloadFailureReason.NO_MATCHES
            )

        except EnqueuingDownloadFailure:
            pop_cached_nzb(self.link)
            raise

        return [download]
