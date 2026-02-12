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
"실록에서 '송시열' 검색해줘"
"승정원일기 현종 3년 수집해줘"
"문집 ITKC_MO_0367A 전체 수집해줘"
```

## How It Works

1. **Intent Parsing** — Natural language to DB + selector + parameters
2. **Preflight** — Count check + user confirmation
3. **Crawl + Report** — Execute and generate JSONL v3.1 bundle

## Output Format

```
~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
├── articles.jsonl      # One article per line
├── provenance.json     # Reproducibility metadata
└── failed.jsonl        # Failed records
```

## Configuration

On first run, fathom guides you through setup:
- Storage path (default: `~/DB`)
- Active databases
- Appendix field selection

Settings saved to `config.json`. Edit directly or delete to reconfigure.

## Selectors

| Type | Description | Example |
|------|-------------|---------|
| query | Keyword search | "실록에서 '허목' 검색" |
| time_range | Date range (SJW only) | "승정원일기 인조 1년~5년" |
| work_scope | Full collection/reign | "문집 ITKC_MO_0367A 전체" |
| ids | Article ID list | Provide TSV/JSON file or ID list |

## Development

```bash
python3 -m pytest tests/ -v                    # All tests
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
