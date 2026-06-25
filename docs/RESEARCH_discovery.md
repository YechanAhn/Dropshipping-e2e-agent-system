# 네이버 쇼핑 트렌드 기회 발굴 — 딥리서치 보고서 + 발굴 파이프라인 설계

> **목적**: "네이버 쇼핑 트렌드에서 지금 뜨고, 경쟁 약하고, 알리 대비 소싱 차익이 큰 상품 기회를 어떻게 체계적·자동으로 찾아내는가"에 대한, 출처 명시 리서치 + 실제 구현 설계.
> **방법**: 11개 리서치 앵글을 병렬 조사 → 교차검증. 1차 출처는 네이버 공식 저장소(`naver/naver-openapi-guide`, `naver/searchad-apidoc`)와 셀러 도구 5종 역설계.
> **신뢰도 표기**: 각 사실에 HIGH/MEDIUM/LOW. 공식 문서 직접 확인 = HIGH, 다수 3rd-party 일치 = MEDIUM-HIGH, 추론 = LOW.
> 작성일: 2026-06-13

---

## 0. TL;DR — 핵심 결론과 설계 요지

1. **절대 수요 신호는 단 하나뿐: 네이버 검색광고 키워드도구 API**(`/keywordstool`, RelKwdStat). PC/모바일 월간검색수를 실수치로 준다. 데이터랩이 아니다.
2. **공급(경쟁) 신호: 네이버 쇼핑 검색 API의 `total`**(키워드별 상품수) + `productType`(가격비교 매칭 여부).
3. **데이터랩은 전부 상대값(기간 최대=100)** 이고 쿼터도 하루 1,000회뿐. **"분야별 인기검색어 TOP500"과 "급상승"은 API에 없다**(웹사이트 전용). → 데이터랩은 *콜드 발굴*이 아니라 후보의 *추세·계절성 검증*에만 쓴다.
4. **셀러 도구 5종(아이템스카우트·판다랭크·셀러라이프·키워드마스터·블랙키위) 전부가 독립적으로 같은 공식**을 쓴다: **경쟁강도 = 공급 ÷ 수요 (상품수 또는 문서수 ÷ 월검색량), 낮을수록(특히 <1) 황금키워드.**
5. 우리에게 가장 직접적인 모델은 whereispost **셀러마스터** = `상품수(쇼핑) ÷ 월검색량(검색광고)`.
6. **콜드스타트 해법**: seed 키워드 → 검색광고 **연관키워드 확장**(절대 검색량 동반)으로 후보 수백 개 생성 → 쇼핑 API로 상품수 → 경쟁강도로 거름 → 데이터랩으로 추세/계절성 검증.
7. **소싱 차익 선별**: 비브랜드·저인증·경량·단순옵션 + **가격비교 매칭(카탈로그) 상품 회피**(`productType`) + 해외상품수 낮음.

→ **결과물(§7)**: `OpportunityScore = f(수요, 경쟁, 모멘텀, 마진잠재, 소싱적합)` 를 산출하는 다단계 파이프라인. 기존 코드의 `priority_scorer`/`margin_calculator`를 그대로 잇는다.

---

## 1. 데이터 소스 3종 — 정확한 역할 분담

### 1.1 네이버 검색광고 키워드도구 (RelKwdStat) — **유일한 절대 수요 신호** ★

| 항목 | 값 | 신뢰도 |
|------|----|--------|
| 엔드포인트 | `GET /keywordstool` (canonical host `https://api.searchad.naver.com`; `https://api.naver.com`도 동작) | HIGH |
| 인증 | HMAC-SHA256. 헤더 `X-Timestamp`, `X-API-KEY`(액세스 라이선스), `X-Customer`(고객 ID), `X-Signature` | HIGH |
| 서명식 | `base64(HMAC_SHA256(secret, "{timestamp}.{METHOD}.{uri}"))`, uri는 경로만(`/keywordstool`), method 대문자, timestamp는 **ms** | HIGH |
| 요청 | `hintKeywords`(콤마구분, 공백없음, **최대 5개**), `showDetail=1` | HIGH |
| 응답 | `{ "keywordList": [ ... ] }` 각 항목: `relKeyword`, `monthlyPcQcCnt`, `monthlyMobileQcCnt`, `monthlyAvePcClkCnt`, `monthlyAveMobileClkCnt`, `monthlyAvePcCtr`, `monthlyAveMobileCtr`, `plAvgDepth`(월평균 노출 광고수), `compIdx` | HIGH |
| **"< 10" 마스킹** | 저검색 키워드는 `monthlyPcQcCnt`/`monthlyMobileQcCnt`가 **문자열 `"< 10"`** 로 옴. `int()` 바로 쓰면 크래시. 대체값은 앱이 정함(업계 관행: 5) | HIGH |
| 값 성격 | 직전 ~1개월 PC/모바일 **추정 실수치**(반올림됨). 총수요 ≈ PC+모바일. **과거 추이는 미제공**(현재 월 스냅샷만) | HIGH |
| `compIdx` | `낮음/중간/높음` 3단계. **검색광고 경쟁도이지 쇼핑 경쟁이 아님** | HIGH |
| 비용/쿼터 | 키워드도구 호출은 **무료**(검색광고 광고주 계정 + API 라이선스 필요). 정확한 초당/일 쿼터는 **미공개**. 초과 시 `429`/`1016` → 스로틀+백오프 필수 | 쿼터 LOW, 무료 MED-HIGH |

> **함의**: 이게 우리 수요 신호의 척추다. 단, ① `"< 10"` 파서를 1일차부터 넣고, ② 한 호출당 5키워드 제한 + 레이트리밋(**공식 공지**: 키워드도구는 다른 오퍼레이션 대비 **1/5~1/6 속도**로 제한, 커스터머ID+클라이언트IP 단위 측정, 초과 시 429/1016)을 고려해 배치+지수백오프 스로틀링, ③ `compIdx`를 쇼핑 경쟁으로 오해하지 말 것(쇼핑 경쟁은 §1.2의 상품수로 별도 계산).
> 출처: `github.com/naver/searchad-apidoc` (signaturehelper.py, ad_management_sample.py, NaverSA_API_Error_Code_MAP.md), `github.com/kyungdongseo/naver_search_ad`, `github.com/1rrock/optisearch`.

### 1.2 네이버 쇼핑 검색 API — **공급(상품수) + 가격/경쟁 구조**

| 항목 | 값 | 신뢰도 |
|------|----|--------|
| 엔드포인트 | `GET https://openapi.naver.com/v1/search/shop.json` | HIGH |
| 인증 | 헤더 `X-Naver-Client-Id`, `X-Naver-Client-Secret` | HIGH |
| 요청 | `query`, `display`(max 100), `start`(max 1000), `sort`(sim/date/asc/dsc), `filter`, `exclude` | HIGH |
| 응답 | `total`(= 키워드 매칭 **총 상품수** = 공급 지표), `items[]`: `title`, `link`, `image`, `lprice`, `hprice`, `mallName`, `productId`, **`productType`**, `brand`, `maker`, `category1~4` | HIGH |
| 쿼터 | **일 25,000회** | MED-HIGH |
| `productType` | 4(상품군: 일반/중고/단종/판매예정) × 3(종류: 가격비교 대표/비매칭 단독/매칭) = **1~12**. 실무상 대부분 1·2·3. **1=가격비교 대표, 2=가격비교 비매칭 단독, 3=가격비교 매칭** | HIGH(공식 표) |
| 한계 | 검색 API로는 **상품별 판매량/리뷰수/구매수 미제공** (별도 추정 필요, §2.4) | HIGH |

> **드랍쉬핑 핵심 해석**: `productType`로 카탈로그(가격비교) 지배 여부를 본다. **2(비매칭 단독)가 많은 키워드 = 단독 상품 시장 = 가격경쟁 덜함(좋음)**. 1·3(가격비교 매칭)이 지배 = 최저가 전쟁 = 마진 갈림(회피).
> 출처: `github.com/naver/naver-openapi-guide/.../search/shopping/shopping.md`(productType 1~12 표 직접 확인), 보강 `sangjung0/wishtrack`, `jhj1111/AndroidNewsApp`.

### 1.3 네이버 데이터랩 — **상대 추세·계절성 검증 전용** (콜드 발굴 불가)

| 항목 | 값 | 신뢰도 |
|------|----|--------|
| 검색어트렌드 | `POST https://openapi.naver.com/v1/datalab/search`, body `keywordGroups`(**≤5그룹×≤20키워드**), `timeUnit`(date/week/month), `device`/`gender`/`ages`, **2016-01-01~** | HIGH |
| 쇼핑인사이트 | `POST /v1/datalab/shopping/{categories|category/keywords|.../device|gender|age}` 등 **8개**, `category`=쇼핑 URL의 `cat_id`, **2017-08-01~** | HIGH |
| 인증 | `X-Naver-Client-Id`/`X-Naver-Client-Secret` + `Content-Type: application/json` | HIGH |
| **값 성격** | **전부 상대 인덱스: 조회 구간 내 최대값=100**. 절대 검색수/판매수 **절대 안 줌**(쇼핑은 클릭량 기준) | HIGH |
| 쿼터 | **하루 1,000회/앱** (검색 API 25,000과 다름) | MED-HIGH |
| 연령코드 | 검색트렌드 `1~11`(0~12세…60+), 쇼핑 `10/20/…/60`(10~19세…60+) — **두 API가 서로 다름** | HIGH |
| **결정적 한계** | **"분야별 인기검색어 TOP500"·"급상승" 키워드 목록 엔드포인트가 API에 없음** → datalab.naver.com 웹사이트 전용. 절대값은 별도 유료 NCloud Data Box | TOP500 부재 MED-HIGH, 상대값 HIGH |

> **함의**: 데이터랩으로는 *뜨는 키워드를 처음부터 캐낼 수 없다.* 이미 가진 후보 리스트의 **추세 방향·계절성**을 매기는 데만 쓴다. 그래서 셀러 도구들도 데이터랩을 핵심으로 안 쓴다(아이템스카우트·키워드마스터 모두 검색광고+쇼핑 기반). 이게 §4 콜드스타트 설계의 근거.
> 출처: `naver/naver-openapi-guide/.../datalab/{search,shopping}/*.md` (원문 직접 확인), `api.ncloud-docs.com`.

---

## 2. 기회 점수 공식 — 셀러 도구 5종 역설계 합의

### 2.1 보편 공식 (5종 독립 확증, HIGH)

**경쟁(강)도 = 공급 ÷ 수요 = (상품수 또는 문서수) ÷ 월간검색량. 낮을수록 좋음. <1 = 황금키워드.**
다개월 조회 시 분모를 월평균으로 정규화: `÷ (검색수 ÷ 개월수)`.

| 도구 | 분자(공급) | 표현 | 데이터 출처 |
|------|-----------|------|------------|
| **아이템스카우트** | 네이버쇼핑 상품수 | 5등급(아주좋음~아주나쁨), >1=공급과잉 | 검색광고+쇼핑 |
| **판다랭크** | 당일 상품수 | 경쟁률 5등급(최적~최악) | 쇼핑+상품광고클릭 |
| **셀러라이프** | 상품수(+해외상품수) | 단일 비율, 월평균 정규화 | 쇼핑/스마트스토어 |
| **키워드마스터** | 블로그 문서수 | 비율(raw), <1 황금 | 검색광고+블로그검색 |
| **블랙키위** | 콘텐츠 발행량 | 포화지수=(발행량/검색량)×100, 등급밴드 | 검색광고+데이터랩 |

> **우리 모델 = whereispost 셀러마스터**: `경쟁강도 = product_count(네이버쇼핑 total) ÷ monthly_search_volume(검색광고 PC+모바일)`, 낮을수록 기회. (역수 "검색량÷문서수, 높을수록 좋음" 관행도 돌지만 방향만 같음 — **공급÷수요, lower=better로 통일**.)
> 출처: `school.itemscout.io/.../경쟁강도`, `whereispost.com/seller`, `i-boss.co.kr/ab-6141-69396`, `inside.ampm.co.kr/insight/9242`, 교차비교 `nananews.co.kr`, `windly.cc`.

### 2.2 분자 차이 주의 (HIGH)
쇼핑 도구(아이템스카우트/판다랭크/셀러라이프)=**상품수**, 블로그 도구(키워드마스터/블랙키위)=**문서수**. 우리는 드랍쉬핑이므로 **상품수**가 맞다. (블로그 문서수는 SEO 콘텐츠 마케팅용.)

### 2.3 보조 지표 (아이템스카우트, HIGH)
- **광고 클릭 경쟁률 = 상품수 ÷ 클릭수** (낮을수록 광고효율↑)
- **광고 종합지표** = 광고클릭률 / 클릭경쟁률 / 가격대비광고비 / 클릭대비광고비(CPC)
- 키워드 유형 ML 분류: **쇼핑성 vs 정보성** (정보성 키워드는 구매 전환 약함 → 발굴에서 후순위)

### 2.4 판매량 추정 트릭 (차용) — 검색 API에 없는 판매량 메우기 (HIGH)
아이템스카우트 **6개월 판매량 = 네이버페이 탭 상위 40/80개 상품의 6개월 합산**(상위 N 샘플 추정). 셀러라이프 **1페이지 6개월 판매건수**, 셀러마스터 **스토어 URL→예상매출**. → 우리도 상위 N 상품의 리뷰수 증가/네이버페이 구매수로 **시장규모 프록시**를 만든다.

---

## 3. 급상승/모멘텀 탐지 — 상대값 시계열에서

### 3.1 출력 모델: 아이템스카우트 4버킷 차용 (HIGH)
키워드를 **트렌드 / 신규 / 급상승 / 급하락**으로 분류. 기간필터: "**1일/7일/1달/1년 전 없던**"(=신규), "**~ 대비**"(=급상승/급하락). 이걸 발굴 산출의 라벨 체계로 채택.

### 3.2 0~100 상대 시계열에서의 모멘텀 레시피 (확정 설계)
데이터랩 검색어트렌드 `ratio[]` 시리즈(**한 호출에 ≥60주 + 작년 동기를 같이 요청** — 그래야 100 기준점이 고정되어 YoY 비교 가능)에 대해:

1. **평활화** `s[t] = SMA(ratio, 4)` — 주간 노이즈 제거
2. **윈도우 비율 모멘텀** `M = mean(최근 4주) / mean(직전 8주)`. `M > 1.2` = 상승 (구글트렌드 'rising'의 %성장과 동형, USPTO 트렌드탐지 특허도 recent-vs-prior-week 비교)
3. **기울기(스케일-free)** 최근 8주 OLS, `slope_n = β / mean(최근 8주)`; `slope_n > 0` AND `R² ≥ 0.4` 요구(추세 vs 노이즈 구분)
4. **스파이크 z-score** `z = (ratio[t] − mean(직전 12주)) / std(직전 12주)`; `z ≥ 2` 주목, `z ≥ 3` = 브레이크아웃. ⚠️ **계절 키워드는 z 계산 전 반드시 탈계절화** — z-score는 계절 데이터에서 매년 오탐(예: 매년 12월 스파이크). STL 잔차 또는 YoY로 보정 후 z
5. **계절성 게이트(필수)** `YoY = mean(최근 4주) / mean(작년 동기 4주)`. `M>1.2`인데 `YoY ≤ 1.1`이면 **계절성으로 강등**. 지속 상승 = `M>1.2` **AND** `YoY>1.2`
6. **합성** `MomentumScore = 100 × [0.35·clip(M−1) + 0.30·clip(slope_n·k) + 0.20·clip(z/3) + 0.15·clip(YoY−1)]` (clip→[0,1])
7. **절대 수준 게이트(데이터랩 보정의 핵심)** SearchAd 절대검색량(PC+모바일)이 floor(예: ≥1,000/월) 이상인 키워드만 통과 — 아무도 안 찾는 키워드의 0→100 스파이크/소분모 폭발 배제

> **신규/급부상(신상품)** 은 구글트렌드 **'브레이크아웃'**(낮은 베이스 → 급등; 구글은 +5000%를 Breakout으로 표기) 모델로 별도 탐지: `ratio`가 오래 `<5~10`이다가 급등 + 절대검색량 floor 통과. 아이템스카우트 **4버킷**(트렌드/신규/급상승/급하락, "1일/7일/1달/1년 전 대비")과 정렬해 라벨링.
> 데이터랩 상대값은 절대 비교엔 못 쓰지만 **방향·가속도·계절성**엔 충분. shortlist에만 적용(1,000회/일 쿼터 절약). 관련 기법(이동평균·회귀기울기·롤링 z·STL/YoY 탈계절화)은 모두 표준 시계열 best practice로 확인됨.

---

## 4. 콜드스타트 문제 — 뜨는 키워드를 어디서 얻나

데이터랩 API가 TOP500/급상승을 안 주므로(§1.3), 후보 시드 확보가 별도 과제다. **채택 전략(우선순위순):**

1. **(1차) 검색광고 연관키워드 확장**: seed 키워드/카테고리 → `/keywordstool` `hintKeywords` → `relKeyword[]` 수십~수백 개를 **절대 검색량과 함께** 획득. 가장 합법적·풍부.
2. **(2차) 쇼핑 카테고리 브라우징**: 쇼핑 검색 API로 카테고리별 상위 상품 → 제목에서 키워드/속성 추출 → 시드 확장.
3. **(3차, 선택) 외부 인기검색어 수집**: datalab.naver.com 분야별 인기검색어 TOP500 또는 아이템스카우트식 카테고리 인기키워드 → **웹 스크래핑(ToS 회색지대, §6)**. 신선한 급상승 후보용. 공식 API 우선 원칙상 후순위·옵션.

→ 1차+2차로 후보 풀을 만들고, §2 경쟁강도로 거르고, §3 데이터랩으로 추세 검증. 3차는 켜고 끌 수 있는 플러그인으로.

---

## 5. 소싱 차익 선별 — demand-first 드랍쉬핑 체크리스트

검증된 수요가 있어도 **알리 대비 차익이 크고 운영 리스크가 낮은** 키워드만 골라야 한다.

**좋은 키워드 6-체크리스트:**
1. **비브랜드/노브랜드** — 상표·병행수입 분쟁 회피 (쇼핑 API `brand`/`maker` 비율로 측정)
2. **저인증·저통관** — 전기용품(KC인증)·식품·화장품 회피, 일반 잡화 선호
3. **경량·소형** — 알리 배송비↓, 파손↓ (RiskScore 연계)
4. **단순 옵션** — 옵션·사이즈차트 적으면 등록/CS 비용↓ (OpsCostScore 연계)
5. **카탈로그 비지배** — `productType` 2(비매칭 단독) 비중↑, 1·3(가격비교 매칭) 지배 회피 = 최저가 전쟁 탈출
6. **소싱 차익 확인** — 네이버 경쟁가(쇼핑 `lprice` 중앙값) ≥ 알리 랜딩원가 × 목표배수(예: 2.5~3×). 매칭 후 `margin_calculator`로 정밀 검증

**보조 신호(셀러라이프 차용)**: **해외 상품수**가 낮으면 = 이미 드랍쉬핑하는 경쟁자가 적음 = 선점 여지. (높으면 레드오션)

**회피 카테고리의 법적 근거(HIGH)**: 유아/어린이용품(어린이제품안전특별법 — 판매·중개·**구매대행 전부 금지**, KC 없으면), 전기·전자/일부 생활용품(전안법/KC, 2024 직구 안전조치로 전기·생활용품 34종+어린이 34종 직구 금지), 식품·건기식·화장품·의료기기(식약처·목록통관 배제·위해식품 차단목록), 브랜드/정품(상표권·짝퉁·병행수입 분쟁).

**마진·관세 기준(소싱/마진 앵글 검증)**:
- **네이버 스마트스토어 수수료는 ~6%** (주문관리 3.63% + 판매수수료 ~2%; 영세 1.98%)이며 **2025-06 개편**으로 유입수수료 2%→판매수수료 1~4% 전환. 흔히 쓰는 "10~11%"는 쿠팡/보수 버퍼에 가까움 → 기존 `margin_calculator`의 카테고리 수수료(5.5~11%)를 **스마트스토어 ~6% + VAT 10% 별도**로 보정 필요.
- **목표 마진(한국 구매대행)**: 마진율 **20~30%** + 건당 절대이익 **최소 ₩5,000 / 목표 ₩10,000** (이하면 환율·반품에 적자 전환). 서구식 3× 마크업(중앙값 4×)은 광고형 드랍쉬핑 기준.
- **$150 개인통관 면세는 '개인 사용' 한정** — 구매대행 모델이 성립하는 이유는 *고객 주문이 개별 배송(개인 목록통관)* 되기 때문. **사업자 사입/벌크 수입은 $150 이하라도 과세** + 동일발송 **합산과세**. → 재고 사입 모델로 가면 관·부가세를 마진에 반드시 반영(관세는 상품가, VAT는 (상품가+관세)×10%).

> ⚠️ 1~5는 업계 베스트프랙티스 + 우리 도메인 추론(MEDIUM). 6은 우리 시스템의 핵심 계산(HIGH). 카테고리 회피 목록은 초기 보수적으로 잡고 데이터로 완화.

---

## 6. 법적 / ToS / 실무 제약

- **공식 API 우선 원칙**: 네이버 검색광고·쇼핑검색·데이터랩 모두 공식 API 사용. 키 발급·쿼터 준수.
- **데이터랩 TOP500/급상승은 웹 전용** → 이를 자동 수집하려면 datalab.naver.com 스크래핑이 필요하고 이는 **ToS 회색지대**. 기본은 끄고, 켜더라도 robots.txt·레이트리밋 준수, 공식 API로 대체 가능한 건 대체.
- **검색광고 API 쿼터 미공개** → 429/1016 백오프 + 보수적 스로틀(초당 소수 호출).
- **데이터랩 1,000회/일** → shortlist에만 사용, 캐싱 필수.
- **한국 판례 — 네이버 DB 무단 크롤링 위법(중요)**: 특허법원이 다윈프로퍼티의 네이버 부동산 DB 크롤링을 **DB제작자 권리 침해**로 보아 **₩8,000만 배상**(2024-12 항소심 확정). 출처표시·아웃링크로도 면책 안 됨. 무단 크롤링은 DB권 외에 컴퓨터업무방해·부정경쟁방지법·정보통신망법 위반 소지. → **네이버 페이지 스크래핑은 실질 법적 리스크**, 공식 API가 안전한 길. 시장 선두(아이템스카우트·판다랭크)가 TOP500을 데이터랩 쇼핑인사이트에서 크롤링으로 가져오지만(byline 2020 확인), **우리는 공식 API 우선·스크래핑은 옵트인으로 분리**.
- **소싱측(알리/테무)**: 알리 = 공식 Open Platform/Affiliate API 존재(사용 권장), 사이트 스크래핑은 ToS 위반. **테무 = 공개 API 없음**, 스크래핑 ToS 위반 → 그래서 테무 연기. 상세는 `PLAN_v3.md` §6.
- **착수 전 1건 수동 확인(액션)**: `shopping.naver.com/robots.txt`·`datalab.naver.com/robots.txt`·네이버 오픈API 이용약관 — TOP500 스크래핑 옵션을 켤지 결정 전 필수(이 환경에선 네트워크 차단으로 미확인, 유일한 LOW-신뢰 항목).

---

## 7. 발굴 파이프라인 설계 (구현)

### 7.1 단계 다이어그램

```
[S0] 시드 확보
     seed 키워드/카테고리 (수동 10~20개 or 쇼핑 카테고리)
        │
[S1] 후보 확장 (수요)                  ← 검색광고 /keywordstool (연관키워드 + 절대검색량)
     relKeyword[] + monthlyPc/MobileQcCnt   ("< 10" 파싱)
        │   ── 후보 수백 개, 각자 월검색량 보유
[S2] 공급/경쟁 측정                      ← 쇼핑검색 /search/shop.json (키워드별 total + productType 분포 + lprice)
     상품수, 가격중앙값, 카탈로그지배율, 브랜드율
        │
[S3] 경쟁강도 계산 + 1차 필터
     경쟁강도 = 상품수 ÷ 월검색량  → <임계 통과분만
        │
[S4] 모멘텀/계절성 검증 (shortlist만)    ← 데이터랩 /datalab/search (상대 시계열)
     TrendScore(WoW·기울기·z) + 계절성 보정 + 4버킷 라벨
        │
[S5] 소싱 적합성 스코어                   ← §5 체크리스트 (productType·brand·인증·해외상품수)
        │
[S6] 마진 잠재 프록시                      ← 네이버 lprice 중앙값 vs 알리 예상가대 (매칭은 PLAN_v3 §3.1)
        │
[S7] OpportunityScore 종합 → Top N 발굴 리스트 → 텔레그램/CLI (증거 동반)
        │
        └─→ (승인) → PLAN_v3 파이프라인(매칭→상세페이지→등록→주문)로 연결
```

### 7.2 OpportunityScore (기존 `priority_scorer` 확장)

```
OpportunityScore =
      w1 · DemandScore        # log(monthlyPc+monthlyMobile) 정규화
    + w2 · (1 − CompetitionScore)   # 경쟁강도(상품수/검색량) 역정규화
    + w3 · TrendScore         # §3 모멘텀(데이터랩 상대 시계열)
    + w4 · MarginPotential    # 네이버 경쟁가 vs 알리 예상원가 (프록시)
    − w5 · SourcingRisk       # §5 체크리스트 위반(카탈로그지배/브랜드/인증/중량)
```
- 기존 코드의 `core/priority_scorer.py`(MarginScore+DemandScore−RiskScore−OpsCostScore)와 **동형** → 그 가중치 학습 루프(`feedback/`)를 그대로 재사용.
- `CompetitionScore`/`MarginPotential`은 신규, 나머지는 기존 모듈 재활용.

### 7.3 코드 매핑 (재설계 반영)

| 단계 | 신규/재활용 | 모듈 |
|------|------------|------|
| S1 검색광고 | **신규 클라이언트** | `clients/naver/searchad_api.py` (HMAC, `"< 10"` 파서) |
| S2 쇼핑 | 재활용 | `clients/naver/shopping_api.py` (`total`/`productType` 노출 추가) |
| S3 경쟁강도 | **신규** | `core/discovery/competition.py` |
| S4 데이터랩 | 재활용 | `clients/naver/datalab_api.py` + **신규** `core/discovery/momentum.py` |
| S5 소싱적합 | 일부 재활용 | `core/risk_scorer.py`+`ops_cost_scorer.py` 확장, **신규** `core/discovery/sourcing_fit.py` |
| S6 마진프록시 | 재활용 | `core/margin_calculator.py` |
| S7 종합 | 재활용/확장 | `core/priority_scorer.py` → `OpportunityScore` |
| 오케스트레이션 | **신규** | `pipeline/discovery.py` (S0→S7) + 스케줄러 잡 |

> **갭 발견**: 기존 코드엔 **검색광고 키워드도구 클라이언트가 없다**(절대 수요의 핵심인데!). `clients/naver/`엔 commerce/shopping/datalab만 있음. → `searchad_api.py` 신설이 Phase 1의 최우선.

### 7.4 쿼터/레이트리밋 예산
- 검색광고: 미공개 → 초당 소수 호출 스로틀 + 429/1016 백오프. 후보 확장은 배치.
- 쇼핑: 25,000/일 → 후보당 1~2회면 충분(수천 키워드 커버).
- 데이터랩: **1,000/일** → S4를 shortlist(수십~수백)로 제한 + 결과 캐싱(키워드 해시).

---

## 8. 검증됨 vs 추론 (불확실성 명시)

| 항목 | 상태 |
|------|------|
| 검색광고 엔드포인트/HMAC/필드/`"< 10"` | **검증(HIGH)** — 공식 샘플코드 |
| 쇼핑 `productType` 1~12, `total` | **검증(HIGH)** — 공식 문서 |
| 데이터랩 상대값/엔드포인트/연령코드/쿼터1000 | **검증(HIGH)**, 1000회는 MED-HIGH |
| 데이터랩 TOP500/급상승 API 부재 | MED-HIGH (엔드포인트 목록 부재로 추론) |
| 경쟁강도=공급÷수요 공식 | **검증(HIGH)** — 5종 독립 일치 |
| 검색광고 정확 쿼터 수치 | **미검증** — 하드코딩 금지 |
| 셀러도구 내부 가중치(상품성 등) | 미공개 |
| 소싱 체크리스트 1~5 | 베스트프랙티스+도메인 추론(MEDIUM) |
| 스마트스토어 수수료 ~6%(2025-06 개편) | **검증(HIGH)** — 다수 실무 출처 |
| 네이버 DB 크롤링 위법 판례(다윈 ₩8천만) | **검증(HIGH)** — 다수 법률/언론 |
| $150 개인통관 면세=개인사용 한정 | **검증(HIGH)** — 관세청/법령 |
| 모멘텀 기법(이동평균·z·STL/YoY) | **검증(HIGH)** — 표준 시계열 |
| robots.txt 정확 Disallow | **미검증(LOW)** — 착수 전 수동 확인 |

---

## 9. 핵심 출처

**네이버 공식**
- 검색광고: `github.com/naver/searchad-apidoc` (signaturehelper.py, ad_management_sample.py, 에러코드맵)
- 쇼핑/데이터랩: `github.com/naver/naver-openapi-guide` (`ko/service-apis/search/shopping/shopping.md`, `.../datalab/{search,shopping}/*.md`)
- NCloud 미러: `api.ncloud-docs.com`

**셀러 도구 역설계**
- 아이템스카우트: `school.itemscout.io/wiki/keyword-index`, `.../category`, `.../경쟁강도`
- 키워드마스터/셀러마스터: `whereispost.com/keyword`, `/seller`, `/keyanalysis`
- 판다랭크: `i-boss.co.kr/ab-6141-69396`, `pandarank.net`
- 블랙키위: `inside.ampm.co.kr/insight/9242`, `blackkiwi.net`
- 셀러라이프/셀록홈즈: `sellochomes.co.kr/sellerlife`
- 교차비교: `nananews.co.kr`, `windly.cc`, `tosspayments.com/blog/articles/semo-120`

> 다수 한국 블로그·벤더 페이지는 자동 fetch에 403(안티봇) → 인용은 검색엔진 추출 스니펫 기반. 핵심 수치는 공식 GitHub 원문으로 직접 검증함.

---

## 10. 다음 단계 (Phase 1 착수 항목)

1. **`clients/naver/searchad_api.py` 신설** — HMAC 서명, `/keywordstool`, `"< 10"` 파서, 스로틀 (최우선 갭)
2. `shopping_api.py`에 `total`/`productType` 분포 추출 메서드 추가
3. `core/discovery/{competition,momentum,sourcing_fit}.py` 신설
4. `pipeline/discovery.py` (S0→S7) + 스케줄러 잡
5. `OpportunityScore`로 `priority_scorer` 확장
6. seed 카테고리 N개로 E2E 시연: 검증된 마진 후보 + 증거(경쟁강도·추세·가격분해) 산출

→ 이 설계는 `PLAN_v3.md`의 Phase 1(발굴→매칭→마진)을 구체화한 것이며, 매칭/상세페이지/주문 단계는 `PLAN_v3.md`를 따른다.
