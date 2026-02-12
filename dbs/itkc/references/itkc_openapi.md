# 한국고전종합DB OpenAPI 규격

> 출처: https://db.itkc.or.kr/openapi
> 작성일: 2025-01-19

## 요청 URL

```
https://db.itkc.or.kr/openapi/search
```

POST/GET 모두 가능. 입력값은 encoding 필요.

---

## 요청 변수

| 파라미터 | 값 | 설명 |
|---------|-----|------|
| `keyword` | string | 검색어 (통합검색용) |
| `q` | string | 옵션확장용 검색파라메터 (keyword 대신 사용) |
| `secId` | string (필수) | 검색대상유형 |
| `start` | number (필수, 기본값:0) | 검색자료의 요청 시작위치 |
| `rows` | number (필수, 기본값:20) | 검색자료의 요청건수 |

### q 파라미터 구문

- 파라메터 구분자: `$`
- 값 구분자: `†` (U+2020 DAGGER)
- 값내부 구분자: `^`

#### 검색옵션

| 옵션 | 설명 | 예시 |
|------|------|------|
| `opExt` | 확장/기본검색 | Y(확장), N(기본) |
| `opDir` | 디렉토리내 검색 | 자료ID(서지ID) |
| `opJib` | 집수내 검색 | 집수아이디 (멀티선택시 ^ 구분자) |
| `detail` | 상세검색 | book(문체검색), year(역사문헌), heje(문집총간해제), dci(DCI검색) |

#### 예시

```
# 검색어 설정
q=query†%EC%A1%B0%EC%84%A0

# 특정 서지내 검색 (디렉토리내 검색)
q=query†%EC%A1%B0%EC%84%A0$opDir†ITKC_BT_0014A

# 특정 집수내 검색
q=query†%EC%A1%B0%EC%84%A0$opJib†a001^a002
```

---

## secId: 검색대상유형

### 고전번역서 (BT)
| secId | 설명 |
|-------|------|
| BT_AA | 전체 |
| BT_SJ | 서지 |
| BT_AU | 저/편/필자 |
| BT_KW | 권차/문체명 |
| BT_GS | 기사명 |
| BT_BD | 본문 |

### 고전원문 (GO)
| secId | 설명 |
|-------|------|
| GO_AA | 전체 |
| GO_SJ | 서지 |
| GO_AU | 저/편/필자 |
| GO_KW | 권차/문체명 |
| GO_GS | 기사명 |
| GO_BD | 본문 |

### 한국문집총간 (MO) ⭐
| secId | 설명 |
|-------|------|
| MO_AA | 전체 |
| MO_SJ | 서지 |
| MO_AU | 저/편/필자 |
| MO_KW | 권차/문체명 |
| MO_GS | 기사명 |
| MO_BD | 본문 |

### 한국고전총간 (KP)
| secId | 설명 |
|-------|------|
| KP_AA | 전체 |
| KP_SJ | 서지 |
| KP_AU | 저/편/필자 |
| KP_KW | 권차/문체명 |
| KP_GS | 기사명 |
| KP_BD | 본문 |

### 조선왕조실록 (JT)
| secId | 설명 |
|-------|------|
| JT_AA | 전체 |
| JT_SJ | 서지 |
| JT_GS | 기사명 |
| JT_BD | 본문 |

### 신역 조선왕조실록 (JR)
| secId | 설명 |
|-------|------|
| JR_AA | 전체 |
| JR_SJ | 서지 |
| JR_GS | 기사명 |
| JR_BD | 본문 |

### 승정원일기 (ST)
| secId | 설명 |
|-------|------|
| ST_AA | 전체 |
| ST_SJ | 서지 |
| ST_GS | 기사명 |
| ST_BD | 본문 |

### 일성록 (IT)
| secId | 설명 |
|-------|------|
| IT_AA | 전체 |
| IT_SJ | 서지 |
| IT_GS | 기사명 |
| IT_BD | 본문 |

### 해제
| secId | 설명 |
|-------|------|
| BT_HJ | 고전번역서 |
| JR_HJ | 신역 조선왕조실록 |
| GO_HJ | 고전원문 |
| MI_HJ | 문집총간 |
| KI_HJ | 고전총간 |

### 기타
| secId | 설명 |
|-------|------|
| KU_JA | 경서성독 전체 |
| PC_IL | 도설자료 전체 |
| SJ_AA | 서지정보 전체 |
| JS_AA | 각주정보 전체 |
| TR_AA | 시소러스 전체 |
| CS_AA | 동양고전종합DB 전체 |
| SE_AA | 세종한글고전 전체 |

### 해제 상세검색
| secId | 설명 |
|-------|------|
| MI_H1 | 형태서지 |
| MI_H2 | 문집저자 |
| MI_H3 | 행력 |
| MI_H4 | 가계 |
| MI_H5 | 편찬및간행 |
| MI_H6 | 구성과내용 |

---

## 검색결과

### Header 필드

| 필드 | 설명 |
|------|------|
| secId | 검색대상유형 |
| keyword | 검색어 |
| startPos | 요청 시작위치 |
| rows | 요청건수 |
| totalCount | 총검색건수 |

### 본문 항목 (doc/field)

| 필드명 | 설명 |
|--------|------|
| DCI_s | DCI 식별자 |
| 저자 | 저자명 (한글\|한자) |
| 저자생년 | 출생년도 |
| 저자몰년 | 사망년도 |
| 기사명 | 기사 제목 |
| 권차명 | 권차 정보 |
| 간행기간 | 간행 기간 |
| 서명 | 서적명 (한글(한자)) |
| 문체명 | 문체 분류 |
| 문체분류 | 상세 문체 분류 |
| 간행처 | 간행 기관 |
| 아이템ID | 아이템 분류 ID |
| 자료구분 | 자료 유형 |
| 검색필드 | 검색어 하이라이트된 본문 snippet |
| 자료ID | 기사 고유 ID (⭐ 크롤링 핵심) |
| 집수번호 | 집수 번호 |
| 간행년 | 간행 연도 |
| 역자 | 번역자 |
| 서지ID | 서지 ID |

---

## 결과 예시 (XML)

```xml
<response>
<header>
    <field name="keyword">조선</field>
    <field name="start">0</field>
    <field name="rows">10</field>
    <field name="totalCount">3870</field>
</header>
<result>
    <doc>
        <field name="DCI_s">ITKC_MK_C007_009_2002_13790_XML</field>
        <field name="저자">안정복|安鼎福</field>
        <field name="저자몰년">1791</field>
        <field name="기사명">후조선(後朝鮮)</field>
        <field name="권차명">동사강목 부록 상권 상</field>
        <field name="간행기간">1977~1979</field>
        <field name="서명">동사강목(東史綱目)</field>
        <field name="문체명">고이(考異)</field>
        <field name="아이템ID">ITKC_BT</field>
        <field name="자료구분">최종정보</field>
        <field name="저자생년">1712</field>
        <field name="검색필드">후<em class="hl1">조선</em>(後<em class="hl1">朝鮮</em>)...</field>
        <field name="자료ID">ITKC_BT_1366A_0400_010_0130</field>
        <field name="집수번호">009</field>
        <field name="역자">장순범 이정섭</field>
    </doc>
</result>
</response>
```

---

## 호출 예시

### 기본 검색

```bash
# 고전번역서 본문에서 '조선' 검색
https://db.itkc.or.kr/openapi/search?secId=BT_BD&keyword=%EC%A1%B0%EC%84%A0&start=0&rows=10

# 한국문집총간 본문에서 '正人心' 검색
https://db.itkc.or.kr/openapi/search?secId=MO_BD&keyword=%E6%AD%A3%E4%BA%BA%E5%BF%83&start=0&rows=10
```

### 옵션확장 검색

```bash
# 특정 서지(송자대전) 내에서 '正人心' 검색
https://db.itkc.or.kr/openapi/search?secId=MO_BD&q=query†正人心$opDir†ITKC_MO_0367A&start=0&rows=10

# 특정 서지의 전체 기사 목록 (검색어 없이 opDir만)
https://db.itkc.or.kr/openapi/search?secId=MO_GS&q=opDir†ITKC_MO_0367A&start=0&rows=100
```

---

## 주요 서지ID 예시

| 서명 | 서지ID | 분류 |
|------|--------|------|
| 송자대전 | ITKC_MO_0367A | 한국문집총간 |
| 송자대전 (번역) | ITKC_BT_0367B | 고전번역서 |
| 동사강목 | ITKC_BT_1366A | 고전번역서 |

---

## 기사 내용 접근

OpenAPI는 목록만 제공. 실제 원문/번역문은 웹페이지에서 크롤링 필요.

```
# 원문 페이지
https://db.itkc.or.kr/dir/node?dataId={자료ID}

# 번역문 포함 (viewSync=TR)
https://db.itkc.or.kr/dir/node?dataId={자료ID}&viewSync=TR
```

### HTML 구조
- 원문: `div.text_body.ori` 내 `div.xsl_para`
- 번역문: `div.gisa2 div.text_body` 내 `div.xsl_para`
