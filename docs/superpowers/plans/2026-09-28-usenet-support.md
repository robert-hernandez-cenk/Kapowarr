# Usenet Support (Newznab + SABnzbd) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kapowarr can search Newznab indexers, send NZBs to SABnzbd, and import the finished downloads. This works for manual search, auto search and RSS sync. When a Usenet result and a GetComics result match equally well, the Usenet result wins.

**Architecture:** A third `DownloadType` (`USENET = 3`) plugs into the existing registries:

- indexer client: `Newznab`
- query builder: reuses the DDL formats
- download prepper: `Newznab`, which fetches the NZB to learn the release name
- download class: `UsenetDownload`
- external client: `SABnzbd`, which uploads the cached NZB and matches existing jobs by name so restarts don't duplicate them

The code that assumed "external download means torrent" is split by type. The search coordinator gains a protocol tiebreak and a fix for its index-shift bug.

**Tech Stack:**

- Python 3.8+
- Flask, with vanilla JS templates for the frontend
- sqlite3
- aiohttp (`AsyncSession`) for indexer searches, requests (`Session`) for clients
- `xml.etree.ElementTree`
- unittest, with `unittest.mock` and `IsolatedAsyncioTestCase`

**Spec:** `docs/superpowers/specs/2026-09-28-usenet-support-design.md`

## Global Constraints

**Python compatibility**

- Code must run on Python 3.8+. Use no `str.removesuffix` or `removeprefix`, no `match`, and no `list[str]`/`dict[...]` generics in annotations. Use `typing.List`, `typing.Dict`, `typing.Union`.
- It must stay compatible with Linux, macOS, Windows and Docker.

**Code style**

- Follow the existing style: 4-space indentation, type hints, docstrings on backend functions, `# -*- coding: utf-8 -*-` header on new backend modules, and `return` at the end of `None` functions like the surrounding code.
- `mypy --explicit-package-bases .` must stay clean. It is clean at the start: "Success: no issues found in 69 source files".
- Run `isort` on files you create or change, and `autopep8` only on those files, e.g. `.venv/Scripts/python -m autopep8 --in-place <files>`. Don't reformat unrelated files.

**Commands** (the venv already exists at `.venv`)

- Tests: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py'`. This must print `OK`. Single module: `.venv/Scripts/python -m unittest discover -s ./tests -p '<file>.py'`.
- Type check: `.venv/Scripts/python -m mypy --explicit-package-bases .`
- The shell is Git Bash on Windows. Use forward slashes.

**Branch and commits**

- Branch: `feature/usenet-support`, already checked out. Commit after every task.
- End every commit message with these two lines:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
  ```

**Fixed values**

- `DownloadType.USENET = 3`
- Newznab default category: `7030`
- SABnzbd category: `Constants.EXTERNAL_DOWNLOAD_TAG` (`"kapowarr"`)
- Newznab page size: `100`
- RSS discover cap: `5` pages
- Newznab auth error codes: `100`, `101`, `102`
- Newznab limit error codes: `429`, `500`, `501`

**Tests**

- No live network calls. Mock every HTTP call.

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `tests/Tbackend/db_helper.py` | `TempDatabase` context manager: a throwaway Kapowarr DB inside a Flask app context |
| `backend/implementations/indexer_clients/usenet/Newznab.py` | Newznab XML parsing and the `NewznabIndexer` client (search, discover, test) |
| `backend/implementations/query_builders/Usenet.py` | `UsenetQueryBuilder`, which reuses the DDL formats |
| `backend/implementations/usenet.py` | NZB fetching, validation, name extraction and the in-memory cache |
| `backend/implementations/external_clients/usenet/SABnzbd.py` | SABnzbd JSON parsing and the `SABnzbd` external client |
| `backend/implementations/download_clients/Usenet.py` | The `UsenetDownload` external download |
| `backend/implementations/download_preppers/usenet/Newznab.py` | `NewznabPrepper`, which turns an NZB link into a `UsenetDownload` |
| `tests/Tbackend/implementations/indexer_client_manager.py` | Indexer field validation, migration, GC round-trip |
| `tests/Tbackend/implementations/newznab.py` | Newznab parsing, indexer and query builder |
| `tests/Tbackend/features/search_full.py` | Iteration bug fix and protocol tiebreak |
| `tests/Tbackend/implementations/usenet.py` | NZB helper |
| `tests/Tbackend/implementations/sabnzbd.py` | SABnzbd parsing and client |
| `tests/Tbackend/implementations/usenet_download.py` | `UsenetDownload` and `NewznabPrepper` |
| `tests/Tbackend/features/download_queue.py` | Post-processor selection |
| `tests/Tbackend/implementations/remote_mapping.py` | `remote_to_local` |

**Modify**

| File | Change |
|---|---|
| `backend/base/definitions.py` | New enum members and TypedDict fields |
| `backend/internals/db.py` | Two columns on `indexer_clients` |
| `backend/internals/db_migration.py` | Migration handler 51 |
| `backend/implementations/indexer_client_manager.py` | Validation plus SELECT/UPDATE/INSERT columns |
| `backend/features/search_full.py` | `protocol_rank`, `_sort_found_results`, iteration fix, `download_type` on results |
| `backend/features/search_discover.py` | RSS protocol ordering |
| `backend/features/post_processing.py` | `PostProcessorUsenet` |
| `backend/features/download_queue.py` | `get_external_post_processor`; Usenet always removed from the client on import |
| `frontend/templates/settings_indexers.html`, `frontend/static/js/settings_indexers.js` | Usenet section, API key and categories fields |
| `frontend/templates/settings_download_clients.html`, `frontend/static/js/settings_download_clients.js` | Usenet Clients section, `download_type` no longer hardcoded |
| `frontend/static/js/view_volume.js` | Hide NZB links, Usenet label, new failure reason text |
| `frontend/templates/settings_download.html` | Help text |

---

### Task 1: Definitions, DB columns, migration and indexer manager

**Files:**
- Create: `tests/Tbackend/db_helper.py`
- Create: `tests/Tbackend/implementations/indexer_client_manager.py`
- Modify: `backend/base/definitions.py` (`DownloadType` ~line 504, `EnqueuingDownloadFailureReason` ~490, `IndexerClientField` ~511, `DownloadService` ~588, `DownloadClientIdentifier` ~601, `IndexerClientData` ~681)
- Modify: `backend/internals/db.py` (`indexer_clients` table, ~line 465)
- Modify: `backend/internals/db_migration.py` (append after handler 50, ~line 1315)
- Modify: `backend/implementations/indexer_client_manager.py` (`_validate_indexer_data`, `BaseIndexerClient.__init__`/`get_indexer_data`/`update_indexer`, `IndexerClients.add` INSERT)

**Interfaces:**
- Produces:
  - Enum members:
    - `DownloadType.USENET` (value `3`)
    - `IndexerClientField.API_KEY` (`"api_key"`), `IndexerClientField.CATEGORIES` (`"categories"`)
    - `DownloadService.USENET` (`"Usenet"`)
    - `DownloadClientIdentifier.USENET` (`"usenet"`)
    - `EnqueuingDownloadFailureReason.NO_USENET_CLIENT` (`"no_usenet_client"`)
  - `IndexerClientData` keys `api_key: Union[str, None]` and `categories: Union[CommaList, None]`.
  - `BaseIndexerClient` attributes `self._api_key: Union[str, None]` and `self._categories: Union[CommaList, None]`.
  - Test helper `Tbackend.db_helper.TempDatabase`.

- [ ] **Step 1: Write the test DB helper**

Create `tests/Tbackend/db_helper.py`:

```python
from shutil import rmtree
from tempfile import mkdtemp

from flask import Flask

from backend.internals.db import (DBConnectionManager, set_db_location,
                                  setup_db)


class TempDatabase:
    """
    Context manager that gives a test a real, throwaway Kapowarr database
    (fully set up and migrated), inside a Flask app context.
    """

    def __enter__(self) -> 'TempDatabase':
        DBConnectionManager.close_connection_of_thread()
        self.folder = mkdtemp()
        set_db_location(self.folder)
        self.app_context = Flask(__name__).app_context()
        self.app_context.push()
        setup_db()
        return self

    def __exit__(self, *args) -> bool:
        DBConnectionManager.close_connection_of_thread()
        self.app_context.pop()
        rmtree(self.folder, ignore_errors=True)
        return False
```

- [ ] **Step 2: Write the failing tests**

Create `tests/Tbackend/implementations/indexer_client_manager.py`:

```python
import unittest
from unittest.mock import patch

from backend.base.custom_exceptions import InvalidKeyValue
from backend.base.definitions import DownloadType
from backend.base.definitions import IndexerClientField as ICF
from backend.implementations.indexer_client_manager import (
    IndexerClients, _validate_indexer_data)
from backend.internals.db import get_db
from backend.internals.db_migration import DatabaseMigrationHandler
from Tbackend.db_helper import TempDatabase


class validate_usenet_fields(unittest.TestCase):
    def test_categories_string_is_normalised(self):
        result = _validate_indexer_data(
            {"categories": " 7030, 7000 "}, (ICF.CATEGORIES,)
        )
        self.assertEqual(result, {"categories": "7030,7000"})

    def test_categories_list_is_accepted(self):
        result = _validate_indexer_data(
            {"categories": ["7030", 7000]}, (ICF.CATEGORIES,)
        )
        self.assertEqual(result, {"categories": "7030,7000"})

    def test_categories_rejects_bad_values(self):
        for value in ("comics", "", "7030,abc", None, 7030):
            with self.subTest(value=value):
                with self.assertRaises(InvalidKeyValue):
                    _validate_indexer_data(
                        {"categories": value}, (ICF.CATEGORIES,)
                    )

    def test_api_key_is_stripped_and_required(self):
        self.assertEqual(
            _validate_indexer_data({"api_key": " abc "}, (ICF.API_KEY,)),
            {"api_key": "abc"}
        )
        for value in ("", "   ", None, 123):
            with self.subTest(value=value):
                with self.assertRaises(InvalidKeyValue):
                    _validate_indexer_data({"api_key": value}, (ICF.API_KEY,))


class usenet_enums(unittest.TestCase):
    def test_usenet_download_type(self):
        self.assertEqual(DownloadType.USENET.value, 3)


class indexer_usenet_columns(unittest.TestCase):
    def test_migration_adds_columns(self):
        with TempDatabase():
            cursor = get_db()
            cursor.execute("DROP TABLE indexer_clients;")
            cursor.execute("""
                CREATE TABLE indexer_clients(
                    id INTEGER PRIMARY KEY,
                    enabled BOOL NOT NULL DEFAULT 1,
                    download_type INTEGER NOT NULL,
                    client_type VARCHAR(255) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    url TEXT NOT NULL,
                    gc_service_preference TEXT,
                    gc_avoid_large_downloads BOOL
                );
            """)
            DatabaseMigrationHandler.handlers[51]()
            columns = {
                row[1]
                for row in cursor.execute(
                    "PRAGMA table_info(indexer_clients);"
                ).fetchall()
            }
            self.assertIn("api_key", columns)
            self.assertIn("categories", columns)

    def test_getcomics_round_trip_with_new_columns(self):
        IndexerClients.trigger_client_registration()
        with TempDatabase():
            client = IndexerClients.get_client(1)
            data = client.get_indexer_data()
            self.assertIsNone(data["api_key"])
            self.assertIsNone(data["categories"])

            with patch.object(type(client), "test"):
                client.update_indexer({
                    "title": "GetComics Renamed",
                    "enabled": True,
                    "url": "https://getcomics.org",
                    "gc_service_preference": data["gc_service_preference"],
                    "gc_avoid_large_downloads": False
                })

            self.assertEqual(
                IndexerClients.get_client(1).get_indexer_data()["title"],
                "GetComics Renamed"
            )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'indexer_client_manager.py'`

Expected: FAIL/ERROR. You should see `AttributeError: API_KEY` (or `CATEGORIES`, or `USENET`) and `KeyError: 51`.

- [ ] **Step 4: Add the enum members and TypedDict fields in `backend/base/definitions.py`**

In `EnqueuingDownloadFailureReason`, add a member after `LINK_RATE_LIMITED = "link_rate_limited"`:

```python
    LINK_RATE_LIMITED = "link_rate_limited"

    # Usenet
    NO_USENET_CLIENT = "no_usenet_client"
```

In `DownloadType`:

```python
class DownloadType(BaseEnum):
    "The download protocol (download type)"

    DDL = 1
    TORRENT = 2
    USENET = 3
```

In `IndexerClientField`, after the `GC_AVOID_LARGE_DOWNLOADS` member and its docstring:

```python
    # Newznab
    API_KEY = "api_key"
    "The API key for the indexer account"

    CATEGORIES = "categories"
    "The (comma separated) category IDs to search in"
```

In `DownloadService`, after `GETCOMICS_TORRENT` and its docstring:

```python
    USENET = "Usenet"
    "An NZB from a Usenet indexer"
```

In `DownloadClientIdentifier`, add `USENET = "usenet"` after `TORRENT = "torrent"`.

In `IndexerClientData`, after `gc_avoid_large_downloads`:

```python
    api_key: Union[str, None]
    categories: Union['CommaList', None]
```

- [ ] **Step 5: Add the columns to the schema in `backend/internals/db.py`**

Replace the `indexer_clients` table definition:

```sql
CREATE TABLE IF NOT EXISTS indexer_clients(
    id INTEGER PRIMARY KEY,
    enabled BOOL NOT NULL DEFAULT 1,
    download_type INTEGER NOT NULL,
    client_type VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,

    gc_service_preference TEXT,
    gc_avoid_large_downloads BOOL,

    api_key TEXT,
    categories TEXT
);
```

- [ ] **Step 6: Add migration handler 51 in `backend/internals/db_migration.py`**

Append at the end of the file:

```python
@DatabaseMigrationHandler.register_handler(51)
def _migrate_add_usenet_indexer_fields() -> None:
    cursor = get_db()
    cursor.execute("ALTER TABLE indexer_clients ADD COLUMN api_key TEXT;")
    cursor.execute("ALTER TABLE indexer_clients ADD COLUMN categories TEXT;")
    return
```

A fresh install already has the columns and starts at the latest version (`Settings` default `database_version = latest_db_version()`), so this handler only runs on existing databases.

- [ ] **Step 7: Validate the new fields in `_validate_indexer_data` (`backend/implementations/indexer_client_manager.py`)**

Replace the `None` check block:

```python
        if (
            key in (
                ICF.TITLE,
                ICF.ENABLED,
                ICF.URL,
                ICF.API_KEY,
                ICF.CATEGORIES
            )
            and value is None
        ):
            raise InvalidKeyValue(key.value, None)
```

Insert these two branches directly before the final generic `elif key in required_tokens:` branch:

```python
        elif key == ICF.API_KEY:
            if not isinstance(value, str) or not value.strip():
                raise InvalidKeyValue(key.value, value)
            filtered_data[key.value] = value.strip()

        elif key == ICF.CATEGORIES:
            if isinstance(value, str):
                entries = value.split(',')
            elif isinstance(value, list):
                entries = value
            else:
                raise InvalidKeyValue(key.value, value)

            categories = CommaList(
                str(entry).strip()
                for entry in entries
                if str(entry).strip()
            )
            if not categories or not all(c.isdigit() for c in categories):
                raise InvalidKeyValue(key.value, value)

            filtered_data[key.value] = str(categories)
```

- [ ] **Step 8: Read, return and update the new columns in `BaseIndexerClient`**

In `__init__`, replace the SELECT and add the new attributes after the GC block, just before `return`:

```python
        data = get_db().execute("""
            SELECT
                enabled,
                title, url,
                gc_service_preference, gc_avoid_large_downloads,
                api_key, categories
            FROM indexer_clients
            WHERE id = ?
            LIMIT 1;
            """,
            (indexer_id,)
        ).fetchone()
```

```python
        self._api_key: Union[str, None] = data["api_key"]
        self._categories: Union[CommaList, None] = (
            CommaList(data["categories"])
            if data["categories"] is not None
            else None
        )

        return
```

In `get_indexer_data`, add two keys after `'gc_avoid_large_downloads'`:

```python
            'gc_avoid_large_downloads': self._gc_avoid_large_downloads,
            'api_key': self._api_key,
            'categories': self._categories
```

In `update_indexer`, replace the `get_db().execute(...)` UPDATE call with:

```python
        get_db().execute("""
            UPDATE indexer_clients
            SET
                enabled = :enabled,
                title = :title,
                url = :url,
                gc_service_preference = :gc_service_preference,
                gc_avoid_large_downloads = :gc_avoid_large_downloads,
                api_key = :api_key,
                categories = :categories
            WHERE id = :id;
            """,
            {
                **{k: None for k in ICF._value2member_map_},
                **filtered_data,
                "id": self._id
            }
        )
```

After the existing GC attribute refresh at the end of `update_indexer`, before `return`, add:

```python
        if ICF.API_KEY in self.required_tokens:
            self._api_key = filtered_data[ICF.API_KEY.value]
        if ICF.CATEGORIES in self.required_tokens:
            self._categories = CommaList(filtered_data[ICF.CATEGORIES.value])
```

- [ ] **Step 9: Insert the new columns in `IndexerClients.add`**

Replace the INSERT statement text. `filtered_data` already contains every `ICF` key.

```python
        indexer_id = cursor.execute(
            """
            INSERT INTO indexer_clients(
                enabled,
                download_type, client_type,
                title, url,
                gc_service_preference, gc_avoid_large_downloads,
                api_key, categories
            ) VALUES (
                :enabled,
                :download_type, :client_type,
                :title, :url,
                :gc_service_preference, :gc_avoid_large_downloads,
                :api_key, :categories
            );
            """,
            filtered_data
        ).lastrowid
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'indexer_client_manager.py'`

Expected: `OK` (6 tests).

- [ ] **Step 11: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK`, then `Success: no issues found`.

- [ ] **Step 12: Commit**

```bash
git add backend/base/definitions.py backend/internals/db.py backend/internals/db_migration.py backend/implementations/indexer_client_manager.py tests/Tbackend/db_helper.py tests/Tbackend/implementations/indexer_client_manager.py
git commit -F - <<'EOF'
Add Usenet download type and API key/categories indexer fields

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 2: Newznab indexer and Usenet query builder

**Files:**
- Create: `backend/implementations/indexer_clients/usenet/Newznab.py`
- Create: `backend/implementations/query_builders/Usenet.py`
- Create: `tests/Tbackend/implementations/newznab.py`

**Interfaces:**
- Consumes: from Task 1, `DownloadType.USENET`, `ICF.API_KEY`, `ICF.CATEGORIES`, `BaseIndexerClient._api_key`, `BaseIndexerClient._categories`
- Produces:
  - `NewznabIndexer`, registered as `(USENET, "Newznab")`, with `allow_multiple_instances=True`
  - `parse_newznab_response(xml_text: str) -> NewznabPage`
  - `NewznabError(code: int, description: str)`
  - `newznab_api_url(url: str) -> str`
  - `UsenetQueryBuilder`, registered for `USENET`

- [ ] **Step 1: Write the failing tests**

Create `tests/Tbackend/implementations/newznab.py`:

```python
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from aiohttp import ClientError

from backend.base.custom_exceptions import ClientNotWorking, CredentialInvalid
from backend.base.definitions import (DownloadType, QueryKeys, SearchAction,
                                      SpecialVersion)
from backend.base.helpers import CommaList
from backend.implementations.indexer_clients.usenet.Newznab import (
    NewznabError, NewznabIndexer, newznab_api_url, parse_newznab_response)
from backend.implementations.query_builder_manager import QueryBuilders
from backend.implementations.query_builders.DDL import DDLQueryBuilder
from backend.implementations.query_builders.Usenet import UsenetQueryBuilder

MODULE = "backend.implementations.indexer_clients.usenet.Newznab"

SEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
<channel>
<title>example</title>
<newznab:response offset="0" total="150"/>
<item>
<title>Batman 001 (2016) (Digital) (Zone-Empire)</title>
<link>https://indexer.example/getnzb/abc.nzb&amp;i=1&amp;r=KEY</link>
<pubDate>Tue, 15 Sep 2026 10:00:00 +0000</pubDate>
<enclosure url="https://indexer.example/getnzb/abc.nzb&amp;i=1&amp;r=KEY" length="0" type="application/x-nzb"/>
<newznab:attr name="category" value="7030"/>
<newznab:attr name="size" value="52428800"/>
</item>
<item>
<title>Batman 002 (2016) (Digital) (Zone-Empire)</title>
<link>https://indexer.example/getnzb/def.nzb</link>
<pubDate>Mon, 01 Jun 2026 10:00:00 +0000</pubDate>
<enclosure url="https://indexer.example/getnzb/def.nzb" length="1000" type="application/x-nzb"/>
</item>
</channel>
</rss>"""

ERROR_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<error code="100" description="Incorrect user credentials"/>'
LIMIT_XML = '<error code="500" description="Request limit reached"/>'


class FakeSession:
    "Stands in for AsyncSession. Responses that are exceptions are raised."

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get_text(self, url, params={}, headers={}, quiet_fail=False):
        self.calls.append((url, dict(params)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            if quiet_fail:
                return ''
            raise response
        return response

    async def close(self):
        return

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_indexer(session):
    indexer = NewznabIndexer.__new__(NewznabIndexer)
    indexer._id = 7
    indexer._title = "NZBIdx"
    indexer._url = "https://indexer.example"
    indexer._enabled = True
    indexer._api_key = "KEY"
    indexer._categories = CommaList("7030")
    indexer.session = session
    indexer.rate_limited = False
    return indexer


def local_naive(dt):
    return dt.astimezone().replace(tzinfo=None)


class parse_newznab(unittest.TestCase):
    def test_items_and_paging(self):
        page = parse_newznab_response(SEARCH_XML)
        self.assertEqual((page.offset, page.total), (0, 150))
        self.assertEqual(len(page.items), 2)

        first = page.items[0]
        self.assertEqual(
            first.title, "Batman 001 (2016) (Digital) (Zone-Empire)"
        )
        self.assertEqual(
            first.link, "https://indexer.example/getnzb/abc.nzb&i=1&r=KEY"
        )
        self.assertEqual(first.size, 52428800)
        self.assertEqual(
            first.pub_date,
            local_naive(datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc))
        )
        self.assertEqual(page.items[1].size, 1000)

    def test_error_response(self):
        with self.assertRaises(NewznabError) as cm:
            parse_newznab_response(ERROR_XML)
        self.assertEqual(cm.exception.code, 100)

    def test_invalid_xml(self):
        with self.assertRaises(NewznabError) as cm:
            parse_newznab_response("<html>nope")
        self.assertEqual(cm.exception.code, -1)

    def test_api_url(self):
        self.assertEqual(
            newznab_api_url("https://x.org"), "https://x.org/api"
        )
        self.assertEqual(
            newznab_api_url("https://x.org/api"), "https://x.org/api"
        )


class newznab_indexer(unittest.IsolatedAsyncioTestCase):
    async def test_search_builds_results(self):
        session = FakeSession([SEARCH_XML])
        result = await make_indexer(session).search(
            {"query": "Batman #1", "page": 1, "total_available_variations": 2}
        )

        self.assertTrue(result.next_page_available)
        self.assertEqual(len(result.results), 2)
        first = result.results[0]
        self.assertEqual(first["series"], "Batman")
        self.assertEqual(first["issue_number"], 1.0)
        self.assertEqual(first["indexer_id"], 7)
        self.assertEqual(first["indexer_title"], "NZBIdx")
        self.assertEqual(first["size"], 52428800)

        url, params = session.calls[0]
        self.assertEqual(url, "https://indexer.example/api")
        self.assertEqual(params["t"], "search")
        self.assertEqual(params["q"], "Batman #1")
        self.assertEqual(params["offset"], 0)
        self.assertEqual(params["cat"], "7030")
        self.assertEqual(params["apikey"], "KEY")

    async def test_second_page_offset(self):
        session = FakeSession([SEARCH_XML])
        await make_indexer(session).search(
            {"query": "Batman", "page": 2, "total_available_variations": 1}
        )
        self.assertEqual(session.calls[0][1]["offset"], 100)

    async def test_rate_limit_stops_indexer(self):
        session = FakeSession([LIMIT_XML])
        indexer = make_indexer(session)
        query = {"query": "Batman", "page": 1, "total_available_variations": 1}

        first = await indexer.search(query)
        second = await indexer.search(query)

        self.assertEqual(first.results, [])
        self.assertFalse(first.next_page_available)
        self.assertEqual(second.results, [])
        self.assertEqual(len(session.calls), 1)

    async def test_no_response(self):
        session = FakeSession([ClientError()])
        result = await make_indexer(session).search(
            {"query": "Batman", "page": 1, "total_available_variations": 1}
        )
        self.assertEqual(result.results, [])
        self.assertFalse(result.next_page_available)

    async def test_discover_stops_at_last_check(self):
        session = FakeSession([SEARCH_XML])
        results = await make_indexer(session).discover(datetime(2026, 8, 1))

        self.assertEqual(
            [r["display_title"] for r in results],
            ["Batman 001 (2016) (Digital) (Zone-Empire)"]
        )
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("q", session.calls[0][1])


class newznab_test(unittest.TestCase):
    def test_valid(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession([SEARCH_XML])):
            NewznabIndexer.test(
                "https://indexer.example", api_key="KEY", categories="7030"
            )

    def test_bad_key(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession([ERROR_XML])):
            with self.assertRaises(CredentialInvalid):
                NewznabIndexer.test(
                    "https://indexer.example", api_key="BAD", categories="7030"
                )

    def test_missing_key(self):
        with self.assertRaises(CredentialInvalid):
            NewznabIndexer.test("https://indexer.example", categories="7030")

    def test_not_newznab(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession(["<html></html>"])):
            with self.assertRaises(ClientNotWorking):
                NewznabIndexer.test(
                    "https://indexer.example", api_key="KEY", categories="7030"
                )

    def test_connection_error(self):
        with patch(f"{MODULE}.AsyncSession", return_value=FakeSession([ClientError()])):
            with self.assertRaises(ClientNotWorking):
                NewznabIndexer.test(
                    "https://indexer.example", api_key="KEY", categories="7030"
                )


class usenet_query_builder(unittest.TestCase):
    def test_registered_and_same_queries_as_ddl(self):
        self.assertIs(
            QueryBuilders.get_builder(DownloadType.USENET), UsenetQueryBuilder
        )
        keys = QueryKeys(["Batman"], 2016, 1, SpecialVersion.NORMAL, None)
        self.assertEqual(
            UsenetQueryBuilder().next_query(SearchAction.SEARCH_VOLUME, keys),
            DDLQueryBuilder().next_query(SearchAction.SEARCH_VOLUME, keys)
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'newznab.py'`

Expected: ERROR, `ModuleNotFoundError: No module named 'backend.implementations.indexer_clients.usenet'`.

- [ ] **Step 3: Implement the Newznab indexer**

Create `backend/implementations/indexer_clients/usenet/Newznab.py`. There is no `__init__.py`, matching the existing `ddl/` folder.

```python
# -*- coding: utf-8 -*-

"""
Indexer client for Newznab compatible Usenet indexers
(NZBGeek, NZB.su, DrunkenSlug, etc.)
"""

from asyncio import run
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Union
from xml.etree.ElementTree import Element, ParseError, fromstring

from aiohttp import ClientError

from backend.base.custom_exceptions import ClientNotWorking, CredentialInvalid
from backend.base.definitions import (BrokenClientReason, DownloadType,
                                      IndexerClientField as ICF, QueryResult,
                                      SearchQuery, SearchResultData)
from backend.base.file_extraction import extract_filename_data
from backend.base.helpers import AsyncSession
from backend.base.logging import LOGGER
from backend.implementations.indexer_client_manager import (BaseIndexerClient,
                                                            IndexerClients)

NEWZNAB_NAMESPACE = "http://www.newznab.com/DTD/2010/feeds/attributes/"
PAGE_SIZE = 100
DISCOVER_MAX_PAGES = 5
AUTH_ERROR_CODES = (100, 101, 102)
LIMIT_ERROR_CODES = (429, 500, 501)


class NewznabError(Exception):
    "The Newznab API returned an error, or a response that couldn't be parsed"

    def __init__(self, code: int, description: str) -> None:
        super().__init__(f"Newznab error {code}: {description}")
        self.code = code
        self.description = description
        return


@dataclass
class NewznabItem:
    title: str
    link: str
    size: int
    pub_date: Union[datetime, None]


@dataclass
class NewznabPage:
    items: List[NewznabItem]
    offset: int
    total: int


def newznab_api_url(url: str) -> str:
    """Get the API endpoint of a Newznab indexer.

    Args:
        url (str): The URL of the indexer, with or without `/api` at the end.

    Returns:
        str: The URL of the API endpoint.
    """
    if url.endswith("/api"):
        return url
    return f"{url}/api"


def _to_int(value: Union[str, None], default: int) -> int:
    try:
        return int(value) # type: ignore
    except (TypeError, ValueError):
        return default


def _parse_pub_date(value: Union[str, None]) -> Union[datetime, None]:
    """Parse an RSS pubDate into a naive datetime in local time, so it can be
    compared with the naive datetimes that the rest of Kapowarr uses.
    """
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError):
        return None

    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone().replace(tzinfo=None)


def _parse_item(item: Element) -> Union[NewznabItem, None]:
    title = (item.findtext("title") or "").strip()
    enclosure = item.find("enclosure")

    link = ""
    if enclosure is not None:
        link = (enclosure.get("url") or "").strip()
    if not link:
        link = (item.findtext("link") or "").strip()

    if not title or not link:
        return None

    size = -1
    for attr in item.findall(f"{{{NEWZNAB_NAMESPACE}}}attr"):
        if attr.get("name") == "size":
            size = _to_int(attr.get("value"), -1)
    if size <= 0 and enclosure is not None:
        size = _to_int(enclosure.get("length"), -1)
    if size <= 0:
        size = -1

    return NewznabItem(
        title=title,
        link=link,
        size=size,
        pub_date=_parse_pub_date(item.findtext("pubDate"))
    )


def parse_newznab_response(xml_text: str) -> NewznabPage:
    """Parse a Newznab search response.

    Args:
        xml_text (str): The body of the response.

    Raises:
        NewznabError: The indexer returned an error, or the response is not
            a Newznab response. Code `-1` when the response couldn't be parsed.

    Returns:
        NewznabPage: The items and paging info.
    """
    try:
        root = fromstring(xml_text)
    except ParseError:
        raise NewznabError(-1, "Response is not valid XML")

    if root.tag == "error":
        raise NewznabError(
            _to_int(root.get("code"), -1),
            root.get("description") or ""
        )

    channel = root.find("channel")
    if channel is None:
        raise NewznabError(-1, "Response has no channel")

    items: List[NewznabItem] = []
    for item_el in channel.findall("item"):
        item = _parse_item(item_el)
        if item is not None:
            items.append(item)

    response = channel.find(f"{{{NEWZNAB_NAMESPACE}}}response")
    offset, total = 0, len(items)
    if response is not None:
        offset = _to_int(response.get("offset"), 0)
        total = _to_int(response.get("total"), offset + len(items))

    return NewznabPage(items=items, offset=offset, total=total)


@IndexerClients.register_client(
    DownloadType.USENET, 'Newznab',
    (ICF.TITLE, ICF.ENABLED, ICF.URL, ICF.API_KEY, ICF.CATEGORIES),
    allow_multiple_instances=True
)
class NewznabIndexer(BaseIndexerClient):
    def __init__(self, indexer_id: int) -> None:
        super().__init__(indexer_id)

        self.session: Union[AsyncSession, None] = None
        self.rate_limited = False
        "Whether the indexer reported that its request limit is reached"

        return

    async def _fetch_page(
        self,
        params: Dict[str, Any]
    ) -> Union[NewznabPage, None]:
        """Make a request to the API of the indexer.

        Args:
            params (Dict[str, Any]): Params added on top of the API key,
                categories and page size.

        Returns:
            Union[NewznabPage, None]: The page, or `None` if the request
                failed (which is logged).
        """
        if self.rate_limited:
            return None

        if not self.session:
            self.session = AsyncSession()

        text = await self.session.get_text(
            newznab_api_url(self._url),
            params={
                "apikey": self._api_key or "",
                "cat": ",".join(self._categories or []),
                "limit": PAGE_SIZE,
                **params
            },
            quiet_fail=True
        )
        if not text:
            LOGGER.warning(
                "Newznab indexer %s did not respond", self._title
            )
            return None

        try:
            return parse_newznab_response(text)

        except NewznabError as e:
            if e.code in LIMIT_ERROR_CODES:
                self.rate_limited = True
            LOGGER.warning(
                "Newznab indexer %s returned error %d: %s",
                self._title, e.code, e.description
            )
            return None

    def _to_search_result(self, item: NewznabItem) -> SearchResultData:
        return {
            **extract_filename_data(
                item.title,
                assume_volume_number=False,
                fix_year=True
            ),
            "link": item.link,
            "display_title": item.title,
            "size": item.size,
            "indexer_id": self._id,
            "indexer_title": self._title
        }

    async def search(self, query: SearchQuery) -> QueryResult:
        page = await self._fetch_page({
            "t": "search",
            "q": query["query"],
            "offset": (query["page"] - 1) * PAGE_SIZE
        })
        if page is None:
            return QueryResult([], next_page_available=False)

        return QueryResult(
            [self._to_search_result(item) for item in page.items],
            next_page_available=page.offset + len(page.items) < page.total
        )

    async def discover(self, last_check: datetime) -> List[SearchResultData]:
        results: List[SearchResultData] = []
        for page_index in range(DISCOVER_MAX_PAGES):
            page = await self._fetch_page({
                "t": "search",
                "offset": page_index * PAGE_SIZE
            })
            if page is None or not page.items:
                break

            reached_old_items = False
            for item in page.items:
                if item.pub_date is not None and item.pub_date <= last_check:
                    reached_old_items = True
                    continue
                results.append(self._to_search_result(item))

            if (
                reached_old_items
                or page.offset + len(page.items) >= page.total
            ):
                break

        return results

    async def shutdown(self) -> None:
        if self.session:
            await self.session.close()
        return

    @classmethod
    async def __test(cls, url: str, api_key: str, categories: str) -> None:
        async with AsyncSession() as session:
            try:
                text = await session.get_text(
                    newznab_api_url(url),
                    params={
                        "t": "search",
                        "cat": categories,
                        "limit": 1,
                        "apikey": api_key
                    }
                )

            except ClientError:
                raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)

        try:
            parse_newznab_response(text)

        except NewznabError as e:
            if e.code in AUTH_ERROR_CODES:
                raise CredentialInvalid
            if e.code == -1:
                raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)
            raise ClientNotWorking(
                BrokenClientReason.FAILED_PROCESSING_RESPONSE
            )

        return

    @classmethod
    def test(cls, url: str, **extra_fields: Any) -> None:
        api_key = extra_fields.get(ICF.API_KEY.value)
        if not api_key:
            raise CredentialInvalid

        run(cls.__test(
            url,
            api_key,
            extra_fields.get(ICF.CATEGORIES.value) or ""
        ))
        return
```

- [ ] **Step 4: Implement the query builder**

Create `backend/implementations/query_builders/Usenet.py`:

```python
# -*- coding: utf-8 -*-

from backend.base.definitions import DownloadType
from backend.implementations.query_builder_manager import QueryBuilders
from backend.implementations.query_builders.DDL import DDLQueryBuilder


@QueryBuilders.register_builder(DownloadType.USENET)
class UsenetQueryBuilder(DDLQueryBuilder):
    """
    Newznab search is keyword based, just like the GetComics search, so the
    same query formats and variations are used.
    """
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'newznab.py'`

Expected: `OK` (15 tests).

- [ ] **Step 6: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK` and `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add backend/implementations/indexer_clients/usenet/Newznab.py backend/implementations/query_builders/Usenet.py tests/Tbackend/implementations/newznab.py
git commit -F - <<'EOF'
Add Newznab indexer client and Usenet query builder

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 3: Search coordinator (iteration fix, protocol tiebreak, RSS ordering)

**Files:**
- Modify: `backend/base/definitions.py` (`MatchedSearchResultData`, ~line 712)
- Modify: `backend/features/search_full.py`
- Modify: `backend/features/search_discover.py`
- Create: `tests/Tbackend/features/search_full.py`

**Interfaces:**
- Consumes: `DownloadType.USENET` (Task 1)
- Produces:
  - `backend.features.search_full.protocol_rank(download_type: Union[DownloadType, int, None]) -> int`
  - `SearchCoordinator._sort_found_results(issue_year, calculated_issue_number) -> None`
  - The optional key `MatchedSearchResultData["download_type"]: int`, used by the frontend in Task 7

- [ ] **Step 1: Write the failing tests**

Create `tests/Tbackend/features/search_full.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'search_full.py'`

Expected: ERROR, `ImportError: cannot import name 'protocol_rank'`.

- [ ] **Step 3: Add `download_type` to `MatchedSearchResultData` in `backend/base/definitions.py`**

```python
class MatchedSearchResultData(
    SearchResultMatchData,
    SearchResultData,
    total=False
):
    _issue_number: Union[float, Tuple[float, float]]
    download_type: int
    "The `DownloadType` value of the indexer that the result came from"
```

- [ ] **Step 4: Implement the changes in `backend/features/search_full.py`**

Extend the `typing` import to include `Tuple` and `Union` (already present), and the definitions import to include `DownloadType`:

```python
from backend.base.definitions import (DownloadType, IndexerClient,
                                      IssueData, MatchedSearchResultData,
                                      QueryBuilder, QueryResult, SearchAction,
                                      SearchIterationStats, SearchQuery,
                                      SearchResultData, SpecialVersion)
```

Add this below the `IndexerTeam` class:

```python
PROTOCOL_PREFERENCE: Tuple[DownloadType, ...] = (
    DownloadType.USENET,
    DownloadType.DDL,
    DownloadType.TORRENT
)
"Order of preference of download types, for results that rank equally"


def protocol_rank(download_type: Union[DownloadType, int, None]) -> int:
    """Rank a download type for breaking ties between equally good search
    results. Lower is better.

    Args:
        download_type (Union[DownloadType, int, None]): The download type
            (or its value) of the indexer that the result came from.

    Returns:
        int: The rank.
    """
    for index, preferred_type in enumerate(PROTOCOL_PREFERENCE):
        if preferred_type == download_type:
            return index
    return len(PROTOCOL_PREFERENCE)
```

In `_run_iteration`, replace the "Remove indexers that should stop" loop with:

```python
        # Remove indexers that should stop
        remaining_actions = []
        remaining_indexers: List[IndexerTeam] = []
        for action_and_keys, team in zip(actions, self.indexers):
            if action_and_keys[0] == SearchAction.STOP:
                await team["indexer"].shutdown()
                continue
            remaining_actions.append(action_and_keys)
            remaining_indexers.append(team)

        actions = remaining_actions
        self.indexers = remaining_indexers
```

In `search`, the `self.found_results.append(...)` call becomes:

```python
                    if not is_duplicate:
                        self.found_links.add(indexer_result['link'])
                        self.found_results.append({
                            **indexer_result,
                            **match_result,
                            "download_type": team["indexer"].download_type.value
                        })
```

Replace the final sort in `search`:

```python
        self._sort_found_results(issue_year, calculated_issue_number)
        return self.found_results
```

Add this method to `SearchCoordinator`, directly after `_rank_search_result`:

```python
    def _sort_found_results(
        self,
        issue_year: Union[int, None],
        calculated_issue_number: Union[float, None]
    ) -> None:
        """Sort `self.found_results` from best to worst. The protocol of the
        result is only used to break ties.

        Args:
            issue_year (Union[int, None]): The year of the issue, if searching
                for an issue and release date is known.
            calculated_issue_number (Union[float, None]): The
                calculated_issue_number of the issue, if searching for one.
        """
        self.found_results.sort(key=lambda r: (
            self._rank_search_result(r, issue_year, calculated_issue_number),
            protocol_rank(r.get("download_type"))
        ))
        return
```

- [ ] **Step 5: Order RSS matches by protocol in `backend/features/search_discover.py`**

Add `protocol_rank` to the `search_full` import:

```python
from backend.features.search_full import choose_downloads, protocol_rank
```

In `discover_downloads`, directly after `all_releases = run(_get_all_new_releases())`, add:

```python
    indexer_types = {
        indexer.id: indexer.download_type
        for indexer in IndexerClients.get_all_clients()
    }
```

Directly before `full_matches[volume_id] = choose_downloads(...)`, add:

```python
        # choose_downloads is greedy in list order, so put the preferred
        # protocol first
        matched_releases.sort(
            key=lambda r: protocol_rank(indexer_types.get(r["indexer_id"]))
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'search_full.py'`

Expected: `OK` (4 tests).

Sanity check that the regression test really covers the bug: temporarily revert the `_run_iteration` change and rerun. `test_stopping_two_indexers_keeps_the_right_one` must fail. Restore the change afterwards.

- [ ] **Step 7: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK` and `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
git add backend/base/definitions.py backend/features/search_full.py backend/features/search_discover.py tests/Tbackend/features/search_full.py
git commit -F - <<'EOF'
Prefer Usenet on ties and fix dropping stopped indexers in search

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 4: NZB helper and SABnzbd client

**Files:**
- Create: `backend/implementations/usenet.py`
- Create: `backend/implementations/external_clients/usenet/SABnzbd.py`
- Create: `tests/Tbackend/implementations/usenet.py`
- Create: `tests/Tbackend/implementations/sabnzbd.py`

**Interfaces:**
- Consumes: `DownloadType.USENET` (Task 1)
- Produces:
  - `backend.implementations.usenet.NzbFile(name: str, filename: str, content: bytes)`, a frozen dataclass
  - `fetch_nzb(link: str) -> NzbFile`, which raises `DownloadLinkBroken` and caches by link
  - `pop_cached_nzb(link: str) -> Union[NzbFile, None]`
  - `extract_nzb_name(headers: Mapping[str, str], content: bytes) -> Union[str, None]`
  - `is_nzb(content: bytes) -> bool`
  - `SABnzbd`, an external client registered as `(USENET, "SABnzbd")`
  - `SABnzbd.get_download(id)` returns a dict with the keys `name`, `category`, `size`, `progress`, `speed`, `state`, `storage` and `fail_message`, or `None`
  - `parse_sab_jobs(queue: dict, history: dict) -> Dict[str, Dict[str, Any]]`

- [ ] **Step 1: Write the failing NZB helper tests**

Create `tests/Tbackend/implementations/usenet.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import DownloadLinkBroken
from backend.implementations import usenet
from backend.implementations.usenet import (extract_nzb_name, fetch_nzb,
                                            is_nzb, pop_cached_nzb)

NZB_CONTENT = b"""<?xml version="1.0" encoding="iso-8859-1" ?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
<head><meta type="name">Batman 001 (2016) (Meta)</meta></head>
<file poster="a@b" date="1" subject="x"><groups><group>alt.binaries.comics</group></groups>
<segments><segment bytes="1" number="1">id@x</segment></segments></file>
</nzb>"""


def fake_response(content, headers=None, ok=True):
    response = MagicMock()
    response.ok = ok
    response.content = content
    response.headers = headers or {}
    return response


class nzb_name(unittest.TestCase):
    def test_header_wins(self):
        self.assertEqual(
            extract_nzb_name(
                {"X-DNZB-Name": " Batman 001 (2016) ",
                 "Content-Disposition": 'attachment; filename="Other.nzb"'},
                NZB_CONTENT
            ),
            "Batman 001 (2016)"
        )

    def test_content_disposition(self):
        self.assertEqual(
            extract_nzb_name(
                {"content-disposition": 'attachment; filename="Batman 001 (2016).nzb"'},
                b"<nzb/>"
            ),
            "Batman 001 (2016)"
        )

    def test_meta_name(self):
        self.assertEqual(
            extract_nzb_name({}, NZB_CONTENT), "Batman 001 (2016) (Meta)"
        )

    def test_nothing_found(self):
        self.assertIsNone(extract_nzb_name({}, b"<nzb/>"))

    def test_is_nzb(self):
        self.assertTrue(is_nzb(NZB_CONTENT))
        self.assertTrue(is_nzb(b"<nzb/>"))
        self.assertFalse(is_nzb(b'<error code="100" description="x"/>'))
        self.assertFalse(is_nzb(b"not xml"))


class nzb_fetching(unittest.TestCase):
    def setUp(self):
        usenet._nzb_cache.clear()

    def test_fetch_caches_and_pop_clears(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(
                NZB_CONTENT, {"X-DNZB-Name": "Batman 001 (2016)"}
            )

            first = fetch_nzb("https://idx/a.nzb")
            second = fetch_nzb("https://idx/a.nzb")

        self.assertIs(first, second)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(first.name, "Batman 001 (2016)")
        self.assertEqual(first.filename, "Batman 001 (2016).nzb")
        self.assertEqual(first.content, NZB_CONTENT)
        self.assertIs(pop_cached_nzb("https://idx/a.nzb"), first)
        self.assertIsNone(pop_cached_nzb("https://idx/a.nzb"))

    def test_error_response_is_broken_link(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(
                b'<error code="300" description="No such item"/>'
            )
            with self.assertRaises(DownloadLinkBroken):
                fetch_nzb("https://idx/gone.nzb")

    def test_http_error_is_broken_link(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(b"", ok=False)
            with self.assertRaises(DownloadLinkBroken):
                fetch_nzb("https://idx/404.nzb")

    def test_unnamed_nzb_gets_fallback_name(self):
        with patch("backend.implementations.usenet.Session") as session_cls:
            session = session_cls.return_value.__enter__.return_value
            session.get.return_value = fake_response(b"<nzb/>")
            self.assertEqual(
                fetch_nzb("https://idx/b.nzb").name, "Unknown release"
            )
```

- [ ] **Step 2: Write the failing SABnzbd tests**

Create `tests/Tbackend/implementations/sabnzbd.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import (ClientNotWorking,
                                            CredentialInvalid)
from backend.base.definitions import DownloadState
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

        self.assertEqual(jobs["nzo_a"]["state"], DownloadState.DOWNLOADING_STATE)
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

        self.assertEqual(jobs["nzo_e"]["state"], DownloadState.DOWNLOADING_STATE)
        self.assertEqual(jobs["nzo_e"]["progress"], 99.0)
        self.assertIsNone(jobs["nzo_e"]["storage"])


class sabnzbd_client(unittest.TestCase):
    def test_get_download_refreshes(self):
        client = make_client()
        with patch.object(SABnzbd, "_api", side_effect=[QUEUE_JSON, HISTORY_JSON]):
            status = client.get_download("nzo_c")
        self.assertEqual(status["state"], DownloadState.IMPORTING_STATE)

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

    def test_add_download_reuses_existing_job(self):
        client = make_client()
        with patch.object(SABnzbd, "_api", side_effect=[QUEUE_JSON, HISTORY_JSON]), \
                patch(f"{MODULE}.fetch_nzb") as fetch, \
                patch(f"{MODULE}.pop_cached_nzb") as pop:
            nzo_id = client.add_download(
                "https://idx/a.nzb", "/downloads", "Batman Issue 001"
            )

        self.assertEqual(nzo_id, "nzo_a")
        fetch.assert_not_called()
        pop.assert_called_once_with("https://idx/a.nzb")

    def test_add_download_uploads_cached_nzb(self):
        client = make_client()
        nzb = NzbFile("Batman 001", "Batman 001.nzb", b"<nzb/>")
        api = MagicMock(side_effect=[
            EMPTY_QUEUE, EMPTY_HISTORY,
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
            side_effect=[EMPTY_QUEUE, EMPTY_HISTORY, {"status": False}]
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
        self.run_test_with({"version": "4.3.2"}, EMPTY_QUEUE)

    def test_bad_key(self):
        with self.assertRaises(CredentialInvalid):
            self.run_test_with(
                {"version": "4.3.2"},
                {"status": False, "error": "API Key Incorrect"}
            )

    def test_not_sabnzbd(self):
        with self.assertRaises(ClientNotWorking):
            self.run_test_with({"something": "else"})
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'usenet.py'; .venv/Scripts/python -m unittest discover -s ./tests -p 'sabnzbd.py'`

Expected: both ERROR with `ModuleNotFoundError`.

- [ ] **Step 4: Implement the NZB helper**

Create `backend/implementations/usenet.py`:

```python
# -*- coding: utf-8 -*-

"""
Fetching and inspecting NZB files
"""

from dataclasses import dataclass
from re import IGNORECASE, compile
from typing import Dict, Mapping, Union
from urllib.parse import unquote
from xml.etree.ElementTree import ParseError, fromstring

from requests.exceptions import RequestException
from requests.structures import CaseInsensitiveDict

from backend.base.custom_exceptions import DownloadLinkBroken
from backend.base.helpers import Session
from backend.base.logging import LOGGER

NZB_NAMESPACE = "http://www.newzbin.com/DTD/2003/nzb"
UNKNOWN_RELEASE_NAME = "Unknown release"
content_disposition_filename_regex = compile(
    r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
    IGNORECASE
)


@dataclass(frozen=True)
class NzbFile:
    name: str
    "The name of the release"

    filename: str
    "The filename to give the NZB file when uploading it"

    content: bytes


_nzb_cache: Dict[str, NzbFile] = {}
"""
NZB link to the fetched file. Filled by the prepper (that needs the release
name) and emptied by the download client (that uploads the file), so that the
NZB is only grabbed from the indexer once.
"""


def is_nzb(content: bytes) -> bool:
    """Check whether some content is an NZB file.

    Args:
        content (bytes): The content to check.

    Returns:
        bool: Whether it is an NZB file.
    """
    try:
        root = fromstring(content)
    except ParseError:
        return False
    return root.tag in (f"{{{NZB_NAMESPACE}}}nzb", "nzb")


def extract_nzb_name(
    headers: Mapping[str, str],
    content: bytes
) -> Union[str, None]:
    """Find the release name of an NZB file. Tries the `X-DNZB-Name` header,
    then the filename in the `Content-Disposition` header, then the name in
    the meta data of the NZB file.

    Args:
        headers (Mapping[str, str]): The headers of the response that
            delivered the NZB file.
        content (bytes): The NZB file.

    Returns:
        Union[str, None]: The name, or `None` if it couldn't be found.
    """
    headers = CaseInsensitiveDict(headers)

    header_name = (headers.get("X-DNZB-Name") or "").strip()
    if header_name:
        return header_name

    match = content_disposition_filename_regex.search(
        headers.get("Content-Disposition") or ""
    )
    if match:
        filename = unquote(match.group(1)).strip()
        if filename.lower().endswith(".nzb"):
            filename = filename[:-4].strip()
        if filename:
            return filename

    try:
        root = fromstring(content)
    except ParseError:
        return None

    for tag in (f"{{{NZB_NAMESPACE}}}meta", "meta"):
        for meta in root.iter(tag):
            if meta.get("type") in ("name", "title") and (meta.text or "").strip():
                return (meta.text or "").strip()

    return None


def fetch_nzb(link: str) -> NzbFile:
    """Download an NZB file, or get it from the cache if it was already
    downloaded.

    Args:
        link (str): The link to the NZB file.

    Raises:
        DownloadLinkBroken: The link doesn't lead to an NZB file.

    Returns:
        NzbFile: The NZB file.
    """
    if link in _nzb_cache:
        return _nzb_cache[link]

    try:
        with Session() as session:
            response = session.get(link)

    except RequestException:
        raise DownloadLinkBroken(link)

    if not response.ok or not is_nzb(response.content):
        raise DownloadLinkBroken(link)

    name = (
        extract_nzb_name(response.headers, response.content)
        or UNKNOWN_RELEASE_NAME
    )
    LOGGER.debug("Fetched NZB for release: %s", name)

    nzb = NzbFile(name=name, filename=f"{name}.nzb", content=response.content)
    _nzb_cache[link] = nzb
    return nzb


def pop_cached_nzb(link: str) -> Union[NzbFile, None]:
    """Take an NZB file out of the cache.

    Args:
        link (str): The link to the NZB file.

    Returns:
        Union[NzbFile, None]: The NZB file, or `None` if it isn't cached.
    """
    return _nzb_cache.pop(link, None)
```

- [ ] **Step 5: Implement the SABnzbd client**

Create `backend/implementations/external_clients/usenet/SABnzbd.py`:

```python
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
            LOGGER.exception("Can't connect to SABnzbd instance: ")
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
        "Fetch the queue and the Kapowarr history from SABnzbd"
        queue = self._api(
            self.ssn, self.base_url, self.api_token,
            {"mode": "queue"}
        )
        history = self._api(
            self.ssn, self.base_url, self.api_token,
            {
                "mode": "history",
                "category": Constants.EXTERNAL_DOWNLOAD_TAG,
                "limit": 100
            }
        )
        self.jobs = parse_sab_jobs(queue, history)
        self.last_update = time()
        return

    def _find_job_by_name(self, name: str) -> Union[str, None]:
        self._refresh()
        for nzo_id, job in self.jobs.items():
            if (
                job["name"] == name
                and job["category"] == Constants.EXTERNAL_DOWNLOAD_TAG
            ):
                return nzo_id
        return None

    def add_download(
        self,
        download_link: str,
        target_folder: str,
        download_name: Union[str, None]
    ) -> str:
        # The target folder is decided by the category in SABnzbd

        if download_name:
            existing_id = self._find_job_by_name(download_name)
            if existing_id:
                LOGGER.info(
                    "Download already in SABnzbd, reusing job: %s",
                    download_name
                )
                pop_cached_nzb(download_link)
                return existing_id

        nzb = pop_cached_nzb(download_link) or fetch_nzb(download_link)
        pop_cached_nzb(download_link)

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

        return
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'usenet.py' && .venv/Scripts/python -m unittest discover -s ./tests -p 'sabnzbd.py'`

Expected: `OK` (9 tests), then `OK` (10 tests).

- [ ] **Step 7: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK` and `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
git add backend/implementations/usenet.py backend/implementations/external_clients/usenet/SABnzbd.py tests/Tbackend/implementations/usenet.py tests/Tbackend/implementations/sabnzbd.py
git commit -F - <<'EOF'
Add NZB fetching helper and SABnzbd download client

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 5: UsenetDownload and Newznab prepper

**Files:**
- Create: `backend/implementations/download_clients/Usenet.py`
- Create: `backend/implementations/download_preppers/usenet/Newznab.py`
- Create: `tests/Tbackend/implementations/usenet_download.py`

**Interfaces:**
- Consumes:
  - Task 1: `DownloadClientIdentifier.USENET`, `DownloadService.USENET`, `EnqueuingDownloadFailureReason.NO_USENET_CLIENT`
  - Task 4: `fetch_nzb`, `pop_cached_nzb`, `NzbFile`
  - Task 4: `get_download()` dict keys `state`, `progress`, `speed`, `size`, `storage`
- Produces:
  - `UsenetDownload`, registered as `DownloadClientIdentifier.USENET`. Its constructor has the same signature as `TorrentDownload`.
  - `NewznabPrepper`, registered as `(USENET, "Newznab")`

- [ ] **Step 1: Write the failing tests**

Create `tests/Tbackend/implementations/usenet_download.py`:

```python
import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import (DownloadLinkBroken,
                                            EnqueuingDownloadFailure,
                                            ExternalClientNotFound)
from backend.base.definitions import (BlocklistReason,
                                      DownloadClientIdentifier,
                                      DownloadService, DownloadState,
                                      EnqueuingDownloadFailureReason)
from backend.implementations.download_clients.Usenet import UsenetDownload
from backend.implementations.download_preppers.usenet.Newznab import \
    NewznabPrepper
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
    return download


def status(state, storage=None):
    return {
        "size": 10, "progress": 100.0, "speed": 0.0,
        "state": state, "storage": storage
    }


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

    def test_no_usenet_client(self):
        with patch(f"{DOWNLOAD_MODULE}.Settings"), \
                patch(f"{DOWNLOAD_MODULE}.Volume"), \
                patch(f"{DOWNLOAD_MODULE}.ExternalClients") as clients:
            clients.get_least_used_client.side_effect = ExternalClientNotFound(-1)
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
        self.external.get_least_used_client.side_effect = \
            ExternalClientNotFound(-1)
        with self.assertRaises(EnqueuingDownloadFailure) as cm:
            self.prepper().get_downloads()
        self.assertReason(cm, EnqueuingDownloadFailureReason.NO_USENET_CLIENT)
        self.fetch.assert_not_called()

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'usenet_download.py'`

Expected: ERROR, `ModuleNotFoundError: No module named 'backend.implementations.download_clients.Usenet'`.

- [ ] **Step 3: Implement `UsenetDownload`**

Create `backend/implementations/download_clients/Usenet.py`:

```python
# -*- coding: utf-8 -*-

from os.path import basename, exists, join
from threading import Event
from typing import Any, Dict, Tuple, Union

from backend.base.custom_exceptions import (DownloadLinkBroken,
                                            EnqueuingDownloadFailure,
                                            ExternalClientNotFound,
                                            IssueNotFound)
from backend.base.definitions import (DownloadClientIdentifier,
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
from backend.implementations.volumes import Volume
from backend.internals.settings import Settings


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
        try:
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

        return

    def update_status(self) -> None:
        if not self.external_id:
            return

        status = self.external_client.get_download(self.external_id)
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

        self.external_client.delete_download(self.external_id, delete_files)
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
```

- [ ] **Step 4: Implement `NewznabPrepper`**

Create `backend/implementations/download_preppers/usenet/Newznab.py`:

```python
# -*- coding: utf-8 -*-

from typing import List, Union

from backend.base.custom_exceptions import (DownloadLinkBroken,
                                            EnqueuingDownloadFailure,
                                            ExternalClientNotFound,
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

        try:
            ExternalClients.get_least_used_client(DownloadType.USENET)
        except ExternalClientNotFound:
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'usenet_download.py'`

Expected: `OK` (11 tests).

- [ ] **Step 6: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK` and `Success: no issues found`.

The existing test `credentials.py` calls `DownloadClients.trigger_client_registration()`, which now also imports `Usenet.py`. It must still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/implementations/download_clients/Usenet.py backend/implementations/download_preppers/usenet/Newznab.py tests/Tbackend/implementations/usenet_download.py
git commit -F - <<'EOF'
Add Usenet download and Newznab download prepper

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 6: Post-processing and queue handling

**Files:**
- Modify: `backend/features/post_processing.py` (append after `PostProcessorTorrentsCopy`)
- Modify: `backend/features/download_queue.py` (imports; new module-level function; `__run_external_download`, ~lines 408-470)
- Create: `tests/Tbackend/features/download_queue.py`
- Create: `tests/Tbackend/implementations/remote_mapping.py`

**Interfaces:**
- Consumes: `DownloadClientIdentifier.USENET` (Task 1) and `UsenetDownload.remove_from_client` (Task 5)
- Produces:
  - `PostProcessorUsenet`
  - `get_external_post_processor(download: ExternalDownload, seeding_handling: SeedingHandling) -> PostProcessor`

- [ ] **Step 1: Write the failing tests**

Create `tests/Tbackend/features/download_queue.py`:

```python
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
```

Create `tests/Tbackend/implementations/remote_mapping.py`:

```python
import unittest

from backend.implementations.remote_mapping import RemoteMappings
from backend.internals.db import get_db
from Tbackend.db_helper import TempDatabase


class remote_to_local(unittest.TestCase):
    def test_translation_and_passthrough(self):
        with TempDatabase():
            cursor = get_db()
            client_id = cursor.execute("""
                INSERT INTO external_download_clients(
                    download_type, client_type, title, base_url, api_token
                ) VALUES (3, 'SABnzbd', 'SAB', 'http://sab:8080', 'TOKEN');
            """).lastrowid
            cursor.execute("""
                INSERT INTO remote_mappings(
                    external_download_client_id, remote_path, local_path
                ) VALUES (?, '/sab/complete/', '/local/complete/');
                """,
                (client_id,)
            )

            self.assertEqual(
                RemoteMappings.remote_to_local(
                    client_id, "/sab/complete/kapowarr/Batman"
                ),
                "/local/complete/kapowarr/Batman"
            )
            self.assertEqual(
                RemoteMappings.remote_to_local(client_id, "/other/Batman"),
                "/other/Batman"
            )
            self.assertEqual(
                RemoteMappings.remote_to_local(
                    client_id + 1, "/sab/complete/kapowarr/Batman"
                ),
                "/sab/complete/kapowarr/Batman"
            )
```

- [ ] **Step 2: Run the tests to verify their state**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'download_queue.py'; .venv/Scripts/python -m unittest discover -s ./tests -p 'remote_mapping.py'`

Expected:
- `download_queue.py` ERRORs with `ImportError: cannot import name 'get_external_post_processor'`.
- `remote_mapping.py` PASSES already. It is a characterisation test for a function that was never called before. If it fails, stop and report, because the design depends on this function.

- [ ] **Step 3: Add `PostProcessorUsenet` to `backend/features/post_processing.py`**

Append at the end of the file:

```python
class PostProcessorUsenet(PostProcessorTorrentsComplete):
    """
    Usenet downloads never seed, so they're always moved, extracted, scanned
    and renamed as soon as the download client reports them complete.
    """
```

- [ ] **Step 4: Split post-processing by type in `backend/features/download_queue.py`**

Update the post-processing import:

```python
from backend.features.post_processing import (PostProcessor,
                                              PostProcessorTorrentsComplete,
                                              PostProcessorTorrentsCopy,
                                              PostProcessorUsenet)
```

Add this module-level function directly above `class DownloadHandler`:

```python
def get_external_post_processor(
    download: ExternalDownload,
    seeding_handling: SeedingHandling
) -> PostProcessor:
    """Choose the post-processor for an external download.

    Args:
        download (ExternalDownload): The external download.
        seeding_handling (SeedingHandling): The seeding handling setting.

    Returns:
        PostProcessor: The post-processor for the download.
    """
    if download.identifier == DownloadClientIdentifier.USENET:
        return PostProcessorUsenet(download)

    if seeding_handling == SeedingHandling.COMPLETE:
        return PostProcessorTorrentsComplete(download)

    elif seeding_handling == SeedingHandling.COPY:
        return PostProcessorTorrentsCopy(download)

    else:
        assert_never(seeding_handling)
```

In `__run_external_download`, replace the `if seeding_handling == ... assert_never(seeding_handling)` block with:

```python
        pp = get_external_post_processor(download, seeding_handling)
```

In the same loop, replace the `IMPORTING_STATE` branch:

```python
            elif download.state == DownloadState.IMPORTING_STATE:
                if (
                    self.settings.sv.delete_completed_downloads
                    # Usenet downloads are moved out of the client's folder,
                    # so there is nothing left for the client's history
                    or download.identifier == DownloadClientIdentifier.USENET
                ):
                    download.remove_from_client(delete_files=False)
                pp.success()
                self.queue.remove(download)
                break
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p 'download_queue.py' && .venv/Scripts/python -m unittest discover -s ./tests -p 'remote_mapping.py'`

Expected: `OK` (2 tests), then `OK` (1 test).

- [ ] **Step 6: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK` and `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add backend/features/post_processing.py backend/features/download_queue.py tests/Tbackend/features/download_queue.py tests/Tbackend/implementations/remote_mapping.py
git commit -F - <<'EOF'
Import Usenet downloads on completion regardless of seeding handling

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 7: Frontend

**Files:**
- Modify: `frontend/templates/settings_indexers.html` (the `main` block)
- Modify: `frontend/static/js/settings_indexers.js`
- Modify: `frontend/templates/settings_download_clients.html` (window titles, the `main` block)
- Modify: `frontend/static/js/settings_download_clients.js`
- Modify: `frontend/static/js/view_volume.js` (`enqueueFailureReasonMap` ~line 47, manual search rendering ~line 363)
- Modify: `frontend/templates/settings_download.html` (help text ~lines 63 and 70)

**Interfaces:**
- Consumes:
  - `/indexers/options["3"]["Newznab"].required_tokens`, which includes `api_key` and `categories`
  - `/externalclients/options["3"]["SABnzbd"]`, which includes `api_token`
  - The indexer JSON `api_key` (string) and `categories` (array)
  - Search results carry `download_type`
  - The failure reason `no_usenet_client`
- Produces: UI only

There is no JS test framework in this repo. Verification is manual in Step 8.

- [ ] **Step 1: Add the Usenet section to the indexers page**

In `frontend/templates/settings_indexers.html`, inside `<div class="settings-container">`, after the DDL `</div>`:

```html
		<h2>Usenet</h2>
		<div id="usenet-indexer-list" class="client-list">
			<button id="add-usenet-indexer" class="add-button icon-text-color" title="Add Usenet indexer">
				<img src="{{url_base}}/static/img/cancel.svg" alt="">
			</button>
		</div>
```

- [ ] **Step 2: Handle the new fields in `frontend/static/js/settings_indexers.js`**

Add these functions after `createGCServicePreferenceInput`:

```js
function createTextInputRow(inputId, labelText, inputType, descriptionText) {
	const row = document.createElement('tr');
	const header = document.createElement('th');
	const label = document.createElement('label');
	label.innerText = labelText;
	label.setAttribute('for', inputId);
	header.appendChild(label);
	row.appendChild(header);
	const container = document.createElement('td');
	const input = document.createElement('input');
	input.type = inputType;
	input.id = inputId;
	input.required = true;
	container.appendChild(input);
	const description = document.createElement('p');
	description.innerText = descriptionText;
	container.appendChild(description);
	row.appendChild(container);
	return row;
}

function createApiKeyInput(inputId) {
	return createTextInputRow(
		inputId, 'API Key', 'password',
		'The API key of your account at the indexer.'
	);
}

function createCategoriesInput(inputId) {
	return createTextInputRow(
		inputId, 'Categories', 'text',
		'Comma separated Newznab category IDs to search in. 7030 is Comics. Add 7000 (Books) if your indexer files comics there.'
	);
}

function getIndexerExtraFields(form, prefix) {
	const data = {};

	const prefTable = form.querySelectorAll('#pref-table select');
	if (prefTable.length)
		data.gc_service_preference = [...prefTable].map(e => e.value);

	const gcAvoid = form.querySelector(`#${prefix}-gc-avoid-input`);
	if (gcAvoid)
		data.gc_avoid_large_downloads = gcAvoid.checked;

	const apiKey = form.querySelector(`#${prefix}-api-key-input`);
	if (apiKey)
		data.api_key = apiKey.value;

	const categories = form.querySelector(`#${prefix}-categories-input`);
	if (categories)
		data.categories = categories.value;

	return data;
}
```

In `loadEditIndexer`, after the `gc_service_preference` block (before `showWindow`):

```js
		if (clientOptions.includes('api_key')) {
			const apiKeyInput = createApiKeyInput('edit-api-key-input');
			apiKeyInput.querySelector('input').value =
				clientData.result.api_key || '';
			form.appendChild(apiKeyInput);
		};

		if (clientOptions.includes('categories')) {
			const categoriesInput = createCategoriesInput('edit-categories-input');
			categoriesInput.querySelector('input').value =
				(clientData.result.categories || []).join(',');
			form.appendChild(categoriesInput);
		};
```

In `saveEditIndexer`, delete the `prefTable`/`gcServicePreference` lines and replace the `data` object:

```js
			const data = {
				title: form.querySelector('#edit-title-input').value,
				enabled: form.querySelector('#edit-enabled-input').checked,
				url: form.querySelector('#edit-url-input').value,
				...getIndexerExtraFields(form, 'edit')
			};
```

In `testEditIndexer`, delete the `prefTable`/`gcServicePreference` lines and replace the `data` object:

```js
	const data = {
		download_type: parseInt(form.dataset.download_type),
		client_type: form.dataset.type,
		url: form.querySelector('#edit-url-input').value,
		...getIndexerExtraFields(form, 'edit')
	};
```

In `loadAddIndexer`, after the `gc_service_preference` line (before `showWindow`):

```js
		if (clientOptions.required_tokens.includes('api_key'))
			form.appendChild(createApiKeyInput('add-api-key-input'));

		if (clientOptions.required_tokens.includes('categories')) {
			const categoriesInput = createCategoriesInput('add-categories-input');
			categoriesInput.querySelector('input').value = '7030';
			form.appendChild(categoriesInput);
		};
```

In `saveAddIndexer`, delete the `prefTable`/`gcServicePreference` lines and replace the `data` object:

```js
			const data = {
				download_type: parseInt(form.dataset.download_type),
				client_type: form.dataset.type,
				title: form.querySelector('#add-title-input').value,
				enabled: form.querySelector('#add-enabled-input').checked,
				url: form.querySelector('#add-url-input').value,
				...getIndexerExtraFields(form, 'add')
			};
```

In `testAddIndexer`, delete the `prefTable`/`gcServicePreference` lines and replace the `data` object:

```js
	const data = {
		download_type: parseInt(form.dataset.download_type),
		client_type: form.dataset.type,
		url: form.querySelector('#add-url-input').value,
		...getIndexerExtraFields(form, 'add')
	};
```

`testAddIndexer`'s `else` branch has no braces, so the error text is set even on success. Fix it while you're here:

```js
		if (json.result.success)
			// Test successful
			testButton.classList.add('show-success');
		else {
			// Test failed
			testButton.classList.add('show-fail');
			error.innerText = brokenClientReasonMap[json.result.description];
			hide([], [error]);
		};
		return json.result.success;
```

Replace `typeToList`, and guard against unknown types in `loadIndexers`:

```js
const typeToList = {
	1: document.querySelector("#ddl-indexer-list"),
	3: document.querySelector("#usenet-indexer-list")
};
```

```js
		json.result.forEach(indexer => {
			const list = typeToList[indexer.download_type];
			if (!list)
				return;
			const entry = document.createElement('button');
			entry.onclick = e => loadEditIndexer(apiKey, indexer.id);
			entry.innerText = indexer.title;
			list.appendChild(entry);
		});
```

- [ ] **Step 3: Add the Usenet Clients section to `frontend/templates/settings_download_clients.html`**

Rename the three window titles, since the windows now serve both types:

- `"Choose Torrent Client"` → `"Choose Download Client"`
- `"Add Torrent Client"` → `"Add Download Client"`
- `"Edit Torrent Client"` → `"Edit Download Client"`

After the Torrent Clients `</div>` (before `<h2>Remote Path Mappings</h2>`):

```html
		<h2>Usenet Clients</h2>
		<div id="usenet-client-list" class="client-list">
			<button id="add-usenet-client" class="add-button icon-text-color" title="Add Usenet client">
				<img src="{{url_base}}/static/img/cancel.svg" alt="">
			</button>
		</div>
```

- [ ] **Step 4: Stop hardcoding `download_type: 2` in `frontend/static/js/settings_download_clients.js`**

In `loadEditTorrent`, after `form.dataset.type = client_type;`:

```js
		form.dataset.download_type = client_data.result.download_type;
```

In `testEditTorrent`, `testAddTorrent` and `saveAddTorrent`, replace `download_type: 2,` with:

```js
		download_type: parseInt(form.dataset.download_type),
```

In `saveAddTorrent`, the line sits inside `const data = {` and keeps its deeper indentation.

Replace `loadTorrentList` and the start of `loadAddTorrent`:

```js
function loadTorrentList(api_key, downloadType) {
	const table = document.querySelector('#choose-torrent-list');
	table.innerHTML = '';

	fetchAPI('/externalclients/options', api_key)
	.then(json => {
		Object.keys(json.result[downloadType]).forEach(c => {
			const entry = document.createElement('button');
			entry.innerText = c;
			entry.onclick = e => loadAddTorrent(api_key, downloadType, c);
			table.appendChild(entry);
		});
		showWindow('choose-torrent-window');
	});
};

function loadAddTorrent(api_key, downloadType, client_type) {
	const form = document.querySelector('#add-torrent-form tbody');
	form.dataset.type = client_type;
	form.dataset.download_type = downloadType;
```

The rest of `loadAddTorrent` stays the same, except for this line:

```js
		const client_options = json.result[downloadType][client_type];
```

In `loadTorrentClients`, add a lookup before the function:

```js
const clientLists = {
	2: '#torrent-client-list',
	3: '#usenet-client-list'
};
```

Inside the function, replace the list clearing and the entry appending:

```js
		document.querySelectorAll(
			'#torrent-client-list > :not(:first-child), #usenet-client-list > :not(:first-child)'
		).forEach(el => el.remove());
```

```js
		json.result.forEach(client => {
			const list = document.querySelector(clientLists[client.download_type]);
			if (list) {
				const entry = document.createElement('button');
				entry.onclick = (e) => loadEditTorrent(api_key, client.id);
				entry.innerText = client.title;
				list.appendChild(entry);
			};

			const option = document.createElement('option');
			option.innerText = client.title;
			option.value = client.id;
			add_mapping_select.appendChild(option);
			edit_mapping_select.appendChild(option.cloneNode(true));
		});
```

Also remove the now-unused `table` from the `const` declaration at the top of `loadTorrentClients`:

```js
		const add_mapping_select = document.querySelector('#add-mapping-client-input'),
			edit_mapping_select = document.querySelector('#edit-mapping-client-input');
```

In the on-load block, replace the `#add-torrent-client` line:

```js
	document.querySelector('#add-torrent-client').onclick = e => loadTorrentList(api_key, 2);
	document.querySelector('#add-usenet-client').onclick = e => loadTorrentList(api_key, 3);
```

- [ ] **Step 5: Hide NZB links and label Usenet results in `frontend/static/js/view_volume.js`**

Add to `enqueueFailureReasonMap`, after `link_rate_limited`:

```js
    link_rate_limited: "Download link rate limited",
    no_usenet_client: "No enabled Usenet download client"
```

In the manual search rendering, replace the `title.href`/`innerText` and `source-column` lines:

```js
			const title = entry.querySelector('a');
			title.innerText = result.display_title;
			if (result.download_type === 3)
				// NZB links contain the API key of the indexer
				title.removeAttribute('href');
			else
				title.href = result.link;

			entry.querySelector('.source-column').innerText =
				result.download_type === 3
					? `${result.indexer_title} (Usenet)`
					: result.indexer_title;
```

- [ ] **Step 6: Update the help text in `frontend/templates/settings_download.html`**

Seeding Handling paragraph:

```html
							<p>How a torrent that goes seeding should be handled. Either wait until it has completed seeding and then move the files, or copy the files and then delete the original when seeding finishes. Usenet downloads are always imported as soon as they complete.</p>
```

Delete Completed Downloads paragraph:

```html
							<p>Remove external downloads from their download client history when they have completed. Usenet downloads are always removed from SABnzbd's history.</p>
```

- [ ] **Step 7: Run the full suite and mypy**

Run: `.venv/Scripts/python -m unittest discover -s ./tests -p '*.py' && .venv/Scripts/python -m mypy --explicit-package-bases .`

Expected: `OK` and `Success: no issues found`.

- [ ] **Step 8: Check the settings pages manually against a scratch database**

Run: `.venv/Scripts/python Kapowarr.py -d "$TMP/kapowarr-usenet-check" -t "$TMP/kapowarr-usenet-downloads"` (`-d` is the database folder, `-t` the temp download folder). Open `http://localhost:5656`.

Verify all of these with the browser devtools console open:

1. Settings → Indexers shows "DDL" with GetComics and an empty "Usenet" section. Adding in Usenet offers "Newznab".
2. The Newznab add form shows Title, Enable, URL, API Key (a password field) and Categories (prefilled `7030`). Test against a bad URL shows a failure message.
3. Editing GetComics still shows Avoid Large Downloads and Service Preference, and Save works.
4. Settings → Download Clients shows "Torrent Clients" and "Usenet Clients". Adding in Usenet offers "SABnzbd" with Base URL and API Token fields. The Torrent add still offers qBittorrent and Transmission.
5. There are no JS errors in the console on any of these pages.

Stop the server afterwards.

- [ ] **Step 9: Commit**

```bash
git add frontend/templates/settings_indexers.html frontend/static/js/settings_indexers.js frontend/templates/settings_download_clients.html frontend/static/js/settings_download_clients.js frontend/static/js/view_volume.js frontend/templates/settings_download.html
git commit -F - <<'EOF'
Add Usenet indexer and client settings UI, hide NZB links in search

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XpvMaP8bfqbSkHogGimPy4
EOF
```

---

### Task 8: End-to-end check against a real indexer and SABnzbd (with the user)

The user runs this with their own NZB indexer account and SABnzbd. It needs no code, only fixes for whatever it finds (each through the TDD loop above).

**Before starting**

- In SABnzbd, create the category `kapowarr` (Config → Categories).
- Start Kapowarr on a copy of the user's real database, or a scratch one with a volume added.
- If SABnzbd runs in Docker or on another machine, add a Remote Path Mapping from SABnzbd's complete folder to the same folder as Kapowarr sees it.

**Steps**

- [ ] **Step 1:** Add the Newznab indexer (URL, API key, `7030`). Test must show Success.
- [ ] **Step 2:** Add SABnzbd (base URL, API key). Test must show Success, and a wrong key must show "Failed to login with the given credentials".
- [ ] **Step 3:** Run a manual search on one volume.
  - Usenet results show "(Usenet)" and aren't links.
  - Where an NZB and a GetComics result match equally, the NZB is listed first.
- [ ] **Step 4:** Download one Usenet result.
  - The job appears in SABnzbd under `kapowarr`.
  - Kapowarr's queue shows progress.
  - On completion the files land in the volume folder, renamed.
  - The SABnzbd history entry is gone.
- [ ] **Step 5:** Start another download, restart Kapowarr mid-download, and confirm the queue entry resumes with no duplicate job in SABnzbd.
- [ ] **Step 6:** Delete a queued download in Kapowarr and confirm SABnzbd removes the job.
- [ ] **Step 7:** Trigger the "RSS Sync" task and check the log for errors.
- [ ] **Step 8:** Record the findings. If anything was fixed, commit the fixes, then run the full suite and mypy again.
