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

### 자동 설치

```bash
curl -fsSL https://raw.githubusercontent.com/BAHO92/fathom/main/install.sh | bash
```

### 수동 설치

```bash
git clone https://github.com/BAHO92/fathom.git ~/.claude/skills/fathom
pip3 install requests beautifulsoup4 lxml pyyaml
```

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

## 출력 형식

```
~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
├── articles.jsonl      # 한 줄 = 한 기사 JSON
├── provenance.json     # 수집 출처 및 재현 정보
└── failed.jsonl        # 실패 기록
```

## 설정

처음 실행 시 안내에 따라 설정을 진행합니다:
- 데이터 저장 경로 (기본값: `~/DB`)
- 활성화할 데이터베이스
- Appendix 필드 선택

설정은 `config.json`에 저장됩니다. 직접 수정하거나 삭제 후 다시 설정하실 수 있습니다.

## 셀렉터

| 타입 | 설명 | 예시 |
|------|------|------|
| query | 키워드 전문검색 | "실록에서 '허목' 검색" |
| time_range | 날짜 범위 (SJW만) | "승정원일기 인조 1년~5년" |
| work_scope | 문집/왕대 전체 | "문집 ITKC_MO_0367A 전체" |
| ids | 기사 ID 목록 | TSV/JSON 파일 또는 ID 직접 전달 |

## 개발

```bash
python3 -m pytest tests/ -v                    # 전체 테스트
python3 -m pytest tests/test_engine.py -v      # 엔진 테스트
python3 -m pytest tests/test_sillok.py -v      # 어댑터 테스트
```

## 라이선스

MIT — [LICENSE](LICENSE) 참조

## 저자

BAHO ([GitHub](https://github.com/BAHO92))
