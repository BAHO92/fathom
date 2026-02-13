# fathom — 역사 사료 통합 수집 도구

[English](README.md)

> **fathom**(패덤)은 바다의 깊이를 재는 단위입니다.
> 이 도구도 같은 일을 합니다 — 역사 데이터베이스의 깊은 곳에서 사료를 길어 올립니다.

fathom은 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 스킬로 설치하여 사용하는 **역사 사료 통합 크롤러**입니다. 조선왕조실록, 승정원일기, 한국고전종합DB(문집)에서 사료를 검색하고, 구조화된 JSONL 파일로 수집합니다.

**대상 사용자**: 조선시대 1차 사료를 체계적으로 수집해야 하는 인문학 연구자

**핵심 특징**:
- 자연어로 요청 — "실록에서 '송시열' 검색해줘"
- 3개 DB 통합 지원 — 실록, 승정원일기, 문집
- 구조화된 출력 — 기사별 메타데이터 + 원문 + 번역문 + 주석
- 재현 가능한 수집 — 수집 조건·결과를 provenance.json에 기록

### 지원 데이터베이스

| DB | 이름 | 사이트 |
|----|------|--------|
| sillok | 조선왕조실록 (朝鮮王朝實錄) | [sillok.history.go.kr](https://sillok.history.go.kr) |
| sjw | 승정원일기 (承政院日記) | [sjw.history.go.kr](https://sjw.history.go.kr) |
| itkc | 한국고전종합DB — 문집 (韓國古典綜合DB) | [db.itkc.or.kr](https://db.itkc.or.kr) |

---

## 설치

### 사전 준비

fathom은 Claude Code 스킬이므로, Claude Code가 먼저 설치되어 있어야 합니다.

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

### 수동 설치

자동 설치가 동작하지 않는 경우, 터미널에서 아래 두 줄을 순서대로 실행합니다:

```bash
git clone https://github.com/BAHO92/fathom.git ~/.claude/skills/fathom
pip3 install requests beautifulsoup4 lxml pyyaml
```

### 업데이트

이미 설치된 상태에서 최신 버전으로 업데이트하려면, 자동 설치 명령을 다시 실행하면 됩니다. 기존 설치를 감지하여 자동으로 업데이트합니다.

---

## 초기 설정

fathom을 설치한 뒤 **처음 크롤링을 요청하면**, Claude가 자동으로 초기 설정을 안내합니다. 별도로 설정 파일을 만들 필요가 없습니다.

### 설정 흐름

#### 1단계: 저장 경로

```
fathom을 처음 사용하시는군요! 간단한 설정을 진행하겠습니다.

수집한 데이터를 저장할 경로를 지정해 주세요.
(기본값: ~/DB)
Enter를 누르시면 기본값을 사용합니다.
```

수집한 데이터가 저장될 폴더 경로입니다. 기본값 `~/DB`를 쓰시면 홈 폴더 아래 `DB` 폴더가 만들어집니다. 원하는 경로가 있으면 입력하세요.

#### 2단계: 활성 데이터베이스

```
활성화할 데이터베이스를 선택해 주세요. (기본값: 전체)
  - sillok: 조선왕조실록
  - sjw: 승정원일기
  - itkc: 한국고전종합DB (문집)

쉼표로 구분하여 입력해 주세요. (예: sillok, sjw)
Enter를 누르시면 전체를 활성화합니다.
```

특정 DB만 사용할 경우 선택할 수 있습니다. 대부분의 경우 Enter를 눌러 전체를 활성화하면 됩니다.

#### 3단계: 추가 수집 필드 (Appendix)

```
추가 수집 필드(appendix)를 설정하시겠습니까?

appendix 필드는 렌더링/네비게이션용 부수 데이터입니다.
기본값은 수집하지 않으며, 필요한 항목만 선택하실 수 있습니다.

[조선왕조실록]
  ◈ day_articles: 같은 날 기사 목록 (네비게이션용)
  ◈ prev_article_id: 이전 기사 ID
  ◈ next_article_id: 다음 기사 ID
  ◈ place_annotations: 지명 annotation (일부 기사)
  ◈ book_annotations: 서명 annotation (일부 기사)

[승정원일기]
  ◈ person_annotations: SJW 페이지 인명/관직 마크업
  ◈ day_total_articles: 같은 날 기사 총수

[한국고전종합DB (문집)]
  ◈ page_markers: 원문 페이지 구분 마커 (렌더링용)
  ◈ indent_levels: 원문/번역 들여쓰기 레벨 (렌더링용)

Enter를 누르시면 appendix 없이 core 필드만 수집합니다.
```

Appendix는 기사 본문·메타데이터 외에 추가로 수집하는 부수 데이터입니다. 일반적인 텍스트 분석 연구라면 **Enter를 눌러 건너뛰어도** 충분합니다. 네비게이션 UI를 만들거나 인명 DB를 구축하는 등 특수한 용도가 있을 때 선택하세요.

#### 설정 완료

```
설정이 완료되었습니다!

  저장 경로: ~/DB
  활성 DB: 조선왕조실록, 승정원일기, 한국고전종합DB (문집)
  Appendix: 없음 (core 필드만 수집)

설정은 config.json에 저장되었습니다.
이제 크롤링을 시작하실 수 있습니다!
```

> **설정을 변경하고 싶다면**: fathom 설치 폴더(`~/.claude/skills/fathom/`)의 `config.json`을 직접 수정하거나, 삭제하면 다음 실행 시 초기 설정이 다시 시작됩니다.

---

## 사용 방법

설치와 초기 설정이 끝나면, Claude Code에서 자연어로 요청합니다:

```
"실록에서 '송시열' 검색해줘"
"승정원일기 현종 1년 수집해줘"
"문집 ITKC_MO_0367A 전체 수집해줘"
```

### 작동 방식

1. **의도 파싱** — 자연어에서 대상 DB + 셀렉터 + 파라미터를 추출합니다
2. **Preflight** — 건수를 확인하고 사용자에게 확인을 요청합니다
3. **수집 + 리포트** — 크롤링을 실행하고 결과 번들을 생성합니다

예를 들어 "실록에서 '송시열' 검색해줘"라고 하면:

```
조선왕조실록에서 '송시열' 검색 결과, 약 2,550건이 확인되었습니다.
수집을 진행하시겠습니까?
```

확인하면 수집이 시작되고, 완료 시:

```
[수집 완료]
- 대상: 조선왕조실록
- 결과: 총 2,550건 성공, 0건 실패
- 번들: ~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
```

---

## 사용 시나리오

fathom은 네 가지 수집 방식(A–D)을 지원합니다.

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

**자연어 예시**:
```
"실록에서 '송시열' 검색해줘"
"승정원일기에서 '허목' 제목 검색, 20건만"
"문집에서 '송시열,허목' 검색해줘"
```

**셀렉터 예시**:
```python
# 실록: "송시열" 원문 검색, 50건 제한
{"db": "sillok", "type": "query", "keywords": "송시열", "layer": "original", "limit": 50}

# 승정원일기: "허목" 제목 필드만 검색
{"db": "sjw", "type": "query", "keywords": "허목", "options": {"field": "title"}, "limit": 20}

# ITKC: 문집에서 복수 키워드 검색
{"db": "itkc", "type": "query", "keywords": "송시열,허목"}
```

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

**자연어 예시**:
```
"승정원일기 현종 1년 수집해줘"
"승정원일기 숙종 3년부터 5년까지"
"승정원일기 인조 즉위년 수집해줘"
```

**셀렉터 예시**:
```python
# 현종 1년만
{"db": "sjw", "type": "time_range", "reign": "현종", "year_from": 1, "year_to": 1, "limit": 50}

# 숙종 3년~5년
{"db": "sjw", "type": "time_range", "reign": "숙종", "year_from": 3, "year_to": 5}

# 인조 즉위년(0년) 전체
{"db": "sjw", "type": "time_range", "reign": "인조", "year_from": 0, "year_to": 0}
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

**자연어 예시**:
```
"문집 ITKC_MO_0367A 전체 수집해줘"
"승정원일기 현종 전체, 5년~10년만"
"문집 ITKC_MO_0367A에서 100건만 수집해줘"
```

**셀렉터 예시**:
```python
# ITKC: 송자대전 전체
{"db": "itkc", "type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A"}

# 승정원일기: 현종 5년~10년만 (segment 활용)
{"db": "sjw", "type": "work_scope", "work_kind": "reign", "work_id": "현종", "segment": "5-10", "limit": 50}
```

> **참고**: SJW `work_scope`에서 segment 없이 사용하면 전체 재위 기간을 수집하므로 장기 재위(15년+)에서는 상당한 시간이 걸립니다. `segment` 및/또는 `limit`을 함께 지정하세요.

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

| DB | 예시 |
|----|------|
| sillok | `wpa_12112025_002` |
| sjw | `SJW-C01010020-00100` |
| itkc | `ITKC_MO_0367A_001_0010` |

**자연어 예시**:
```
"실록 기사 wpa_12112025_002 수집해줘"
"이 ID 목록으로 승정원일기 수집해줘: [파일 경로]"
```

**셀렉터 예시**:
```python
# 실록: 특정 기사 ID
{"db": "sillok", "type": "ids", "id_list": ["wpa_12112025_002", "wpa_12112025_003"]}

# 승정원일기: 파일에서 ID 읽기
{"db": "sjw", "type": "ids", "source_file": "/path/to/ids.tsv"}
```

**에러 처리**: 각 DB 사이트가 잘못된 ID를 처리하는 방식은 다릅니다(실록→404, 승정원일기→빈 페이지, ITKC→500). fathom은 이를 모두 정규화하여 — 무효 기사를 `failed.jsonl`에 에러 설명과 함께 기록합니다.

---

---

# 레퍼런스

## 출력 번들 구조

크롤링이 완료되면 지정된 저장 경로에 **번들 폴더**가 생성됩니다:

```
~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
├── articles.jsonl      # 수집된 기사 (한 줄 = 한 기사 JSON)
├── provenance.json     # 수집 조건·도구 버전·통계 (재현용)
└── failed.jsonl        # 실패 기록 (ID, 에러 사유, 재시도 횟수)
```

| 파일 | 설명 |
|------|------|
| `articles.jsonl` | 수집 성공한 기사. JSONL v3.1 스키마. |
| `provenance.json` | 이 수집을 재현하기 위한 메타데이터 — 검색 조건, 도구 버전, 수집 시각, 성공/실패 통계. |
| `failed.jsonl` | 수집 실패한 기사 목록. 각 항목에 기사 ID, 에러 메시지, 재시도 횟수 포함. |

---

## JSONL v3.1 스키마

각 기사는 **Core 필드**(항상 수집)와 **Appendix 필드**(설정에 따라 선택)로 구성됩니다.

### Core 필드 — 공통

모든 DB에서 항상 포함되는 필드입니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `schema_version` | string | `"3.1"` |
| `id` | string | 기사 고유 ID (DB별 형식) |
| `source` | string | 출처 DB: `"sillok"` / `"sjw"` / `"munzip"` |
| `metadata` | object | 메타데이터 (DB별 구조 — 아래 참조) |
| `original` | object | 원문 (한문) |
| `translation` | object | 번역문 (국역) |
| `has_translation` | boolean | 번역문 존재 여부 |
| `url` | string | 원본 사이트 기사 URL |
| `crawled_at` | string | 수집 시각 (ISO 8601) |
| `appendix` | object | 부수 데이터 (설정에 따라 비어 있을 수 있음) |

### Core 필드 — DB별 메타데이터

<details>
<summary><b>조선왕조실록 (sillok)</b></summary>

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

| 필드 | 설명 |
|------|------|
| `sillok_name` | 실록명 (예: "인조실록") |
| `volume` | 권수 |
| `date.reign` | 왕대명 |
| `date.year/month/day` | 재위년/월/일 |
| `date.ganzhi` | 간지 (예: "乙酉") |
| `date.article_num` | 해당일 기사 순번 |
| `category` | 분류 (대분류/소분류) |
| `page_info` | 태백산사고본·국편영인본 면수 |
| `footnotes` | 주석 (용어 + 풀이) |

</details>

<details>
<summary><b>승정원일기 (sjw)</b></summary>

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

| 필드 | 설명 |
|------|------|
| `date.reign/year/month/day/ganzhi` | 실록과 동일 구조 |
| `western_year` | 서력 연도 (예: 1660) |
| `chinese_era` | 중국 연호 (예: "順治 17年") |
| `source_info.book_num` | 책차 번호 |
| `source_info.book_num_talcho` | 탈초본 책차 |
| `itkc_data_id` | ITKC 교차 참조 ID |

</details>

<details>
<summary><b>한국고전종합DB — 문집 (itkc/munzip)</b></summary>

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

| 필드 | 설명 |
|------|------|
| `title` / `title_ko` | 한문 제목 / 국역 제목 |
| `seo_myeong` | 서명 (예: "송자대전") |
| `gwon_cha` | 권차 (예: "제108권") |
| `mun_che` | 문체 (예: "잡저", "서", "소") |
| `author` | 저자 정보 (이름, 한자, 생몰년) |
| `seo_ji_id` | 서지 ID (예: "ITKC_MO_0367A") |
| `translator` | 번역자/번역 위원회 |
| `original.sections` | 원문 — 섹션 단위, 각 섹션에 행 배열 |
| `translation.paragraphs` | 번역문 — 단락 단위 (index + text) |

</details>

---

### Appendix 필드 — DB별

Appendix는 초기 설정에서 선택하는 **부수 데이터**입니다. 기본값은 수집하지 않습니다.

#### 실록

| 필드 | 설명 |
|------|------|
| `day_articles` | 같은 날 기사 목록 (네비게이션용) |
| `prev_article_id` | 이전 기사 ID |
| `next_article_id` | 다음 기사 ID |
| `place_annotations` | 지명 annotation |
| `book_annotations` | 서명 annotation |

#### 승정원일기

| 필드 | 설명 |
|------|------|
| `person_annotations` | 인명/관직 마크업 |
| `day_total_articles` | 같은 날 기사 총수 |

#### 문집 (ITKC)

| 필드 | 설명 |
|------|------|
| `page_markers` | 원문 페이지 구분 마커 |
| `indent_levels` | 원문/번역 들여쓰기 레벨 |

---

## 개발

```bash
python3 -m pytest tests/ -v                    # 전체 테스트 (142건)
python3 -m pytest tests/test_engine.py -v      # 엔진 테스트
python3 -m pytest tests/test_sillok.py -v      # 어댑터 테스트
```

## 프로젝트 구조

```
fathom/
├── SKILL.md              # Claude 스킬 정의
├── registry.yaml         # DB 메타데이터
├── config.default.json   # 기본 설정
├── engine/               # 코어 엔진
│   ├── workflow.py       # 3단계 워크플로우
│   ├── selector.py       # 셀렉터 스키마
│   ├── config.py         # 설정 관리
│   ├── output.py         # JSONL 출력
│   ├── provenance.py     # 수집 출처 메타데이터
│   └── onboarding.py     # 초기 설정
├── dbs/                  # DB 어댑터
│   ├── base.py           # 추상 베이스
│   ├── sillok/           # 조선왕조실록
│   ├── sjw/              # 승정원일기
│   └── itkc/             # ITKC 문집
└── tests/
```

## 라이선스

MIT — [LICENSE](LICENSE) 참조

## 저자

BAHO ([GitHub](https://github.com/BAHO92))
