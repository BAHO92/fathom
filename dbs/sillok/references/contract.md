# Sillok Crawler Contract

## Output Structure

```
DB/Sillok/{번들명}/
├── raw/              # 기사별 개별 JSON (신규 크롤링)
└── metadata.json     # 수집 메타정보
```

**변경사항**: `articles.json` 생성 제거됨. 모든 기사는 `raw/*.json`으로 개별 저장.

## Bundle Naming Convention

`{검색어}_{출처}` (예: `송시열_숙종`, `송시열_전체`)

## Metadata Schema

### metadata.json
```json
{
  "bundle_name": "광기_전체",
  "source": "sillok",
  "crawl_mode": "search",
  "created_at": "2025-02-09T12:34:56",
  "total_articles": 127,
  "articles_with_translation": 120,
  "failed_articles": 0,
  "search_params": {
    "keywords": ["狂氣", "發狂", "癲狂"],
    "tab": "w",
    "reign_range": "전체"
  },
  "source_detail": {
    "sillok_names": ["현종실록", "숙종실록"]
  }
}
```

**필드 설명**:
- `source`: 데이터 출처 (고정값: `"sillok"`)
- `crawl_mode`: 크롤링 모드 (`"search"` 또는 `"file"`)
- `articles_with_translation`: 번역문 포함 기사 수
- `search_params`: 검색 모드 파라미터 (검색어, 탭, 왕대 범위)
- `source_detail`: 실록 특화 정보 (구 `source_sillok` 필드)
  - `sillok_names`: 수집된 실록 이름 목록

## Article JSON Structure

각 기사는 `raw/{article_id}.json`으로 저장:

```json
{
  "id": "hyeonjong_12_08_12_001",
  "title": "기사 제목",
  "date": {
    "reign": "현종",
    "year": 12,
    "month": 8,
    "day": 12
  },
  "url": "https://sillok.history.go.kr/...",
  "original_text": "原文內容...",
  "translation": "번역문 내용...",
  "has_translation": true,
  "source_specific": {
    "sillok_name": "현종실록",
    "article_num": "12번째기사",
    "footnotes": [],
    "page_info": "현종 12년 8월 12일",
    "category": "정사"
  }
}
```

**필드 설명**:
- `id`: 기사 고유 ID (왕대_년_월_일_순번)
- `has_translation`: 번역문 존재 여부
- `source_specific`: 실록 특화 필드
  - `sillok_name`: 실록 이름
  - `article_num`: 기사 번호
  - `footnotes`: 주석 목록
  - `page_info`: 페이지 정보
  - `category`: 기사 분류 (정사, 사론 등)

## Index Structure

`DB/Sillok/_index/` 디렉토리에 다음 인덱스 파일 생성:

- `bundle_registry.json`: 번들 목록
- `corpus_registry.json`: 전체 기사 인덱스
- `reign/*.json`: 왕대별 인덱스
- `keywords/*.json`: 키워드 역인덱스

## Search Mode Limitations

검색어 기반 크롤링은 실록 웹사이트 검색 인덱스에 의존:

- **특수 기사 누락 가능**: 묘지문(誌文), 행장(行狀) 등 날짜 없는 문서
- 검색어가 본문에 포함되어도 검색 결과에서 제외될 수 있음
- 예: "山林" 검색 시 효종/현종/숙종/영조 묘지문 4건 누락 사례 확인

**완전한 수집 필요 시**: file 모드(TSV 파일 기반) 사용 권장
