# Munzip Crawler Contract

## Output Structure

```
DB/Munzip/{번들명}/
├── raw/              # 기사별 개별 JSON
├── articles.json     # 전체 기사 통합
├── metadata.json     # 수집 메타정보
└── failed_articles.json  # 실패 로그 (실패 시)
```

## Bundle Naming Convention

| 모드 | 형식 | 예시 |
|------|------|------|
| search | `{검색어}_{문집명}` | `正人心_송자대전` |
| full | `전체_{문집명}` | `전체_송자대전` |

## Metadata Schema

`metadata.json` 구조:

```json
{
  "source": "munzip",
  "crawl_mode": "search" | "full",
  "search_params": {
    "query": "검색어",
    "collection_id": "ITKC_MO_0367A",
    "search_target": "MO_BD"
  },
  "source_detail": {
    "seo_myeong": "송자대전",
    "seo_myeong_hanja": "宋子大全",
    "dci": "ITKC_MO_0367A"
  },
  "source_specific": {
    "title_ko": "국역 송자대전",
    "author": "송시열",
    "dci": "ITKC_MO_0367A",
    "jibsu": "9434",
    "mun_che_category": "문집류"
  },
  "crawl_date": "2026-02-09T...",
  "total_articles": 43,
  "preprocessing_done": false
}
```

## Index Structure

`DB/Munzip/_index/` 디렉토리에 다음 인덱스 파일 생성:

- `bundle_registry.json`: 번들 목록
- `corpus_registry.json`: 전체 기사 인덱스
- `source/*.json`: 출전별 인덱스
- `keywords/*.json`: 키워드 역인덱스
