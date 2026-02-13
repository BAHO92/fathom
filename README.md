# fathom

Historical source crawler for Claude Code — unified JSONL v3.1 collection from Korean classical databases.

[한국어](README.ko.md)

## Supported Databases

| DB | Name | Period | Selectors |
|----|------|--------|-----------|
| sillok | Joseon Wangjo Sillok (朝鮮王朝實錄) | Joseon | query, work_scope, ids |
| sjw | Seungjeongwon Ilgi (承政院日記) | Joseon | query, time_range, work_scope, ids |
| itkc | ITKC Classical Texts DB (韓國古典綜合DB) | Joseon | query, work_scope, ids |

## Installation

### Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/BAHO92/fathom/main/install.sh | bash
```

### Manual Install

```bash
git clone https://github.com/BAHO92/fathom.git ~/.claude/skills/fathom
pip3 install requests beautifulsoup4 lxml pyyaml
```

## Quick Start

After installation, use natural language in Claude Code:

```
"Search '송시열' in Sillok"
"Collect Seungjeongwon Ilgi, Hyeonjong year 3"
"Crawl full collection ITKC_MO_0367A"
```

## How It Works

1. **Intent Parsing** — Natural language → DB + selector + parameters
2. **Preflight** — Count check + user confirmation
3. **Crawl + Report** — Execute and generate JSONL v3.1 bundle

---

## User Scenarios

Fathom supports four selector types (A–D). Each maps to a different research workflow.

### Scenario A — Keyword Search (`query`)

Full-text keyword search across an entire database. Supports single or comma-separated multiple keywords with automatic deduplication.

**Supported DBs**: sillok, sjw, itkc

| Parameter | Required | Description |
|-----------|----------|-------------|
| `keywords` | ✅ | Search terms. Comma-separated for multiple (e.g. `"송시열,허목"`) |
| `layer` | | `"original"` / `"translation"` / omit for both (sillok only) |
| `reign` | | Filter results by reign name (sillok only) |
| `field` | | `"all"` (default) / `"title"` / `"content"` (sjw only) |
| `limit` | | Max articles to crawl (applies early — stops pagination once reached) |

**Examples**:

```python
# Sillok: search "송시열" in original text, limited to 50 articles
{"db": "sillok", "type": "query", "keywords": "송시열", "layer": "original", "limit": 50}

# SJW: search "허목" in title field only
{"db": "sjw", "type": "query", "keywords": "허목", "options": {"field": "title"}, "limit": 20}

# ITKC: multi-keyword search across classical texts
{"db": "itkc", "type": "query", "keywords": "송시열,허목"}

# Natural language
"실록에서 '송시열' 검색해줘"
"승정원일기에서 '허목' 제목 검색, 20건만"
```

**Output**: Each result includes metadata (title, date, source), translation, original text, footnotes, and categories.

---

### Scenario B — Date Range (`time_range`)

Browse articles within a calendar date range by reign name and year. Useful for collecting all records of a specific period.

**Supported DBs**: sjw

| Parameter | Required | Description |
|-----------|----------|-------------|
| `reign` | ✅ | King's reign name in Korean (e.g. `"현종"`, `"숙종"`) |
| `year_from` | | Start year (0 = accession year). Omit for full reign |
| `year_to` | | End year. Omit for same as `year_from` |
| `limit` | | Max articles (early limit — stops day-by-day collection once reached) |

**Examples**:

```python
# SJW: Hyeonjong year 1 only
{"db": "sjw", "type": "time_range", "reign": "현종", "year_from": 1, "year_to": 1, "limit": 50}

# SJW: Sukjong years 3 through 5
{"db": "sjw", "type": "time_range", "reign": "숙종", "year_from": 3, "year_to": 5}

# SJW: entire accession year (year 0)
{"db": "sjw", "type": "time_range", "reign": "인조", "year_from": 0, "year_to": 0}

# Natural language
"승정원일기 현종 1년 수집해줘"
"승정원일기 숙종 3년부터 5년까지"
```

**How it works**: Collects month list → filters by year range → iterates days → collects article IDs → crawls each article. With `limit`, stops as soon as enough article IDs are gathered.

---

### Scenario C — Full Collection (`work_scope`)

Crawl an entire work (문집 collection) or reign. For large scopes, use `segment` to narrow the range.

**Supported DBs**: sillok (limited), sjw, itkc

| Parameter | Required | Description |
|-----------|----------|-------------|
| `work_kind` | ✅ | `"collection"` (itkc) / `"reign"` (sjw, sillok) |
| `work_id` | ✅ | Collection ID (e.g. `"ITKC_MO_0367A"`) or reign name (e.g. `"현종"`) |
| `segment` | | Year range for SJW (e.g. `"5"` or `"5-10"`), volume range for sillok (e.g. `"1-5"`) |
| `limit` | | Max articles (early limit) |

**Examples**:

```python
# ITKC: entire Songja Daejeon (송자대전)
{"db": "itkc", "type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A"}

# ITKC: with limit
{"db": "itkc", "type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A", "limit": 100}

# SJW: Hyeonjong entire reign
{"db": "sjw", "type": "work_scope", "work_kind": "reign", "work_id": "현종"}

# SJW: Hyeonjong years 5-10 only (using segment)
{"db": "sjw", "type": "work_scope", "work_kind": "reign", "work_id": "현종", "segment": "5-10", "limit": 50}

# Natural language
"문집 ITKC_MO_0367A 전체 수집해줘"
"승정원일기 현종 전체, 5년~10년만"
```

**Note**: SJW `work_scope` without segment collects the entire reign period, which can take significant time for long reigns (15+ years). Always use `segment` and/or `limit` for practical usage.

---

### Scenario D — Article IDs (`ids`)

Crawl specific articles by ID. Accepts a list of IDs directly or a file (TSV/JSON). Invalid IDs are isolated to `failed.jsonl`.

**Supported DBs**: sillok, sjw, itkc

| Parameter | Required | Description |
|-----------|----------|-------------|
| `id_list` | ✅* | Array of article ID strings |
| `source_file` | ✅* | Path to TSV/JSON file containing IDs |

*One of `id_list` or `source_file` is required.

**ID formats by DB**:

| DB | Format | Example |
|----|--------|---------|
| sillok | `{king_code}_{YYMM}{DD}{seq}_{NNN}` | `wpa_12112025_002` |
| sjw | `SJW-{king}{YYMM}{DD}{seq}-{NNN}{NN}` | `SJW-C01010020-00100` |
| itkc | `ITKC_MO_{NNNN}A_{NNN}_{NNNN}` | `ITKC_MO_0367A_001_0010` |

**Examples**:

```python
# Sillok: specific article IDs
{"db": "sillok", "type": "ids", "id_list": ["wpa_12112025_002", "wpa_12112025_003"]}

# SJW: from a file
{"db": "sjw", "type": "ids", "source_file": "/path/to/ids.tsv"}

# ITKC: mixed valid + invalid (invalid → failed.jsonl)
{"db": "itkc", "type": "ids", "id_list": ["ITKC_MO_0367A_001_0010", "INVALID_ID"]}

# Natural language
"실록 기사 wpa_12112025_002 수집해줘"
"이 ID 목록으로 승정원일기 수집해줘: [파일 경로]"
```

**Error handling**: Each DB handles invalid IDs differently at the site level (sillok→404, sjw→empty page, itkc→500), but fathom normalizes all cases — invalid articles are written to `failed.jsonl` with an error description.

---

## Output Format

```
~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
├── articles.jsonl      # One article per line (JSONL v3.1)
├── provenance.json     # Reproducibility metadata
└── failed.jsonl        # Failed records with error info
```

<details>
<summary>JSONL v3.1 article schema (abbreviated)</summary>

```json
{
  "schema_version": "3.1",
  "id": "wpa_12112025_002",
  "source": "sillok",
  "metadata": {
    "title": "이태연·정태제·조계원 등에게 관직을 제수하다",
    "sillok_name": "인조실록",
    "volume": 44,
    "date": {
      "reign": "인조", "year": 21, "month": 12, "day": 25,
      "ganzhi": "乙酉", "article_num": 2
    },
    "category": [{"major": "註 082", "minor": null}],
    "page_info": {"taebaek": "44책 44권 46장 B면", "gukpyeon": "35책 170면"}
  },
  "translation": {"paragraphs": ["이태연(李泰淵)을 대교로..."], "persons": []},
  "original": {"paragraphs": ["○以李泰淵爲待敎..."], "persons": []},
  "footnotes": [{"footnote_id": "1", "term": "...", "definition": "..."}],
  "has_translation": true,
  "url": "https://sillok.history.go.kr/id/wpa_12112025_002",
  "crawled_at": "2026-02-13T03:13:00+00:00"
}
```

</details>

## Configuration

On first run, fathom guides you through setup:
- Storage path (default: `~/DB`)
- Active databases
- Appendix field selection

Settings saved to `config.json`. Edit directly or delete to reconfigure.

## Development

```bash
python3 -m pytest tests/ -v                    # All tests (142)
python3 -m pytest tests/test_engine.py -v      # Engine only
python3 -m pytest tests/test_sillok.py -v      # Adapter tests
```

## Project Structure

```
fathom/
├── SKILL.md              # Claude skill definition
├── registry.yaml         # Database registry
├── config.default.json   # Default configuration
├── engine/               # Core engine
│   ├── workflow.py       # 3-stage workflow
│   ├── selector.py       # Selector schema
│   ├── config.py         # Configuration
│   ├── output.py         # JSONL output
│   ├── provenance.py     # Provenance metadata
│   └── onboarding.py     # First-run setup
├── dbs/                  # Database adapters
│   ├── base.py           # Abstract base
│   ├── sillok/           # Joseon Sillok
│   ├── sjw/              # Seungjeongwon Ilgi
│   └── itkc/             # ITKC Munzip
└── tests/
```

## License

MIT — see [LICENSE](LICENSE)

## Author

BAHO ([GitHub](https://github.com/BAHO92))
