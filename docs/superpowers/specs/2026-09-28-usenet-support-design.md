# Usenet Support (Newznab + SABnzbd) — Design

- **Date:** 2026-09-28
- **Issue:** [Casvt/Kapowarr#71](https://github.com/Casvt/Kapowarr/issues/71)
- **Scope:** Personal fork only (`robert-hernandez-cenk/Kapowarr`), built on `main`. Not intended as an upstream PR.
- **Branch:** `feature/usenet-support`

## Goal

Let Kapowarr search Newznab indexers (NZB.su, NZBGeek, DrunkenSlug, ...) for comics, send chosen NZBs to SABnzbd, and import completed downloads into the library. This works for manual search, automatic search, and RSS sync. When a Usenet result and a GetComics result match equally well, the Usenet result wins.

## Approach

Add a third `DownloadType` (`USENET = 3`) and implement the same set of plugins GetComics already has: indexer client, query builder, download prepper, download class, and external client. While doing so, fix the places where the code assumes every external download is a torrent. Other approaches were considered and rejected:

- treating NZBs as a torrent variant, which deepens the torrent assumptions and conflicts with upstream
- a Prowlarr bridge, which adds a required extra service and saves little

## 1. Definitions, database, Newznab indexer

### Definitions (`backend/base/definitions.py`)

- `DownloadType.USENET = 3`
- `IndexerClientField.API_KEY = "api_key"`, `IndexerClientField.CATEGORIES = "categories"`
- `DownloadService.USENET = "Usenet"`
- `DownloadClientIdentifier.USENET = "usenet"`
- `IndexerClientData` gains `api_key: Union[str, None]` and `categories: Union[CommaList, None]`. Both are `None` for GetComics, and `gc_*` is `None` for Newznab.

### Database

Migration handler 51 (DB version 51 → 52) adds two nullable columns to `indexer_clients`:

- `api_key TEXT`
- `categories TEXT`, a comma list, stored like `gc_service_preference`

These columns are also added to:

- the `indexer_clients` table definition in `backend/internals/db.py`, for fresh installs
- the hardcoded SELECT in `BaseIndexerClient.__init__`, the UPDATE in `update_indexer`, and the INSERT in `IndexerClients.add` (`backend/implementations/indexer_client_manager.py`)
- `_validate_indexer_data`:
  - `CATEGORIES` is parsed into a `CommaList` of numeric strings. An empty value is rejected.
  - `API_KEY` must be a non-empty string.

`get_indexer_data()` returns `api_key` masked as `Constants.CREDENTIAL_REPLACEMENT`. On update, receiving the masked value keeps the stored key, the same way external client passwords work.

### Newznab indexer (`backend/implementations/indexer_clients/usenet/Newznab.py`)

Registered as `(DownloadType.USENET, "Newznab", (TITLE, ENABLED, URL, API_KEY, CATEGORIES))`, with `allow_multiple_instances=True`.

**`search(query)`**

- Request: `GET {url}/api?t=search&q={query}&cat={categories}&apikey={key}&offset={page*100}&limit=100`
- The response is parsed as RSS/XML, which every Newznab implementation supports. Each `<item>` becomes a `SearchResultData`:
  - `title` goes through `extract_filename_data(title, assume_volume_number=False, fix_year=True)`, as GetComics does
  - `link` comes from `<enclosure url>`, falling back to `<link>`
  - `size` comes from `<enclosure length>` or the `newznab:attr name="size"`
  - `display_title` is the raw title
  - `indexer_id` and `indexer_title` are set as for GetComics
- `next_page_available` is true when `offset + items < newznab:response total`.

**`discover(last_check)`**

- Uses the same endpoint with no `q`, so it covers the categories only.
- Pages until an item's `pubDate` is older than `last_check`, capped at 5 pages.
- Returns the matching items in the same result shape.

**`test(url, api_key, categories)`**

- Calls `GET {url}/api?t=caps&apikey={key}`.
- A Newznab `<error code>` of 100, 101 or 102 raises `CredentialInvalid`.
- A connection error, a non-XML response, or any other error code raises `ClientNotWorking`.

**Error handling during search**

- Error code 500 (request limit reached) and connection errors are logged as warnings.
- The failing indexer returns an empty `QueryResult(next_page_available=False)` for that query, so its planner stops without failing the whole search.

**Categories and URL**

- Default categories are `7030` (Comics). The UI hint suggests adding `7000` (Books) for indexers that file comics there.
- The URL is stored without the trailing `/api`. If the user enters it with `/api`, it is stripped.

### Query builder (`backend/implementations/query_builders/Usenet.py`)

- Registered as `@QueryBuilders.register_builder(DownloadType.USENET)`. It subclasses `DDLQueryBuilder` and reuses its format variations (TPB, VAI, VOLUME, SPECIFIC_ISSUE, GENERAL_ISSUE).
- `page` is passed through. The indexer converts it to `offset`.

## 2. Ranking, prepper, download class, SABnzbd client

### Ranking (`backend/features/search_full.py`)

- The `SearchCoordinator` builds an `indexer_id → DownloadType` map from its indexer teams.
- `_rank_search_result` appends a final sort-key element: the protocol rank, where `USENET` beats `DDL`. It is the last element, so it only breaks ties after all match-quality elements.
- `choose_downloads` uses the same ranking. It is shared by auto search and RSS sync (`search_discover.py`), and RSS sync builds the same map from the enabled indexers.

**Bug fix:** in `_run_iteration`, stopped indexers are currently removed with `del actions[idx]` / `del self.indexers[idx]` inside a loop over the original indices. Replace this with a rebuild that keeps only the non-stopped pairs.

### Prepper (`backend/implementations/download_preppers/usenet/Newznab.py`)

- Registered as `(DownloadType.USENET, "Newznab")`.
- `get_downloads()` returns `[UsenetDownload(...)]` for the NZB link.
- The covered issues come from `extract_filename_data` on the release title (the web title), mapped to the volume's issues the same way GetComics link paths are.
- If the title doesn't match the volume/issue and `force_match` is false, it raises `EnqueuingDownloadFailure`.

### Download class (`backend/implementations/download_clients/Usenet.py`)

`UsenetDownload(ExternalDownload, BaseDirectDownload)` is registered as `DownloadClientIdentifier.USENET`.

- `__init__`:
  - Uses the passed `external_client` when restoring from the DB. Otherwise it calls `ExternalClients.get_least_used_client(DownloadType.USENET)`.
  - Catches `ExternalClientNotFound` and raises `EnqueuingDownloadFailure("No enabled Usenet download client")`.
  - Takes the title from the release title, sanitised for use as a filename.
  - Uses `download_service = DownloadService.USENET` and `source_name` = the indexer title.
  - Leaves `files` empty until the job completes.
- `run()`: `external_id = external_client.add_download(download_link, <unused target>, title)`.
- `update_status()` copies progress, speed, size and state from `get_download()`. `None` means CANCELED. On IMPORTING it also captures `storage`.

### SABnzbd client (`backend/implementations/external_clients/usenet/SABnzbd.py`)

Registered as `(DownloadType.USENET, "SABnzbd", (TITLE, ENABLED, BASE_URL, API_TOKEN))`. All calls go to `{base_url}/api?output=json&apikey={token}&mode=...`.

**`add_download(link, target_folder, name)`**

- Calls `mode=addurl&name={link}&cat=kapowarr&nzbname={name}` and returns `nzo_ids[0]`.
- Raises `ExternalClientNotWorking` if `status` is false.
- `target_folder` is ignored. SABnzbd's `kapowarr` category controls where files land, and the user sets up that category in SABnzbd. A missing category makes SABnzbd fall back to its default, which is acceptable.

**Status polling**

- Batched refresh of `mode=queue` and `mode=history&category=kapowarr`, at most once every 30 s, cached per client instance. This follows the qBittorrent pattern.
- `get_download(nzo_id)` returns `None` when the ID is in neither list.

**State mapping**

| SABnzbd status | DownloadState | Notes |
|---|---|---|
| Queued, Grabbing, Fetching, Propagating | QUEUED | |
| Downloading | DOWNLOADING | |
| Paused | PAUSED | |
| Checking, QuickCheck, Verifying, Repairing, Extracting, Moving, Running | DOWNLOADING | progress reported as 99 |
| Completed | IMPORTING | `storage` exposed |
| Failed | FAILED | `fail_message` logged |

**Other methods**

- `delete_download(nzo_id, delete_files)`:
  - A queue item is deleted with `mode=queue&name=delete&value={id}&del_files={0|1}`.
  - A history item is deleted with `mode=history&name=delete&value={id}&del_files={0|1}`.
- `test(base_url, username, password, api_token)`:
  - Calls `mode=version`, which raises `ClientNotWorking` on a connection or HTTP error.
  - Then calls `mode=queue&limit=1`. An `"API Key Incorrect"` or `"API Key Required"` error raises `CredentialInvalid`.

## 3. Queue handling, post-processing, paths

### Picking the post-processor (`backend/features/download_queue.py`, `__run_external_download`)

- If the download is a `UsenetDownload`, use `PostProcessorUsenet`. Otherwise keep the existing seeding-handling choice (`PostProcessorTorrentsComplete` / `PostProcessorTorrentsCopy`). Seeding handling is never consulted for Usenet.
- The polling loop is otherwise unchanged:
  - CANCELED: `remove_from_client(True)`, then `pp.canceled`.
  - FAILED: `remove_from_client(True)`, then `perm_failed`, which blocklists the NZB link.
  - IMPORTING: `pp.success`.

### Finding the files (`backend/implementations/remote_mapping.py`)

- On IMPORTING, `UsenetDownload` sets `files = [RemoteMappings.remote_to_local(client.id, storage)]`.
- If that path doesn't exist locally, the download goes to FAILED. The log line names the SABnzbd path, the translated local path, and the Remote Mapping setting. It does not import nothing silently, and it does not blocklist, because this is a configuration error rather than a bad release.
- `remote_to_local` has never been called before, so its behaviour gets verified and tested: longest-prefix match, and passthrough when no mapping applies.

### PostProcessorUsenet (`backend/features/post_processing.py`)

Based on `PostProcessorTorrentsComplete`, using the existing helpers rather than copies of them. `success` runs these steps:

1. Move the files from the storage path to the volume folder (`move_torrent_to_dest` logic, generalised or reused).
2. Run `extract_files_from_folder`, which handles any `.rar`/`.zip` left over if SABnzbd unpacking was off.
3. Run `scan_files` and `mass_rename`.
4. Remove the job from SABnzbd's history with `del_files=0`, since the files have already been moved.
5. Remove it from the queue and add a history entry, as for torrents.

`canceled` and `perm_failed` behave as they do for torrents.

### Restart safety

- `__load_downloads` rebuilds from `download_queue.client_type = "usenet"`, `external_client_id` and `external_id`.
- `UsenetDownload` accepts the same constructor arguments as `TorrentDownload`, so in-flight jobs resume polling.

### Display

Queue, history and blocklist show `source_type = "Usenet"` and `source_name` = the indexer title. The existing JS renders these strings unchanged.

## 4. Frontend

### Indexers (`frontend/templates/settings_indexers.html`, `frontend/static/js/settings_indexers.js`)

- Add a "Usenet" section (`#usenet-indexer-list`) under DDL. `typeToList = {1: ddl, 3: usenet}`. Indexers of unknown types are skipped rather than throwing.
- The add/edit forms render inputs from `required_tokens`:
  - `api_key`: a password input, sent as the masked value when unchanged
  - `categories`: a text input prefilled with `7030`, with a hint about `7000`
- Save/test payloads include only the fields the indexer declares, instead of always sending `gc_*`.
- The Usenet section's add button offers the client types from `/indexers/options[3]`, which is Newznab.

### Download clients (`frontend/templates/settings_download_clients.html`, `frontend/static/js/settings_download_clients.js`)

- Split the list into "Torrent Clients" (`download_type` 2) and "Usenet Clients" (`download_type` 3), each filtered by type.
- Replace the hardcoded `download_type: 2` and `result[2]` with the type passed by each section's add button.
- The SABnzbd form shows Base URL and API key, driven by `required_tokens`.
- Remote-mapping selects already list every external client. No change is needed there.

### Manual search (`frontend/static/js/view_volume.js`)

- For results from Usenet indexers, the title is rendered as plain text rather than a link to `result.link`. This keeps the API-key-bearing NZB URL out of the DOM.
- A "Usenet" badge is shown next to the indexer title.
- The download action still posts `{link, indexer_id, force_match}`.

### Download settings (`frontend/templates/settings_download.html`)

The Seeding Handling help text gains "Only applies to torrents."

## 5. Testing

The tests use unittest under `tests/Tbackend/`, with HTTP mocked and no live network calls.

- `implementations/newznab.py`:
  - parsing recorded search XML into results, including size and link
  - paging decided from offset/total
  - error 100 → `CredentialInvalid`
  - error 500 → empty result
  - `discover` stops at `last_check`
  - `/api` suffix stripping
- `implementations/sabnzbd.py`:
  - state mapping from recorded queue/history JSON
  - `storage` extraction
  - `get_download` returns `None` for an unknown ID
  - a bad API key → `CredentialInvalid`
- `features/search_ranking.py`:
  - with equal match quality, Usenet ranks above DDL
  - a better-matching DDL result ranks above a worse Usenet one
- `features/search_coordinator.py`: when two indexers stop in the same iteration, the correct remaining indexers are kept (regression test).
- `implementations/remote_mapping.py`: mapping applied, longest prefix wins, passthrough when no mapping applies.
- `features/download_queue.py`: a `UsenetDownload` gets `PostProcessorUsenet` under both seeding-handling settings.
- `mypy --explicit-package-bases .` passes.
- Existing tests pass.

**Manual end-to-end check** against a real Newznab indexer and SABnzbd:

1. Add both and pass Test on each.
2. Run a manual search for one volume. Confirm Usenet results show the badge and no NZB link is exposed.
3. Grab one and watch the queue progress.
4. Confirm the files import, are renamed, and leave no job in SABnzbd history.
5. Restart Kapowarr during a download and confirm it resumes.
6. Confirm the RSS sync task runs without errors.

## Out of scope

- NZBGet
- Prowlarr sync
- Per-indexer priority or a configurable protocol preference
- Newznab `t=book` / caps-driven search modes
- Automatic re-search after a failure, beyond the existing blocklist behaviour
- Upstream contribution
