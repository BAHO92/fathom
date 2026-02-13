# fathom — Historical Source Collection Tool

[한국어](README.ko.md)

> **fathom** is a unit for measuring the depth of the sea.
> This tool does the same — it draws up historical sources from the depths of Korean classical databases.

fathom is a **unified historical source crawler** installed as a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill. It searches and collects primary sources from the Joseon Wangjo Sillok, Seungjeongwon Ilgi, and ITKC Classical Texts DB, outputting structured JSONL files.

**Target users**: Humanities researchers who need systematic collection of Joseon-era primary sources

**Key features**:
- Natural language requests — "Search '송시열' in Sillok"
- 3 databases unified — Sillok, Seungjeongwon Ilgi, Classical Texts (Munzip)
- Structured output — per-article metadata + original text + translation + footnotes
- Reproducible collection — search conditions and results recorded in provenance.json

### Supported Databases

| DB | Name | Site |
|----|------|------|
| sillok | Joseon Wangjo Sillok (朝鮮王朝實錄) | [sillok.history.go.kr](https://sillok.history.go.kr) |
| sjw | Seungjeongwon Ilgi (承政院日記) | [sjw.history.go.kr](https://sjw.history.go.kr) |
| itkc | ITKC Classical Texts DB (韓國古典綜合DB) | [db.itkc.or.kr](https://db.itkc.or.kr) |

---

## Installation

### Prerequisites

fathom is a Claude Code skill, so Claude Code must be installed first.

| Program | Minimum Version | How to Check (type in terminal) |
|---------|-----------------|----------------------------------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | — | `claude --version` |
| Python | 3.8+ | `python3 --version` |

> **How to open a terminal**
> - **Mac**: `Cmd + Space` → type "Terminal" → open
> - **Windows**: `Win + R` → type `cmd` → OK
> - **Linux**: `Ctrl + Alt + T`

If not yet installed:
- **Claude Code**: Follow the [official installation guide](https://docs.anthropic.com/en/docs/claude-code).
- **Python**: Download from [python.org/downloads](https://www.python.org/downloads/). Mac usually has it pre-installed.

### Quick Install (Recommended)

Open a terminal and paste the following line, then press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/BAHO92/fathom/main/install.sh | bash
```

When installation completes, you'll see:

```
=== Installation complete ===
fathom installed at: ~/.claude/skills/fathom
```

### Manual Install

If the quick install doesn't work, run these two lines in order:

```bash
git clone https://github.com/BAHO92/fathom.git ~/.claude/skills/fathom
pip3 install requests beautifulsoup4 lxml pyyaml
```

### Update

To update an existing installation, just run the quick install command again. It detects the existing installation and updates automatically.

---

## Initial Setup

After installing fathom, **the first time you request a crawl**, Claude will automatically guide you through setup. No need to create config files manually.

### Setup Flow

#### Step 1: Storage Path

```
Looks like this is your first time using fathom! Let's do a quick setup.

Please specify where to save collected data.
(Default: ~/DB)
Press Enter to use the default.
```

This is the folder where collected data will be stored. The default `~/DB` creates a `DB` folder under your home directory. Enter a custom path if you prefer.

#### Step 2: Active Databases

```
Select which databases to enable. (Default: all)
  - sillok: Joseon Wangjo Sillok
  - sjw: Seungjeongwon Ilgi
  - itkc: ITKC Classical Texts DB (Munzip)

Enter comma-separated values. (e.g., sillok, sjw)
Press Enter to enable all.
```

You can select specific DBs if needed. In most cases, press Enter to enable all.

#### Step 3: Appendix Fields

```
Would you like to configure appendix fields?

Appendix fields are supplementary data for rendering/navigation.
By default, none are collected. You can select only the ones you need.

[Joseon Wangjo Sillok]
  ◈ day_articles: List of articles from the same day (for navigation)
  ◈ prev_article_id: Previous article ID
  ◈ next_article_id: Next article ID
  ◈ place_annotations: Place name annotations (some articles)
  ◈ book_annotations: Book title annotations (some articles)

[Seungjeongwon Ilgi]
  ◈ person_annotations: Person/title markup from SJW pages
  ◈ day_total_articles: Total article count for the same day

[ITKC Classical Texts DB (Munzip)]
  ◈ page_markers: Original text page break markers (for rendering)
  ◈ indent_levels: Original/translation indent levels (for rendering)

Press Enter to collect core fields only (no appendix).
```

Appendix fields are supplementary data beyond the article body and metadata. For typical text analysis research, **pressing Enter to skip is fine**. Select specific fields only if you need to build navigation UIs or person name databases.

#### Setup Complete

```
Setup complete!

  Storage path: ~/DB
  Active DBs: Joseon Wangjo Sillok, Seungjeongwon Ilgi, ITKC Classical Texts DB (Munzip)
  Appendix: None (core fields only)

Settings saved to config.json.
You can start crawling now!
```

> **To change settings**: Edit `config.json` in the fathom install folder (`~/.claude/skills/fathom/`), or delete it to restart the setup on next run. You can also just ask Claude: "Change my fathom settings."

---

## Usage

Once installation and setup are done, make requests in natural language from Claude Code:

```
"Search '송시열' in Sillok"
"Collect Seungjeongwon Ilgi, Hyeonjong year 1"
"Crawl full collection ITKC_MO_0367A"
```

### How It Works

1. **Intent Parsing** — Extracts target DB + selector + parameters from natural language
2. **Preflight** — Checks count and asks for user confirmation
3. **Crawl + Report** — Executes crawling and generates the result bundle

For example, saying "Search '송시열' in Sillok":

```
Found approximately 2,550 results for '송시열' in Joseon Wangjo Sillok.
Proceed with collection?
```

After confirmation, collection begins. On completion:

```
[Collection Complete]
- Target: Joseon Wangjo Sillok
- Result: 2,550 succeeded, 0 failed
- Bundle: ~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
```

---

## User Scenarios

fathom supports four collection methods (A–D).

### Scenario A — Keyword Search (`query`)

Full-text keyword search across an entire database. Supports single or comma-separated multiple keywords with automatic deduplication.

**Supported DBs**: sillok, sjw, itkc

| Parameter | Required | Description |
|-----------|----------|-------------|
| `keywords` | ✅ | Search terms. Comma-separated for multiple (e.g. `"송시열,허목"`) |
| `layer` | | `"original"` / `"translation"` / omit for both. Sillok has separate tabs for original text (Classical Chinese) and translation (Korean), so you can choose which to search. (sillok only) |
| `reign` | | Filter by reign name (e.g. `"현종"`) (sillok, sjw) |

> Seungjeongwon Ilgi also supports specialized search fields such as attendance, weather, person names, and place names. When you make a request in natural language, Claude will select the appropriate field automatically.

**Natural language examples**:
```
"Search '송시열' in Sillok"
"Search '허목' by title in Seungjeongwon Ilgi, 20 articles only"
"Search '송시열,허목' in classical texts"
```

**Selector examples**:
```python
# Sillok: search "송시열" in original text only
{"db": "sillok", "type": "query", "keywords": "송시열", "layer": "original"}

# SJW: search "허목" in title field only
{"db": "sjw", "type": "query", "keywords": "허목", "options": {"field": "title"}}

# ITKC: multi-keyword search across classical texts
{"db": "itkc", "type": "query", "keywords": "송시열,허목"}
```

---

### Scenario B — Date Range (`time_range`)

Browse articles within a calendar date range by reign name and year. Useful for collecting all records of a specific period.

**Supported DBs**: sjw

| Parameter | Required | Description |
|-----------|----------|-------------|
| `reign` | ✅ | King's reign name in Korean (e.g. `"현종"`, `"숙종"`) |
| `year_from` | | Start year (0 = accession year). Omit for full reign |
| `year_to` | | End year. Omit for same as `year_from` |

**Natural language examples**:
```
"Collect Seungjeongwon Ilgi, Hyeonjong year 1"
"Seungjeongwon Ilgi, Sukjong years 3 through 5"
"Collect Seungjeongwon Ilgi, Injo accession year"
```

**Selector examples**:
```python
# Hyeonjong year 1 only
{"db": "sjw", "type": "time_range", "reign": "현종", "year_from": 1, "year_to": 1}

# Sukjong years 3–5
{"db": "sjw", "type": "time_range", "reign": "숙종", "year_from": 3, "year_to": 5}

# Injo accession year (year 0)
{"db": "sjw", "type": "time_range", "reign": "인조", "year_from": 0, "year_to": 0}
```

**How it works**: Collects month list → filters by year range → iterates days → collects article IDs → crawls each article.

---

### Scenario C — Full Collection (`work_scope`)

Crawl an entire work (문집 collection) or reign. For large scopes, use `segment` to narrow the range.

**Supported DBs**: sillok (limited), sjw, itkc

| Parameter | Required | Description |
|-----------|----------|-------------|
| `work_kind` | ✅ | `"collection"` (itkc) / `"reign"` (sjw, sillok) |
| `work_id` | ✅ | Collection ID (e.g. `"ITKC_MO_0367A"`) or reign name (e.g. `"현종"`) |
| `segment` | | Year range for SJW (e.g. `"5"` or `"5-10"`), volume range for sillok (e.g. `"1-5"`) |

**Natural language examples**:
```
"Crawl full collection ITKC_MO_0367A"
"Collect entire Seungjeongwon Ilgi for Hyeonjong, years 5–10 only"
```

**Selector examples**:
```python
# ITKC: entire Songja Daejeon (송자대전)
{"db": "itkc", "type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A"}

# SJW: Hyeonjong years 5-10 only (using segment)
{"db": "sjw", "type": "work_scope", "work_kind": "reign", "work_id": "현종", "segment": "5-10"}
```


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

| DB | Example |
|----|---------|
| sillok | `wpa_12112025_002` |
| sjw | `SJW-C01010020-00100` |
| itkc | `ITKC_MO_0367A_001_0010` |

**Natural language examples**:
```
"Collect Sillok article wpa_12112025_002"
"Collect from Seungjeongwon Ilgi using this ID list: [file path]"
```

**Selector examples**:
```python
# Sillok: specific article IDs
{"db": "sillok", "type": "ids", "id_list": ["wpa_12112025_002", "wpa_12112025_003"]}

# SJW: from a file
{"db": "sjw", "type": "ids", "source_file": "/path/to/ids.tsv"}
```

**Error handling**: Each DB handles invalid IDs differently at the site level (sillok→404, sjw→empty page, itkc→500), but fathom normalizes all cases — invalid articles are written to `failed.jsonl` with an error description.

---

---

# Reference

## Output Bundle Structure

When crawling completes, a **bundle folder** is created at the configured storage path:

```
~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
├── articles.jsonl      # Collected articles (one JSON per line)
├── provenance.json     # Collection conditions, tool version, stats (for reproducibility)
└── failed.jsonl        # Failed records (ID, error reason, retry count)
```

| File | Description |
|------|-------------|
| `articles.jsonl` | Successfully collected articles. JSONL v3.1 schema. |
| `provenance.json` | Metadata for reproducing this collection — search conditions, tool version, timestamps, success/failure stats. |
| `failed.jsonl` | List of failed articles. Each entry includes article ID, error message, and retry count. |

---

## JSONL v3.1 Schema

Each article consists of **Core fields** (always collected) and **Appendix fields** (selected during setup).

### Core Fields — Common

Fields included in every article across all DBs.

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | `"3.1"` |
| `id` | string | Unique article ID (format varies by DB) |
| `source` | string | Source DB: `"sillok"` / `"sjw"` / `"munzip"` |
| `metadata` | object | Metadata (DB-specific structure — see below) |
| `original` | object | Original text (Classical Chinese) |
| `translation` | object | Translation (Korean) |
| `has_translation` | boolean | Whether translation exists |
| `url` | string | Article URL on the source site |
| `crawled_at` | string | Collection timestamp (ISO 8601) |
| `appendix` | object | Supplementary data (may be empty depending on settings) |

### Core Fields — DB-Specific Metadata

<details>
<summary><b>Joseon Wangjo Sillok (sillok)</b></summary>

```json
{
  "metadata": {
    "title": "이태연·정태제·조계원 등에게 관직을 제수하다",
    "sillok_name": "인조실록",
    "volume": 44,
    "date": {
      "reign": "인조",
      "year": 21,
      "month": 12,
      "day": 25,
      "ganzhi": "乙酉",
      "article_num": 2,
      "total_articles": null
    },
    "western_year": null,
    "chinese_era": null,
    "category": [{"major": "註 082", "minor": null}],
    "page_info": {
      "taebaek": "44책 44권 46장 B면",
      "gukpyeon": "35책 170면"
    }
  },
  "original": {
    "paragraphs": ["○以李泰淵爲待敎..."],
    "persons": []
  },
  "translation": {
    "paragraphs": ["이태연(李泰淵)을 대교로..."],
    "persons": []
  },
  "footnotes": [
    {"footnote_id": "1", "term": "동기(同氣)", "definition": "송시열의 형을 말함."}
  ]
}
```

| Field | Description |
|-------|-------------|
| `sillok_name` | Sillok name (e.g., "인조실록") |
| `volume` | Volume number |
| `date.reign` | Reign name |
| `date.year/month/day` | Reign year / month / day |
| `date.ganzhi` | Sexagenary cycle date (e.g., "乙酉") |
| `date.article_num` | Article sequence number for that day |
| `category` | Classification (major/minor) |
| `page_info` | Taebaek / Gukpyeon edition page references |
| `footnotes` | Annotations (term + definition) |

</details>

<details>
<summary><b>Seungjeongwon Ilgi (sjw)</b></summary>

```json
{
  "metadata": {
    "title": "비변사에서 아뢰기를...",
    "date": {
      "reign": "현종",
      "year": 1,
      "month": 1,
      "day": 2,
      "ganzhi": "甲子",
      "article_num": 1,
      "total_articles": null
    },
    "western_year": 1660,
    "chinese_era": "順治 17年",
    "source_info": {
      "book_num": 145,
      "book_num_talcho": 0,
      "description": "인조 27년 ~ 현종 1년 1월"
    }
  },
  "original": {
    "paragraphs": ["備邊司啓曰..."]
  },
  "translation": {
    "paragraphs": ["비변사에서 아뢰기를..."],
    "title": null,
    "footnotes": [],
    "person_index": [],
    "place_index": []
  },
  "itkc_data_id": ""
}
```

| Field | Description |
|-------|-------------|
| `date.reign/year/month/day/ganzhi` | Same structure as Sillok |
| `western_year` | Western calendar year (e.g., 1660) |
| `chinese_era` | Chinese era name (e.g., "順治 17年") |
| `source_info.book_num` | Book number |
| `source_info.book_num_talcho` | Talcho edition book number |
| `itkc_data_id` | ITKC cross-reference ID |

</details>

<details>
<summary><b>ITKC Classical Texts DB — Munzip (itkc/munzip)</b></summary>

```json
{
  "metadata": {
    "dci": null,
    "title": "答金叔涵[光煜]問目",
    "title_ko": "김숙함(金光煜)의 문목에 답하다",
    "seo_myeong": "송자대전",
    "seo_myeong_hanja": "宋子大全",
    "gwon_cha": "제108권",
    "mun_che": "잡저",
    "mun_che_category": "잡저",
    "author": {
      "name": "송시열",
      "name_hanja": "宋時烈",
      "birth_year": 1607,
      "death_year": 1689
    },
    "item_id": "ITKC_MO",
    "seo_ji_id": "ITKC_MO_0367A",
    "translator": "송시열문집번역위원회"
  },
  "original": {
    "title": "答金叔涵[光煜]問目",
    "sections": [
      {"index": 0, "lines": ["問禮疑..."], "annotations": []}
    ]
  },
  "translation": {
    "title": "김숙함(金光煜)의 문목에 답하다",
    "paragraphs": [
      {"index": 0, "text": "예의에 대해 의문되는 것을...", "footnote_markers": []}
    ],
    "footnotes": []
  }
}
```

| Field | Description |
|-------|-------------|
| `title` / `title_ko` | Classical Chinese title / Korean title |
| `seo_myeong` | Work name (e.g., "송자대전") |
| `gwon_cha` | Volume (e.g., "제108권") |
| `mun_che` | Literary form (e.g., "잡저", "서", "소") |
| `author` | Author info (name, hanja, birth/death years) |
| `seo_ji_id` | Bibliographic ID (e.g., "ITKC_MO_0367A") |
| `translator` | Translator / translation committee |
| `original.sections` | Original text — by section, each with line array |
| `translation.paragraphs` | Translation — by paragraph (index + text) |

</details>

---

### Appendix Fields — By DB

Appendix fields are **supplementary data** selected during initial setup. By default, none are collected.

#### Sillok

| Field | Description |
|-------|-------------|
| `day_articles` | List of articles from the same day (for navigation) |
| `prev_article_id` | Previous article ID |
| `next_article_id` | Next article ID |
| `place_annotations` | Place name annotations |
| `book_annotations` | Book title annotations |

#### Seungjeongwon Ilgi

| Field | Description |
|-------|-------------|
| `person_annotations` | Person/title markup |
| `day_total_articles` | Total article count for the same day |

#### Munzip (ITKC)

| Field | Description |
|-------|-------------|
| `page_markers` | Original text page break markers |
| `indent_levels` | Original/translation indent levels |

---

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
