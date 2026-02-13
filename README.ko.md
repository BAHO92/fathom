# fathom — 역사 사료 통합 수집 도구

Claude Code 스킬로 설치하여 사용하는 JSONL v3.1 통합 크롤러입니다.

[English](README.md)

> 이 도구는 인문학 연구자를 위해 설계되었습니다. Claude Code 사용 경험이 있다고 전제합니다.

## 지원 데이터베이스

| DB | 이름 | 시대 | 셀렉터 |
|----|------|------|--------|
| sillok | 조선왕조실록 (朝鮮王朝實錄) | 조선 | query, work_scope, ids |
| sjw | 승정원일기 (承政院日記) | 조선 | query, time_range, work_scope, ids |
| itkc | 한국고전종합DB — 문집 (韓國古典綜合DB) | 조선 | query, work_scope, ids |

## 설치

### 사전 준비

fathom을 설치하려면 아래 두 가지가 컴퓨터에 설치되어 있어야 합니다.

| 프로그램 | 최소 버전 | 확인 방법 (터미널에 입력) |
|----------|-----------|--------------------------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | — | `claude --version` |
| Python | 3.8 이상 | `python3 --version` |

> **터미널 여는 법**
> - **Mac**: `Cmd + Space` → "터미널" 검색 → 열기
> - **Windows**: `Win + R` → `cmd` 입력 → 확인
> - **Linux**: `Ctrl + Alt + T`

아직 설치되지 않은 경우:

- **Claude Code**: [공식 설치 안내](https://docs.anthropic.com/en/docs/claude-code)를 따라 설치합니다.
- **Python**: [python.org/downloads](https://www.python.org/downloads/)에서 다운로드합니다. Mac에는 보통 기본 설치되어 있습니다.

### 자동 설치 (권장)

터미널을 열고 아래 한 줄을 복사하여 붙여넣은 뒤 Enter를 누릅니다:

```bash
curl -fsSL https://raw.githubusercontent.com/BAHO92/fathom/main/install.sh | bash
```

설치가 완료되면 아래와 같은 메시지가 나타납니다:

```
=== Installation complete ===
fathom installed at: ~/.claude/skills/fathom
```

이후 Claude Code를 열고 바로 사용할 수 있습니다.

### 수동 설치

자동 설치가 동작하지 않는 경우, 터미널에서 아래 두 줄을 순서대로 실행합니다:

```bash
git clone https://github.com/BAHO92/fathom.git ~/.claude/skills/fathom
pip3 install requests beautifulsoup4 lxml pyyaml
```

### 업데이트

이미 설치된 상태에서 최신 버전으로 업데이트하려면, 자동 설치 명령을 다시 실행하면 됩니다. 기존 설치를 감지하여 자동으로 업데이트합니다.

### 설치 확인

Claude Code를 열고 아래처럼 입력해 보세요:

```
"실록에서 '송시열' 검색해줘"
```

fathom이 응답하면 설치가 정상적으로 된 것입니다.

## 사용 방법

설치 후 Claude Code에서 자연어로 요청하시면 됩니다:

```
"실록에서 '송시열' 검색해줘"
"승정원일기 현종 3년 수집해줘"
"문집 ITKC_MO_0367A 전체 수집해줘"
```

## 작동 방식

1. **의도 파싱** — 자연어에서 대상 DB + 셀렉터 + 파라미터를 추출합니다
2. **Preflight** — 건수를 확인하고 사용자에게 확인을 요청합니다
3. **수집 + 리포트** — 크롤링을 실행하고 JSONL v3.1 번들을 생성합니다

---

## 사용 시나리오

fathom은 네 가지 셀렉터 타입(A–D)을 지원합니다. 각각 다른 연구 워크플로우에 대응합니다.

### 시나리오 A — 키워드 검색 (`query`)

데이터베이스 전체에 대한 전문 키워드 검색입니다. 쉼표로 구분하여 복수 키워드를 지정하면 자동 중복 제거됩니다.

**지원 DB**: sillok, sjw, itkc

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `keywords` | ✅ | 검색어. 쉼표 구분으로 복수 가능 (예: `"송시열,허목"`) |
| `layer` | | `"original"` / `"translation"` / 생략 시 양쪽 모두 (실록만) |
| `reign` | | 왕대별 필터링 (실록만) |
| `field` | | `"all"` (기본) / `"title"` / `"content"` (승정원일기만) |
| `limit` | | 최대 수집 건수 (조기 적용 — 페이지네이션 중 도달 시 즉시 중단) |

**예시**:

```python
# 실록: "송시열" 원문 검색, 50건 제한
{"db": "sillok", "type": "query", "keywords": "송시열", "layer": "original", "limit": 50}

# 승정원일기: "허목" 제목 필드만 검색
{"db": "sjw", "type": "query", "keywords": "허목", "options": {"field": "title"}, "limit": 20}

# ITKC: 문집에서 복수 키워드 검색
{"db": "itkc", "type": "query", "keywords": "송시열,허목"}

# 자연어
"실록에서 '송시열' 검색해줘"
"승정원일기에서 '허목' 제목 검색, 20건만"
```

**결과**: 각 기사에 메타데이터(제목, 날짜, 출처), 번역문, 원문, 주석, 분류 정보가 포함됩니다.

---

### 시나리오 B — 날짜 범위 (`time_range`)

왕대명과 연도를 지정하여 해당 기간의 기사를 일자별로 수집합니다. 특정 시기의 전체 기록을 모을 때 유용합니다.

**지원 DB**: sjw

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `reign` | ✅ | 왕대명 (예: `"현종"`, `"숙종"`) |
| `year_from` | | 시작 연도 (0 = 즉위년). 생략 시 전체 |
| `year_to` | | 종료 연도. 생략 시 `year_from`과 동일 |
| `limit` | | 최대 수집 건수 (조기 적용 — 일자별 수집 중 도달 시 즉시 중단) |

**예시**:

```python
# 승정원일기: 현종 1년만
{"db": "sjw", "type": "time_range", "reign": "현종", "year_from": 1, "year_to": 1, "limit": 50}

# 승정원일기: 숙종 3년~5년
{"db": "sjw", "type": "time_range", "reign": "숙종", "year_from": 3, "year_to": 5}

# 승정원일기: 인조 즉위년(0년) 전체
{"db": "sjw", "type": "time_range", "reign": "인조", "year_from": 0, "year_to": 0}

# 자연어
"승정원일기 현종 1년 수집해줘"
"승정원일기 숙종 3년부터 5년까지"
```

**동작 과정**: 월 목록 수집 → 연도 필터링 → 일자별 순회 → 기사 ID 수집 → 각 기사 크롤링. `limit` 지정 시 기사 ID 수집 단계에서 조기 종료합니다.

---

### 시나리오 C — 전체 수집 (`work_scope`)

문집 컬렉션 전체 또는 왕대 전체를 수집합니다. 대규모 범위에서는 `segment`로 범위를 좁힐 수 있습니다.

**지원 DB**: sillok (제한적), sjw, itkc

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `work_kind` | ✅ | `"collection"` (itkc) / `"reign"` (sjw, sillok) |
| `work_id` | ✅ | 컬렉션 ID (예: `"ITKC_MO_0367A"`) 또는 왕대명 (예: `"현종"`) |
| `segment` | | SJW: 연도 범위 (예: `"5"` 또는 `"5-10"`), 실록: 권 범위 (예: `"1-5"`) |
| `limit` | | 최대 수집 건수 (조기 적용) |

**예시**:

```python
# ITKC: 송자대전 전체
{"db": "itkc", "type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A"}

# ITKC: 100건만
{"db": "itkc", "type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A", "limit": 100}

# 승정원일기: 현종 전체
{"db": "sjw", "type": "work_scope", "work_kind": "reign", "work_id": "현종"}

# 승정원일기: 현종 5년~10년만 (segment 활용)
{"db": "sjw", "type": "work_scope", "work_kind": "reign", "work_id": "현종", "segment": "5-10", "limit": 50}

# 자연어
"문집 ITKC_MO_0367A 전체 수집해줘"
"승정원일기 현종 전체, 5년~10년만"
```

**참고**: SJW `work_scope`에서 segment 없이 사용하면 전체 재위 기간을 수집하므로 장기 재위(15년+)에서는 상당한 시간이 걸립니다. 실용적 사용을 위해 반드시 `segment` 및/또는 `limit`을 함께 지정하세요.

---

### 시나리오 D — 기사 ID 직접 지정 (`ids`)

특정 기사를 ID로 직접 지정하여 수집합니다. ID 배열 또는 파일(TSV/JSON)을 받습니다. 잘못된 ID는 `failed.jsonl`로 분리됩니다.

**지원 DB**: sillok, sjw, itkc

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `id_list` | ✅* | 기사 ID 문자열 배열 |
| `source_file` | ✅* | ID가 담긴 TSV/JSON 파일 경로 |

*`id_list` 또는 `source_file` 중 하나 필수.

**DB별 ID 형식**:

| DB | 형식 | 예시 |
|----|------|------|
| sillok | `{왕코드}_{YYMM}{DD}{seq}_{NNN}` | `wpa_12112025_002` |
| sjw | `SJW-{왕}{YYMM}{DD}{seq}-{NNN}{NN}` | `SJW-C01010020-00100` |
| itkc | `ITKC_MO_{NNNN}A_{NNN}_{NNNN}` | `ITKC_MO_0367A_001_0010` |

**예시**:

```python
# 실록: 특정 기사 ID
{"db": "sillok", "type": "ids", "id_list": ["wpa_12112025_002", "wpa_12112025_003"]}

# 승정원일기: 파일에서 ID 읽기
{"db": "sjw", "type": "ids", "source_file": "/path/to/ids.tsv"}

# ITKC: 유효 + 무효 ID 혼합 (무효 → failed.jsonl)
{"db": "itkc", "type": "ids", "id_list": ["ITKC_MO_0367A_001_0010", "INVALID_ID"]}

# 자연어
"실록 기사 wpa_12112025_002 수집해줘"
"이 ID 목록으로 승정원일기 수집해줘: [파일 경로]"
```

**에러 처리**: 각 DB 사이트가 잘못된 ID를 처리하는 방식은 다릅니다(실록→404, 승정원일기→빈 페이지, ITKC→500). fathom은 이를 모두 정규화하여 — 무효 기사를 `failed.jsonl`에 에러 설명과 함께 기록합니다.

---

## 출력 형식

```
~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
├── articles.jsonl      # 한 줄 = 한 기사 JSON (JSONL v3.1)
├── provenance.json     # 수집 출처 및 재현 정보
└── failed.jsonl        # 실패 기록 + 에러 정보
```

<details>
<summary>JSONL v3.1 기사 스키마 (요약)</summary>

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

## 설정

처음 실행 시 안내에 따라 설정을 진행합니다:
- 데이터 저장 경로 (기본값: `~/DB`)
- 활성화할 데이터베이스
- Appendix 필드 선택

설정은 `config.json`에 저장됩니다. 직접 수정하거나 삭제 후 다시 설정하실 수 있습니다.

## 개발

```bash
python3 -m pytest tests/ -v                    # 전체 테스트 (142건)
python3 -m pytest tests/test_engine.py -v      # 엔진 테스트
python3 -m pytest tests/test_sillok.py -v      # 어댑터 테스트
```

## 라이선스

MIT — [LICENSE](LICENSE) 참조

## 저자

BAHO ([GitHub](https://github.com/BAHO92))
