# SJW Crawler Contract

## Output Structure

```
DB/SJW/{번들명}/
├── raw/              # 기사별 개별 JSON
├── metadata.json     # 수집 메타정보
└── failed_articles.json  # 실패 로그 (있으면)
```

**주의**: `articles.json` (전체 기사 통합)은 생성되지 않음. 개별 기사는 `raw/` 디렉토리에만 저장.

## Bundle Naming Convention

| 모드 | 형식 | 예시 |
|------|------|------|
| search | `{검색어}_{왕대범위}` | `송시열_현종숙종` |
| browse | `{왕대}_{연도범위}` | `현종_즉위년_5년`, `현종_전체` |

## Article JSON Structure

```json
{
  "id": "SJW-C03060230-00300",
  "title": "기사 제목",
  "date": {"reign": "현종", "year": 3, "month": 6, "day": 23, "ganzhi": "...", "article_num": 3},
  "source": {"book_num": 180, "book_num_talcho": 33, "source_info": "승정원일기 180책 (탈초본 33책)"},
  "url": "https://sjw.history.go.kr/id/SJW-C03060230-00300",
  "original": "한문 원문 (SJW에서 추출)",
  "translation": "국역 번역문 (ITKC에서 추출, 있으면)",
  "has_translation": true,
  "source_specific": {
    "itkc_data_id": "ITKC_ST_P0_C03_06A_23A_00030"
  }
}
```

## Metadata JSON Structure

```json
{
  "source": "sjw",
  "crawl_mode": "search",
  "search_params": {
    "keywords": ["宋時烈"],
    "field": "all",
    "reign_range": ["현종", "숙종"]
  },
  "date_range": {
    "reign_from": "현종",
    "reign_to": "숙종"
  },
  "source_detail": {
    "database": "승정원일기(sjw.history.go.kr)",
    "translation_source": "한국고전종합DB(db.itkc.or.kr)"
  },
  "bundle_name": "송시열_현종숙종",
  "total_articles": 3617,
  "articles_with_translation": 2100,
  "failed_count": 0,
  "crawl_timestamp": "2025-02-09T10:30:00Z"
}
```

**browse 모드 예시**:
```json
{
  "source": "sjw",
  "crawl_mode": "browse",
  "search_params": {
    "reign": "현종",
    "year_range": [0, 5]
  },
  "date_range": {
    "reign": "현종",
    "year_from": 0,
    "year_to": 5
  },
  "source_detail": {
    "database": "승정원일기(sjw.history.go.kr)",
    "translation_source": "한국고전종합DB(db.itkc.or.kr)"
  },
  "bundle_name": "현종_즉위년_5년",
  "total_articles": 1250,
  "articles_with_translation": 800,
  "failed_count": 0,
  "crawl_timestamp": "2025-02-09T10:30:00Z"
}
```

## 왕대 코드

| 코드 | 왕대 |
|------|------|
| A | 인조 |
| B | 효종 |
| C | 현종 |
| D | 숙종 |
| E | 경종 |
| F | 영조 |
| G | 정조 |
| H | 순조 |
| I | 헌종 |
| J | 철종 |
| K | 고종 |
| L | 순종 |

## 특이사항

- **국역은 ITKC에서 추출**: 승정원일기 번역문은 SJW가 아닌 한국고전종합DB(db.itkc.or.kr)에 존재. 크롤러가 자동으로 ITKC에서 국역을 수집.
- **국역 미존재 기사**: `has_translation: false`. 인조~효종 초기 등 번역 미완료 구간이 있음.
- **왕대 범위**: 인조(A) ~ 순종(L). 인조 이전(광해군 이전)은 승정원일기 부존재.
- **인덱스 동기화**: index_sync 스크립트 미존재. 후처리는 수동.
