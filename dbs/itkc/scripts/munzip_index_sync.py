#!/usr/bin/env python3
"""
munzip_index_sync.py - 문집 인덱스 동기화 스크립트

DB/Munzip/*/ 번들들을 스캔하여 _index/ 디렉토리의 모든 인덱스 파일을 갱신합니다.
중복 기사는 bundles 배열로 관리하여 어떤 번들에서 수집되었는지 추적합니다.

디렉토리 구조:
    DB/Munzip/
    ├── _index/                          # 소스 레벨 Silver (집계·조회)
    │   ├── keywords/                    # 키워드 역인덱스 (번들 카드에서 합산)
    │   │   ├── _catalog.json
    │   │   ├── 인물.json
    │   │   └── ...
    │   ├── source/                      # 문집별 인덱스
    │   ├── corpus_registry.json         # 기사 메타 + 전처리 상태
    │   └── bundle_registry.json         # 번들 목록
    └── {번들명}/                         # 개별 번들
        ├── articles.json
        ├── metadata.json
        └── index/                       # 번들 레벨 Silver
            ├── manifest.json
            ├── cards/                   # 기사별 카드 (요약+키워드)
            └── keywords.json

Usage:
    python munzip_index_sync.py           # 실제 동기화
    python munzip_index_sync.py --dry-run # 변경사항 미리보기 (파일 수정 없음)
    python munzip_index_sync.py --verbose # 상세 로그
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def get_project_root() -> Path:
    """프로젝트 루트 찾기 (.claude/skills/munzip-crawler/scripts에서 3단계 상위)"""
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent.parent.parent


def _get_db_root() -> Path:
    import os
    env = os.environ.get("KHC_DB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        cf = base / "crawl-orchestrator" / "config.json"
        if cf.is_file():
            try:
                c = json.loads(cf.read_text(encoding="utf-8"))
                raw = c.get("db_root", "")
                if raw:
                    p = Path(raw).expanduser()
                    return (p if p.is_absolute() else cf.parent / p).resolve()
            except Exception:
                pass
            return (base / "DB").resolve()
    return Path.home() / "DB"


def scan_bundles(munzip_dir: Path, verbose: bool = False) -> list:
    """DB/Munzip/ 내 모든 번들 스캔 (_index, test 등 제외)"""
    bundles = []

    for item in munzip_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith('_') or item.name == 'test':
            continue

        metadata_path = item / 'metadata.json'
        articles_path = item / 'articles.json'
        keywords_path = item / 'keywords.json'

        if not metadata_path.exists():
            if verbose:
                print(f"  [SKIP] {item.name}: metadata.json 없음")
            continue

        bundle = {
            'name': item.name,
            'path': item,
            'metadata_path': metadata_path,
            'articles_path': articles_path,
            'keywords_path': keywords_path
        }

        # metadata 로드
        with open(metadata_path, 'r', encoding='utf-8') as f:
            bundle['metadata'] = json.load(f)

        # articles 로드 (raw/*.json 우선, 없으면 articles.json)
        raw_dir = item / 'raw'
        articles = []
        if raw_dir.exists() and any(raw_dir.glob('*.json')):
            for json_file in sorted(raw_dir.glob('*.json')):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        article = json.load(f)
                    articles.append(article)
                except (json.JSONDecodeError, KeyError):
                    continue
        else:
            if articles_path.exists():
                with open(articles_path, 'r', encoding='utf-8') as f:
                    articles = json.load(f)
        
        bundle['articles'] = articles

        # keywords 로드 (있으면)
        if keywords_path.exists():
            with open(keywords_path, 'r', encoding='utf-8') as f:
                bundle['keywords'] = json.load(f)
        else:
            bundle['keywords'] = {}

        bundles.append(bundle)
        if verbose:
            print(f"  [OK] {item.name}: {len(bundle['articles'])} articles")

    return bundles


def extract_query_from_name(bundle_name: str) -> str:
    """번들 폴더명에서 검색어 추출 (예: '송자대전_正人心' → '正人心')"""
    parts = bundle_name.split('_', 1)
    if len(parts) > 1:
        return parts[1]
    return bundle_name


def extract_source_from_name(bundle_name: str) -> str:
    """번들 폴더명에서 출전 추출 (예: '송자대전_正人心' → '송자대전')"""
    parts = bundle_name.split('_', 1)
    return parts[0]


def build_bundle_registry(bundles_data: list) -> dict:
    """bundle_registry.json 데이터 구성"""
    bundles = []

    for bnd in bundles_data:
        meta = bnd['metadata']
        query = meta.get('query') or extract_query_from_name(bnd['name'])
        source = meta.get('source_name') or extract_source_from_name(bnd['name'])

        bundle = {
            'name': bnd['name'],
            'query': query,
            'source': source,
            'created': meta.get('crawl_date', '')[:10] if meta.get('crawl_date') else '',
            'article_count': len(bnd['articles']),
            'preprocessing_done': meta.get('preprocessing_done', False)
        }
        bundles.append(bundle)

    return {
        'bundles': bundles,
        'last_synced': datetime.now().isoformat()
    }


def build_corpus_registry(bundles_data: list, index_dir: Path) -> dict:
    """corpus_registry.json 데이터 구성 (중복 병합, 전처리 상태 보존)"""
    corpus = {}

    # 기존 corpus_registry 로드 (전처리 상태 보존용)
    existing_corpus = {}
    corpus_path = index_dir / 'corpus_registry.json'
    if corpus_path.exists():
        with open(corpus_path, 'r', encoding='utf-8') as f:
            existing_corpus = json.load(f)

    for bnd in bundles_data:
        for article in bnd['articles']:
            article_id = article.get('id', '')
            if not article_id:
                continue

            # source 정보 추출
            source_info = article.get('source', {})

            if article_id not in corpus:
                # 기존 전처리 상태 가져오기
                existing_entry = existing_corpus.get(article_id, {})

                corpus[article_id] = {
                    'bundles': [bnd['name']],
                    'source': source_info.get('seo_myeong', ''),
                    'gwon_cha': source_info.get('gwon_cha', ''),
                    'mun_che': source_info.get('mun_che', ''),
                    'category': source_info.get('mun_che_category', ''),
                    'title': article.get('title', ''),
                    'title_ko': article.get('title_ko', ''),
                    'author': article.get('author', {}).get('name', ''),
                    # 전처리 상태 필드 (기존 값 보존 또는 기본값)
                    'preprocessed': existing_entry.get('preprocessed', False),
                    'preprocessed_at': existing_entry.get('preprocessed_at', ''),
                    'preprocessed_by': existing_entry.get('preprocessed_by', '')
                }
                
                # Determine canonical_bundle
                bundles = corpus[article_id]['bundles']
                canonical = None
                for b in bundles:
                    if b.startswith("전체_"):
                        canonical = b
                        break
                if canonical is None and bundles:
                    canonical = bundles[0]
                corpus[article_id]['canonical_bundle'] = canonical
            else:
                # 이미 존재하는 기사면 bundles에 추가
                if bnd['name'] not in corpus[article_id]['bundles']:
                    corpus[article_id]['bundles'].append(bnd['name'])
                    
                    # Recalculate canonical_bundle
                    bundles = corpus[article_id]['bundles']
                    canonical = None
                    for b in bundles:
                        if b.startswith("전체_"):
                            canonical = b
                            break
                    if canonical is None and bundles:
                        canonical = bundles[0]
                    corpus[article_id]['canonical_bundle'] = canonical

    return corpus


def build_source_indexes(bundles_data: list) -> dict:
    """source/{문집명}.json 데이터 구성"""
    source_data = {}  # {문집명: {articles: {}, bundles: set()}}

    for bnd in bundles_data:
        for article in bnd['articles']:
            article_id = article.get('id', '')
            if not article_id:
                continue

            source_info = article.get('source', {})
            source_name = source_info.get('seo_myeong', '')
            if not source_name:
                source_name = extract_source_from_name(bnd['name'])

            if source_name not in source_data:
                source_data[source_name] = {
                    'source': source_name,
                    'source_hanja': source_info.get('seo_myeong_hanja', ''),
                    'articles': {},
                    'bundles': set()
                }

            source_data[source_name]['bundles'].add(bnd['name'])

            if article_id not in source_data[source_name]['articles']:
                source_data[source_name]['articles'][article_id] = {
                    'id': article_id,
                    'gwon_cha': source_info.get('gwon_cha', ''),
                    'mun_che': source_info.get('mun_che', ''),
                    'category': source_info.get('mun_che_category', ''),
                    'title': article.get('title', ''),
                    'title_ko': article.get('title_ko', ''),
                    'bundles': [bnd['name']]
                }
            else:
                if bnd['name'] not in source_data[source_name]['articles'][article_id]['bundles']:
                    source_data[source_name]['articles'][article_id]['bundles'].append(bnd['name'])

    # 최종 형태로 변환
    result = {}
    for source_name, data in source_data.items():
        articles_list = list(data['articles'].values())
        result[source_name] = {
            'source': data['source'],
            'source_hanja': data['source_hanja'],
            'total_articles': len(articles_list),
            'articles': articles_list,
            'bundles': sorted(list(data['bundles']))
        }

    return result


def build_keyword_indexes_from_bundles(bundles_data: list) -> dict:
    """번들의 keywords.json에서 역인덱스 구성 (기본 카테고리만)"""
    base_categories = ['인물', '관직', '지명', '개념', '사건', '유형']
    merged = {cat: {} for cat in base_categories}

    for bnd in bundles_data:
        keywords = bnd.get('keywords', {})

        for category in base_categories:
            cat_keywords = keywords.get(category, {})

            for keyword, article_ids in cat_keywords.items():
                if keyword not in merged[category]:
                    merged[category][keyword] = []

                # 기사 ID 병합 (중복 제거)
                for aid in article_ids:
                    if aid not in merged[category][keyword]:
                        merged[category][keyword].append(aid)

    return merged


def build_keyword_indexes_from_cards(source_dir: Path) -> dict:
    """번들별 index/cards/ 에서 키워드 역인덱스 구성 (동적 카테고리 지원)"""
    merged = {}

    for bundle_dir in sorted(source_dir.iterdir()):
        if not bundle_dir.is_dir() or bundle_dir.name.startswith('_'):
            continue
        cards_dir = bundle_dir / 'index' / 'cards'
        if not cards_dir.exists():
            continue

        for card_file in cards_dir.glob('*.json'):
            try:
                with open(card_file, 'r', encoding='utf-8') as f:
                    card = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            article_id = card.get('id', card_file.stem)
            keywords = card.get('keywords', {})

            for category, values in keywords.items():
                if category not in merged:
                    merged[category] = {}

                if isinstance(values, list):
                    for keyword in values:
                        if keyword not in merged[category]:
                            merged[category][keyword] = []
                        if article_id not in merged[category][keyword]:
                            merged[category][keyword].append(article_id)

    return merged


def build_keyword_catalog(keyword_indexes: dict) -> dict:
    """_catalog.json 데이터 구성 (키워드 목록)"""
    catalog = {}
    for category, keywords in keyword_indexes.items():
        catalog[category] = sorted(keywords.keys())
    return catalog


def sync_indexes(dry_run: bool = False, verbose: bool = False):
    """인덱스 동기화 실행"""
    project_root = get_project_root()
    munzip_dir = _get_db_root() / 'Munzip'
    index_dir = munzip_dir / '_index'

    print("문집 인덱스 동기화")
    print(f"  프로젝트: {project_root}")
    print(f"  Munzip DB: {munzip_dir}")
    print(f"  인덱스: {index_dir}")
    if dry_run:
        print("  [DRY-RUN] 파일 수정 없음")
    print()

    # 1. 번들 스캔
    print("1. 번들 스캔...")
    bundles_data = scan_bundles(munzip_dir, verbose)
    print(f"   발견된 번들: {len(bundles_data)}개")
    print()

    if not bundles_data:
        print("   처리할 번들이 없습니다.")
        return

    # 인덱스 디렉토리 확인/생성
    if not dry_run:
        index_dir.mkdir(exist_ok=True)
        (index_dir / 'source').mkdir(exist_ok=True)
        (index_dir / 'keywords').mkdir(exist_ok=True)
        # 카드는 번들 레벨 index/cards/에 저장됨

    # 2. bundle_registry.json
    print("2. bundle_registry.json 갱신...")
    bundle_registry = build_bundle_registry(bundles_data)
    bundle_path = index_dir / 'bundle_registry.json'
    if verbose:
        for b in bundle_registry['bundles']:
            print(f"   - {b['name']}: {b['article_count']} articles")
    if not dry_run:
        with open(bundle_path, 'w', encoding='utf-8') as f:
            json.dump(bundle_registry, f, ensure_ascii=False, indent=2)
    print(f"   → {len(bundle_registry['bundles'])}개 번들")
    print()

    # 3. corpus_registry.json (중복 병합 + 전처리 상태 보존)
    print("3. corpus_registry.json 갱신 (중복 병합 + 전처리 상태 보존)...")
    corpus_registry = build_corpus_registry(bundles_data, index_dir)
    corpus_path = index_dir / 'corpus_registry.json'

    # 중복 통계
    total_raw = sum(len(bnd['articles']) for bnd in bundles_data)
    unique_count = len(corpus_registry)
    duplicate_count = total_raw - unique_count
    multi_bundle = sum(1 for v in corpus_registry.values() if len(v['bundles']) > 1)
    preprocessed_count = sum(1 for v in corpus_registry.values() if v.get('preprocessed'))

    if not dry_run:
        with open(corpus_path, 'w', encoding='utf-8') as f:
            json.dump(corpus_registry, f, ensure_ascii=False, indent=2)
    print(f"   → {unique_count}개 유니크 기사 (원본 {total_raw}개, 중복 {duplicate_count}개)")
    print(f"   → {multi_bundle}개 기사가 여러 번들에 소속")
    print(f"   → {preprocessed_count}개 기사 전처리 완료")
    print()

    # 4. source/{문집명}.json
    print("4. source/*.json 갱신...")
    source_indexes = build_source_indexes(bundles_data)
    for source_name, data in source_indexes.items():
        source_path = index_dir / 'source' / f'{source_name}.json'
        if verbose:
            print(f"   - {source_name}: {data['total_articles']} articles")
        if not dry_run:
            with open(source_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"   → {len(source_indexes)}개 문집")
    print()

    # 5. keywords/*.json (cards 우선, 없으면 bundles에서)
    print("5. keywords/*.json 갱신...")

    # cards 디렉토리에서 키워드 수집 시도
    cards_keywords = build_keyword_indexes_from_cards(munzip_dir)

    if cards_keywords:
        # cards에서 키워드 수집됨 (전처리된 데이터 우선)
        keyword_indexes = cards_keywords
        print("   (cards에서 키워드 수집)")
    else:
        # cards가 비어있으면 bundles의 keywords.json에서 수집
        keyword_indexes = build_keyword_indexes_from_bundles(bundles_data)
        print("   (bundles에서 키워드 수집)")

    for category, keywords in keyword_indexes.items():
        keyword_path = index_dir / 'keywords' / f'{category}.json'
        if verbose:
            print(f"   - {category}: {len(keywords)}개 키워드")
        if not dry_run:
            with open(keyword_path, 'w', encoding='utf-8') as f:
                json.dump(keywords, f, ensure_ascii=False, indent=2)

    # _catalog.json 생성
    catalog = build_keyword_catalog(keyword_indexes)
    catalog_path = index_dir / 'keywords' / '_catalog.json'
    if not dry_run:
        with open(catalog_path, 'w', encoding='utf-8') as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)

    total_keywords = sum(len(kw) for kw in keyword_indexes.values())
    print(f"   → {len(keyword_indexes)}개 카테고리, {total_keywords}개 키워드")
    print(f"   → _catalog.json 갱신됨")
    print()

    # 완료
    if dry_run:
        print("[DRY-RUN] 완료. 실제 파일은 수정되지 않았습니다.")
    else:
        print(f"동기화 완료: {datetime.now().isoformat()}")


def main():
    parser = argparse.ArgumentParser(
        description='문집 인덱스 동기화 스크립트'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='변경사항 미리보기 (파일 수정 없음)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='상세 로그 출력'
    )

    args = parser.parse_args()
    sync_indexes(dry_run=args.dry_run, verbose=args.verbose)


if __name__ == '__main__':
    main()
