import unittest
from types import SimpleNamespace

from backend.base.definitions import (DownloadType, QueryKeys, QueryResult,
                                      SearchAction, SpecialVersion)
from backend.features.search_full import SearchCoordinator, protocol_rank


class FakePlanner:
    def __init__(self, action):
        self.action = action

    def next_action(self):
        return (
            self.action,
            QueryKeys(["Batman"], 2016, 1, SpecialVersion.NORMAL, None)
        )


class FakeBuilder:
    def next_query(self, action, query_keys):
        return {"query": "Batman", "page": 1, "total_available_variations": 1}


class FakeIndexer:
    def __init__(self):
        self.searched = False
        self.shut_down = False

    async def search(self, query):
        self.searched = True
        return QueryResult([], next_page_available=False)

    async def shutdown(self):
        self.shut_down = True


def team(indexer, action):
    return {
        "indexer": indexer,
        "query_builder": FakeBuilder(),
        "search_action_planner": FakePlanner(action)
    }


def result(link, download_type, match=True):
    return {
        "link": link,
        "display_title": link,
        "size": 1,
        "indexer_id": 1,
        "indexer_title": "x",
        "download_type": download_type.value,
        "match": match,
        "match_issue": None,
        "series": "Batman",
        "year": 2016,
        "volume_number": 1,
        "special_version": None,
        "issue_number": 1.0,
        "annual": False
    }


class run_iteration(unittest.IsolatedAsyncioTestCase):
    async def test_stopping_two_indexers_keeps_the_right_one(self):
        coordinator = SearchCoordinator.__new__(SearchCoordinator)
        stop_a, stop_b, keep = FakeIndexer(), FakeIndexer(), FakeIndexer()
        coordinator.indexers = [
            team(stop_a, SearchAction.STOP),
            team(stop_b, SearchAction.STOP),
            team(keep, SearchAction.SEARCH_VOLUME)
        ]

        results = await coordinator._run_iteration()

        self.assertEqual(
            [t["indexer"] for t in coordinator.indexers], [keep]
        )
        self.assertTrue(stop_a.shut_down)
        self.assertTrue(stop_b.shut_down)
        self.assertFalse(keep.shut_down)
        self.assertTrue(keep.searched)
        self.assertEqual(len(results), 1)


class sort_results(unittest.TestCase):
    def make(self, results):
        coordinator = SearchCoordinator.__new__(SearchCoordinator)
        coordinator.volume_data = SimpleNamespace(
            title="Batman", volume_number=1, year=2016
        )
        coordinator.found_results = results
        return coordinator

    def test_usenet_wins_ties(self):
        coordinator = self.make([
            result("gc", DownloadType.DDL),
            result("nzb", DownloadType.USENET)
        ])
        coordinator._sort_found_results(2016, 1.0)
        self.assertEqual(
            [r["link"] for r in coordinator.found_results], ["nzb", "gc"]
        )

    def test_better_match_beats_protocol(self):
        coordinator = self.make([
            result("nzb", DownloadType.USENET, match=False),
            result("gc", DownloadType.DDL)
        ])
        coordinator._sort_found_results(2016, 1.0)
        self.assertEqual(
            [r["link"] for r in coordinator.found_results], ["gc", "nzb"]
        )

    def test_protocol_rank_order(self):
        self.assertLess(
            protocol_rank(DownloadType.USENET), protocol_rank(DownloadType.DDL)
        )
        self.assertLess(
            protocol_rank(DownloadType.DDL), protocol_rank(DownloadType.TORRENT)
        )
        self.assertEqual(protocol_rank(3), protocol_rank(DownloadType.USENET))
        self.assertGreater(
            protocol_rank(None), protocol_rank(DownloadType.TORRENT)
        )
