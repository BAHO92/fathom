---
name: fathom
description: |
  역사 사료 통합 수집 도구. 조선왕조실록, 승정원일기, 한국고전종합DB(문집) 크롤링.
  "실록 크롤링", "승정원일기 수집", "문집 크롤링", "ITKC", "사료 수집",
  "fathom", "크롤링해줘", "수집해줘" 요청 시 사용.
---

# fathom — 역사 사료 통합 수집 도구

조선왕조실록, 승정원일기, 한국고전종합DB(문집)를 통합 수집하는 JSONL v3.1 크롤러입니다.

---

## 지원 데이터베이스

| DB ID | 이름 | 시대 | 사이트 | 선택자 |
|-------|------|------|--------|--------|
| `sillok` | 조선왕조실록 | 조선 | sillok.history.go.kr | query, work_scope, ids |
| `sjw` | 승정원일기 | 조선 | sjw.history.go.kr | query, time_range, work_scope, ids |
| `itkc` | 한국고전종합DB (문집) | 조선 | db.itkc.or.kr | query, work_scope, ids |

**선택자 타입**:
- `query`: 키워드 전문검색
- `time_range`: 날짜/연호 범위 지정
- `work_scope`: 문집/왕대 단위 전체 수집
- `ids`: 사용자 제공 ID 리스트

---

## 3단계 워크플로우

### Stage 1 — 의도 파싱

자연어에서 **[대상 DB] + [selector type] + [파라미터]** 추출.

**DB 라우팅**: "실록/sillok" → sillok, "승정원/sjw" → sjw, "문집/ITKC" → itkc
**Selector 매핑**: "검색/키워드" → query, "년대/시기" → time_range, "전체" → work_scope, "ID/목록" → ids

```python
from engine.workflow import parse_intent
intent = parse_intent(user_input)
```

### Stage 2 — Preflight

건수 확인 + 사용자 확인.

1. DB 확정 시 `dbs/{db_id}/contract.md` 로딩 (상세 파라미터/옵션/스키마)
2. 건수 확인 및 요약 생성
3. 존댓말로 확인 메시지 출력

```python
from engine.workflow import preflight
summary = preflight(adapter, selector)
```

**확인 예시**:
```
조선왕조실록에서 '송시열' 검색 (원문) 결과, 약 1,234건이 확인되었습니다.
수집을 진행하시겠습니까?
```

### Stage 3 — 실행 + 리포트

크롤링 실행 + 결과 보고.

```python
from engine.workflow import execute
report = execute(adapter, selector, config, limit=None)
```

**보고 예시**:
```
[수집 완료]
- 대상: 조선왕조실록
- 결과: 총 1,230건 성공, 4건 실패
- 번들: ~/DB/bndl_20260213-1430--a1b2c3__song-siyeol__src-sillok/
```

---

## 첫 실행 처리

`config.json`이 없으면 사용자의 요청을 실행하기 **전에** 반드시 온보딩을 완료해야 합니다.

**3단계 전부 완료 필수 — 어떤 단계도 스킵하지 마세요:**

1. **저장 경로** — `get_db_root_prompt()` 호출 → 사용자 입력 대기
2. **활성 DB** — `get_db_selection_prompt()` 호출 → 사용자 입력 대기 (사용자의 첫 요청이 특정 DB를 지칭하더라도, 향후 다른 DB 사용을 위해 반드시 설정)
3. **Appendix 필드** — `get_appendix_prompt(enabled_dbs)` 호출 → 번호로 선택 또는 Enter로 스킵

3단계 완료 후 `create_config_from_onboarding()`으로 `config.json` 저장.
그 다음 사용자의 원래 요청을 실행합니다.

```python
from engine.onboarding import check_onboarding
if check_onboarding():
    # 반드시 3단계 전부 진행 후 config.json 저장
```

---

## 스크립트 실행 패턴

실제 크롤링은 **DB별 Python 스크립트** 실행. 스킬 루트 기준 `dbs/{db_id}/scripts/` 경로 사용.

---

## 언어 규칙

**모든 사용자 대면 출력에서 존댓말을 사용합니다.**

✅ **사용**:
- "~하겠습니다", "~드리겠습니다", "~해 주세요"
- "수집을 진행하시겠습니까?", "완료되었습니다"

❌ **금지**:
- "~해줘", "~할게", "~할까"
- "수집 진행할까?", "완료했어"

---

## 파일 구조

```
fathom/
├── SKILL.md                # 이 문서
├── registry.yaml           # DB 메타데이터
├── engine/workflow.py      # 3단계 엔진
└── dbs/{db_id}/
    ├── contract.md         # DB별 상세 계약서
    ├── adapter.py          # 어댑터 구현
    └── scripts/            # 크롤링 스크립트
```
