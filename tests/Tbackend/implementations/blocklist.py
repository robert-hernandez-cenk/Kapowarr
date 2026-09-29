import unittest
from unittest.mock import patch

from backend.base.definitions import BlocklistReason, DownloadService
from backend.implementations.blocklist import add_to_blocklist

MODULE = "backend.implementations.blocklist"


class blocklist_logging(unittest.TestCase):
    def test_add_log_is_redacted(self):
        with patch(f"{MODULE}.blocklist_contains", return_value=None), \
                patch(f"{MODULE}.get_db"), \
                patch(f"{MODULE}.get_blocklist_entry"), \
                patch(f"{MODULE}.LOGGER") as logger:
            add_to_blocklist(
                web_link=None, web_title="Batman 001", web_sub_title=None,
                download_link="https://idx/getnzb/a.nzb?apikey=SECRET",
                download_service=DownloadService.USENET,
                volume_id=1, issue_id=None,
                reason=BlocklistReason.LINK_BROKEN
            )

        message = " ".join(map(str, logger.info.call_args.args))
        self.assertNotIn("SECRET", message)
        self.assertIn("apikey=<redacted>", message)
