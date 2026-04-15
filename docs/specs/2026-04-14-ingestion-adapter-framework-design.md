# Ingestion Adapter Framework — Design Spec

**Date:** 2026-04-14
**Status:** Draft (post-adversarial review)
**Author:** Claude (Opus), with Stuart Watson
**Reviewed by:** Three adversarial Claude agents (HTML compatibility, output format, scope/YAGNI)

## 1. Purpose

Replace the 50+ bespoke capture scripts with a framework where each data source platform gets one adapter class, and each source instance gets a YAML config entry. Adding a new city that runs Granicus should be a YAML entry, not a new script.

## 2. Scope

**Build now:**
- Adapter base class (the contract all adapters follow)
- Granicus adapter with variant detection (handles both legacy and modern Granicus templates)
- Source registry (`registry/sources.yaml`)
- Runner script (`scripts/ingest.py`)
- Validate against 3 Granicus sources: Marin County BOS (legacy template), Novato (modern template), Sausalito (modern template)

**Build later:**
- CivicPlus adapter (covers Mill Valley, San Anselmo, Larkspur, Corte Madera, Tiburon)
- NetFile adapter (covers county + San Rafael + Novato campaign finance)
- Auto-normalization from adapter output to Neo4j
- Scheduling/cron
- Custom scrapers for WordPress/ProudCity cities (San Rafael, Fairfax, Belvedere)
- Custom scrapers for other platforms (Ross/Drupal, Marin Water/Municode)

## 3. Platform Coverage (Marin County)

| Platform | Cities | Adapter | Status |
|---|---|---|---|
| Granicus Publisher View | Novato, Sausalito, Marin County, Tiburon (video) | `granicus` | **This plan** |
| CivicPlus Agenda Center | Mill Valley, San Anselmo, Larkspur, Corte Madera, Tiburon (agendas) | `civicplus` | Future |
| NetFile (campaign finance) | Marin County, San Rafael, Novato | `netfile` | Future |
| ProudCity/WordPress | San Rafael, Fairfax, Belvedere | Custom per site | Future |
| Drupal | Ross | Custom | Low priority |

## 4. Critical Discovery: Granicus Template Variants

Adversarial review fetched all three Granicus pages and found **two distinct template generations**. A single parsing path will not work. The adapter must detect and handle both.

### What's shared (safe to use in common code)

- `<tr class="listingRow">` for meeting rows
- `<td class="listItem">` for cells within rows
- `window.open(...)` pattern for video links
- `AgendaViewer.php?...&clip_id=NNN` pattern for agenda URLs
- Upcoming events section layout

### What differs (variant-specific parsing required)

| Feature | Legacy (Marin BOS) | Modern (Novato, Sausalito) |
|---|---|---|
| **Year sections** | `<!-- 2024 Start -->` HTML comments | TabbedPanels widget or flat `<tbody>` — no year comments |
| **Column layout** | 9 cols: Month, Name, Date, Agenda, Minutes, Video, Captions, MP3, MP4 | 6-7 cols: Name, Date, Duration, Agenda, Minutes, Video [, MP4] — no Month column |
| **Date format** | `03/10/26` (2-digit year, no spaces) | `03 / 24 / 2026` (4-digit, `&nbsp;` separated) or `Apr 7, 2026` (month name) |
| **Hidden epoch** | `<span style="display:none;">1773126000</span>` in date cells | Not present |

### Adapter design: auto-detection

The Granicus adapter detects the variant from the fetched HTML:
- If `<!-- \d{4} Start -->` comments are present → **legacy parser**
- Otherwise → **modern parser**

Both parsers share: row/cell extraction, artifact URL parsing, meeting classification. They differ in: year detection, column mapping, date parsing.

## 5. Architecture

### Data Flow

```
registry/sources.yaml          "what sources exist"
        │
        ▼
scripts/ingest.py              "runner: load config, dispatch adapter"
        │
        ▼
scripts/adapters/granicus.py   "fetch + auto-detect variant + parse"
        │
        ▼
data/raw/{source_id}/{date}/   "raw HTML artifact"
data/extracted/{source_id}/    "structured JSON output"
```

### File Structure

```
registry/
  sources.yaml                  # All source instances with adapter type + config
scripts/
  ingest.py                     # CLI runner
  adapters/
    __init__.py
    base.py                     # BaseAdapter ABC
    granicus.py                 # Granicus adapter (legacy + modern variants)
```

### Source Registry Format

```yaml
sources:
  - id: marin-county-bos
    adapter: granicus
    url: https://marin.granicus.com/ViewPublisher.php?view_id=33
    jurisdiction_id: place-marin-county
    institution_id: org-marin-county-board-of-supervisors
    backfill_from: "2019-01-01"
    schedule: weekly

  - id: novato-city-council
    adapter: granicus
    url: https://novato.granicus.com/ViewPublisher.php?view_id=7
    jurisdiction_id: place-novato
    institution_id: org-novato-city-council
    backfill_from: "2019-01-01"
    schedule: weekly

  - id: sausalito-city-council
    adapter: granicus
    url: https://sausalito.granicus.com/ViewPublisher.php?view_id=6
    jurisdiction_id: place-sausalito
    institution_id: org-sausalito-city-council
    backfill_from: "2019-01-01"
    schedule: weekly
```

Each entry:
- `id` — unique identifier, becomes the directory name under `data/raw/` and `data/extracted/`
- `adapter` — which adapter class to use
- `url` — the entry point URL the adapter fetches
- `jurisdiction_id` / `institution_id` — settled-ontology IDs for the jurisdiction and institution these meetings belong to
- `backfill_from` — earliest date to capture (adapter skips meetings before this)
- `schedule` — intended refresh cadence (informational, not enforced in this plan)

### BaseAdapter Contract

```python
class BaseAdapter(ABC):
    def __init__(self, source_config: dict, root_dir: Path):
        """Initialize with source config from YAML and project root."""

    @abstractmethod
    def capture(self) -> dict:
        """Fetch data from the source. Returns the extracted JSON dict
        (same structure that gets written to disk)."""

    def raw_dir(self) -> Path:
        """Where raw artifacts are stored: data/raw/{source_id}/{date}/"""

    def extracted_path(self) -> Path:
        """Where extracted JSON goes: data/extracted/{source_id}/{date}.json"""
```

The `capture()` method returns the output dict directly — no intermediate CaptureResult dataclass. The dict is what gets serialized to the extracted JSON file.

### Granicus Adapter

Refactored from the existing `capture_marin_county_bos_archive.py` (390 lines), extended with a modern-template parser for Novato/Sausalito.

**Common logic (both variants):**
1. Fetch the Granicus Publisher View page (single HTTP GET, 1-2s delay between sources)
2. Detect variant (legacy vs modern) from HTML structure
3. Extract meeting rows via `<tr class="listingRow">` / `<td class="listItem">`
4. Extract artifact URLs from cell links (href) and onclick handlers (`window.open`)
5. Classify meetings (regular, special, budget, joint, etc.) from title text
6. Filter by `backfill_from` date
7. Write raw HTML and structured JSON

**Legacy parser (Marin BOS):**
- Partition by `<!-- YYYY Start -->` HTML comments
- 9-column mapping: Month | Name | Date | Agenda | Minutes | Video | Captions | MP3 | MP4
- Date regex: `(\d{2})/(\d{2})/(\d{2})` → `%m/%d/%y`
- Extract hidden epoch spans for sort ordering

**Modern parser (Novato, Sausalito):**
- Partition by TabbedPanels content divs or parse flat tbody
- 6-7 column mapping: Name | Date | Duration | Agenda | Minutes | Video [| MP4]
- Multiple date formats: `MM / DD / YYYY` (with `&nbsp;`), `Mon DD, YYYY`
- No hidden epoch — sort by parsed date

### Runner CLI

```
python scripts/ingest.py --source novato-city-council
python scripts/ingest.py --source marin-county-bos
python scripts/ingest.py --all
```

The runner:
1. Reads `registry/sources.yaml`
2. Filters to the requested source(s)
3. Instantiates the appropriate adapter class
4. Calls `adapter.capture()`
5. Writes the returned dict to the extracted JSON path
6. Prints a summary (meetings found, artifacts extracted, errors)

When running `--all`, the runner inserts a 2-second delay between sources to avoid hammering Granicus.

### Output Format

The extracted JSON matches the structure of existing captures where possible, with fixes identified in review:

```json
{
  "capture_id": "novato-city-council__2026-04-14",
  "source_id": "novato-city-council",
  "adapter": "granicus",
  "variant": "modern",
  "captured_at": "2026-04-14T18:30:00Z",
  "url": "https://novato.granicus.com/ViewPublisher.php?view_id=7",
  "jurisdiction_id": "place-novato",
  "institution_id": "org-novato-city-council",
  "raw_artifact": "data/raw/novato-city-council/2026-04-14/source.html",
  "meeting_count": 250,
  "artifact_counts": {
    "agenda": 230,
    "minutes": 220,
    "video": 200
  },
  "meetings": [
    {
      "meeting_id": "meeting-novato-city-council-12345",
      "date": "2024-01-09",
      "title": "Regular City Council Meeting",
      "meeting_type": "regular",
      "institution_id": "org-novato-city-council",
      "artifacts": {
        "agenda": {"available": true, "url": "https://novato.granicus.com/..."},
        "minutes": {"available": true, "url": "https://novato.granicus.com/..."},
        "video": {"available": true, "url": "https://novato.granicus.com/..."}
      },
      "source_row_number": 1,
      "clip_id": "12345"
    }
  ],
  "record_refs": [
    {
      "id": "record-novato-city-council-meeting-page-2026-04-14",
      "record_type": "meeting_archive_page",
      "source_id": "novato-city-council",
      "artifact_path": "data/raw/novato-city-council/2026-04-14/source.html",
      "captured_at": "2026-04-14T18:30:00Z"
    }
  ],
  "errors": []
}
```

**Key format decisions (from review):**
- `capture_id` at envelope level (`{source_id}__{date}`) — anchors the provenance chain
- `institution_id` at envelope level — validates all meetings belong to expected institution
- Artifacts use `{available: bool, url: str|null}` objects — matches existing capture format
- `meeting_id` uses institution slug + clip_id (`meeting-novato-city-council-12345`) — compatible with existing ID conventions, avoids the date-first format that would clash with existing graph
- `record_refs` section scaffolds a Record node for the captured archive page — provides the evidence link for downstream normalization
- `variant` field records which parser was used — useful for debugging

## 6. Known Risks and Mitigations

- **Re-capture overwrites.** Each `--all` run re-fetches and re-writes the full extracted JSON unconditionally. If manual corrections were made to a prior extract, they will be lost. Mitigation: raw HTML is always preserved with a date-stamped directory, so the data can be re-extracted. Incremental capture is a future optimization.
- **Rate limiting.** Granicus is a shared government platform. The runner inserts a 2-second delay between sources when running `--all`. Individual adapters should not make rapid sequential HTTP requests.
- **Template drift.** Granicus may update their templates, breaking either parser. Mitigation: tests use saved HTML fixtures, so regressions are caught immediately. Live smoke tests validate against real pages.

## 7. What This Doesn't Do

- **No normalization.** The adapter produces structured capture output. Turning that into normalized bundles and loading into Neo4j is a separate step.
- **No identity resolution.** The adapter uses the `institution_id` and `jurisdiction_id` from config. It doesn't resolve actors, committees, or other entities.
- **No scheduling.** The `schedule` field in the registry is informational. Cron/automation comes later.
- **No PDF/document download.** The adapter extracts artifact *URLs* but doesn't download PDFs, packets, or minutes documents. Document capture is a separate pipeline step.
- **No incremental updates.** Each run captures the full archive page. Diffing against prior captures to find new meetings is a future optimization.

## 8. Success Criteria

1. `python scripts/ingest.py --source marin-county-bos` produces output equivalent to the existing `capture_marin_county_bos_archive.py` script (legacy variant auto-detected)
2. `python scripts/ingest.py --source novato-city-council` captures Novato council meetings (modern variant auto-detected) without any Novato-specific code
3. `python scripts/ingest.py --source sausalito-city-council` captures Sausalito council meetings (modern variant auto-detected) without any Sausalito-specific code
4. All three outputs have: capture_id, meeting dates, titles, types, artifact URLs in `{available, url}` format, and a record_refs section
5. Adding a fourth Granicus source requires only a new YAML entry
6. The adapter correctly detects legacy vs modern template and uses the appropriate parser

## 9. Testing Strategy

- **Saved HTML fixtures** from all three Granicus instances (captured once, committed to repo under `tests/fixtures/`)
- Unit tests for variant detection (legacy vs modern)
- Unit tests for legacy parser: year section extraction, 9-column mapping, 2-digit date parsing, epoch span extraction
- Unit tests for modern parser: TabbedPanels/flat tbody handling, 6-7 column mapping, multi-format date parsing
- Unit tests for shared logic: row extraction, artifact URL parsing, meeting classification
- Integration test: capture from saved HTML fixture (no live HTTP), verify full output structure matches expected
- Live smoke test: run against real Granicus URLs, verify meeting counts are in reasonable ranges (BOS ~300+, Novato ~250+, Sausalito ~200+)
