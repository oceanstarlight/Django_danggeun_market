# 🥕 폴리마켓 (Poly Market)

> Django로 만드는 동네 중고거래 플랫폼, 대학교 기말 프로젝트

폴리마켓은 우리 동네 이웃끼리 물건을 사고파는 중고거래 웹 서비스입니다. 회원가입과 동네 설정, 상품 등록과 검색, 찜, 판매자와의 실시간 채팅, 거래완료 처리와 거래 후기(매너온도), 알림, 신고·차단까지 중고거래의 전체 흐름을 구현했습니다. 여기에 Google Gemini 기반 AI 기능 4종을 더해 판매글 작성과 거래를 돕습니다. 기능별로 Django 앱을 나누었고(`apps/*`), 화면은 Tailwind CSS와 HTMX로 만들었습니다.

### ✨ 핵심 기능

**기본 기능**

- 👤 **회원**: 회원가입(HTMX 아이디·닉네임 중복 확인), 로그인/로그아웃, 마이페이지, 프로필 수정(닉네임·아바타·소개·동네), 판매자 프로필
- 🛍️ **중고거래**: 상품 등록/수정/삭제(사진 여러 장, 최대 10장), 검색어·카테고리·동네 필터와 "거래 가능만" 보기, 정렬(최신순·인기순·낮은 가격순·높은 가격순), 판매중/예약중/거래완료 상태 변경, 최근 본 상품
- ❤️ **찜**: 상품 찜하기/취소 토글
- 💬 **실시간 채팅**: Django Channels + WebSocket 1:1 채팅, 읽음 표시, 자동 재연결(놓친 메시지 보충)
- 🤝 **거래**: 거래완료 처리(구매자 선택), 거래 후기 작성, 후기에 따른 매너온도 반영
- 🔔 **알림**: 새 채팅 메시지·찜한 상품 가격 변동·거래 후기 등 알림, 헤더 배지와 드롭다운
- 🚨 **신고·차단**: 상품/사용자 신고, 사용자 차단(어느 쪽이든 차단 관계가 있으면 상대의 상품이 목록에서 숨겨지고, 새 채팅 시작·메시지 전송·찜·거래 상대 선택이 막힙니다)

**AI 기능 4종** (Gemini, `apps/ai/services/`)

| # | 기능 | 설명 | 모듈 |
|:---:|---|---|---|
| 1 | 📝 **사진 + 키워드 설명 생성** | 사진(최대 2장)이나 키워드 중 하나 이상과 (선택) 카테고리로 판매글 제목·본문·추천 태그를 만들어 줍니다 | `description.py` |
| 2 | 📷 **사진 인식 자동 분류** | 사진 1~2장을 보고 카테고리·제목·상품 상태를 추천합니다 (DB에 있는 카테고리 안에서만 고릅니다) | `vision.py` |
| 3 | 🛡️ **사기 의심 게시글 탐지** | 정규식 규칙(선입금·외부 메신저·계좌번호 등)과 가격 이상치, AI 판단을 합쳐 위험도(낮음/주의/위험)를 매기고 상품 상세에 경고 배너를 띄웁니다. 채팅 메시지도 같은 텍스트 규칙으로 검사합니다 | `fraud.py` |
| 4 | 💬 **가격 협상 답장 초안** | 채팅에서 가격 협상 메시지를 키워드로 감지하고, 판매자가 누르면 답장 초안 3개를 만들어 줍니다 | `negotiation.py` |

> AI 결과는 폼에 자동으로 덮어쓰지 않습니다. 사용자가 결과 카드에서 **적용** 버튼을 눌러야 반영됩니다.

<br>

## 📌 목차

1. [로컬 실행](#️-로컬-실행)
2. [환경 변수](#-환경-변수)
3. [기술 스택](#-기술-스택)
4. [프로젝트 구조](#-프로젝트-구조)
5. [아키텍처 원칙](#️-아키텍처-원칙)
6. [주요 URL](#-주요-url)
7. [테스트](#-테스트)
8. [배포 (Render)](#-배포-render)

<br>

## ⚙️ 로컬 실행

> 필요한 것: **Python 3.10 이상**, **Git**
> (Node.js는 스타일을 수정할 때만 필요합니다)

### 1. 프로젝트 받기

```bash
git clone <저장소 URL>
cd Django_danggeun_market
```

### 2. 가상환경 만들기 & 활성화

<table>
<tr><th>🐧 Linux / macOS</th><th>🪟 Windows (PowerShell)</th></tr>
<tr><td>

```bash
python3 -m venv .venv
source .venv/bin/activate
```

</td><td>

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

</td></tr>
</table>

- Windows에서 `실행할 수 없습니다` 오류가 나면 PowerShell에서 한 번만 실행하세요:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- Windows **cmd** 를 쓴다면 활성화 명령은 `.venv\Scripts\activate.bat` 입니다.
- 활성화되면 프롬프트 앞에 `(.venv)` 가 보입니다.

### 3. 패키지 설치

Linux / Windows 공통입니다.

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. (선택) CSS 빌드

빌드된 `static/css/app.css` 가 저장소에 커밋되어 있으므로 **화면만 띄울 때는 이 단계가 필요 없습니다.**
`static/src/input.css`, `tailwind.config.js`, 템플릿의 Tailwind 클래스를 바꿨을 때만 다시 빌드하세요.

```bash
npm install
npm run build:css     # static/src/input.css → static/css/app.css (minify)
npm run watch:css     # 개발 중 변경을 감지해서 자동 빌드 (선택)
```

> `npm run build` 는 `node_modules` 의 HTMX를 `static/vendor/htmx.min.js` 로 복사한 뒤 CSS까지 빌드합니다.

### 5. DB 마이그레이션 & 데모 데이터

```bash
python manage.py migrate
python manage.py seed_demo
```

- `migrate` 를 하면 동네(Region)와 카테고리(Category) 기본 데이터도 함께 들어갑니다.
- `seed_demo` 는 데모 사용자·상품(사진 포함)·찜·최근 본 상품·채팅·거래 후기·신고·알림을 만듭니다. 모든 쓰기가 실제 서비스 함수를 거치므로 알림·매너온도·사기 분석도 실제 흐름과 똑같이 생깁니다.

| 옵션 | 설명 |
|---|---|
| `python manage.py seed_demo` | 데모 데이터가 없으면 생성 |
| `python manage.py seed_demo --reset` | 기존 데모 데이터를 지우고 다시 생성 |
| `python manage.py seed_demo --with-ai` | 사기 탐지에 실제 Gemini 판단까지 사용 (기본은 규칙 기반만, 오프라인 동작) |

**데모 계정** (비밀번호 공통 `demo1234!`)

| 아이디 | 닉네임 | 비고 |
|---|---|---|
| `demo_minji` | 민지네 | |
| `demo_junho` | 준호아빠 | |
| `demo_seoyeon` | 서연이네책방 | |
| `demo_dohyun` | 도현 | |
| `demo_quick` | 급처분해요 | 사기 탐지 시연용 의심 판매글 보유 |

> ⚠️ `seed_demo` 는 안전장치가 있어 **개발 환경(`DEBUG=True`, `RENDER` 없음) + SQLite + 로컬 저장소**에서만 실행됩니다.
> SQLite가 아닌 DB에서 꼭 실행해야 한다면 `SEED_DEMO_ALLOW_POSTGRES=1` 이 필요하고, `USE_SUPABASE_STORAGE` 가 켜져 있으면 실행되지 않습니다.

관리자 계정이 필요하면 다음 명령을 실행하세요. (선택)

```bash
python manage.py createsuperuser
```

### 6. 서버 실행

```bash
python manage.py runserver
```

브라우저에서 👉 http://127.0.0.1:8000/

> `daphne` 가 `INSTALLED_APPS` 맨 위에 있어서 `runserver` 만으로 WebSocket 채팅까지 동작합니다.

### 개발 / 운영 설정 전환

설정은 `config/settings/` 에 나뉘어 있고, `config/settings/__init__.py` 가 자동으로 고릅니다.

| 조건 | 사용 설정 | DB | 이미지 저장소 |
|---|---|---|---|
| `RENDER` 환경 변수 **없음** (로컬 개발·테스트) | `dev.py` | SQLite (`db.sqlite3`) | 로컬 `media/` 폴더 |
| `RENDER` 환경 변수 **있음** (Render가 자동 설정) | `prod.py` | PostgreSQL (Supabase) | Supabase Storage |

개발 환경은 `.env` 에 운영 접속 정보가 들어 있어도 **기본적으로 무시하고** SQLite + 로컬 미디어를 씁니다. 다음 스위치를 켤 때만 예외입니다.

| 스위치 | 효과 |
|---|---|
| `USE_POSTGRES=1` | 개발 환경에서도 `DB_*` 값으로 PostgreSQL에 접속 |
| `USE_SUPABASE_STORAGE=1` | 개발 환경에서도 이미지를 Supabase Storage(`SUPABASE_*`)에 업로드 |

AI 기능을 쓰려면 프로젝트 루트(`manage.py` 와 같은 폴더)의 `.env` 에 `GEMINI_API_KEY` 를 넣으세요. 키가 없어도 사이트는 정상 동작하며, AI 기능만 "지금은 AI 기능을 쓸 수 없어요" 안내가 나옵니다.

```env
GEMINI_API_KEY=
```

| 운영체제 | 파일 만들기 |
|---|---|
| Linux / macOS | `touch .env` 후 편집기로 열기 |
| Windows | `New-Item .env` (PowerShell) 후 메모장 등으로 열기. **확장자가 `.txt` 가 되지 않게 주의** |

> ⚠️ `.env` 에는 비밀번호와 키가 들어가므로 **절대 git에 커밋하지 마세요.** (`.gitignore` 에 등록되어 있습니다)

### 자주 겪는 문제

| 증상 | 해결 |
|---|---|
| `ModuleNotFoundError` | 가상환경 활성화 여부 확인 후 `pip install -r requirements.txt` 다시 실행 |
| `seed_demo` 가 "이미 있어요" 라며 멈춤 | `python manage.py seed_demo --reset` |
| AI 버튼을 눌러도 안내 문구만 나옴 | `.env` 의 `GEMINI_API_KEY` 확인 |
| DB 연결 오류 (`USE_POSTGRES=1` 일 때) | `.env` 의 `DB_*` 값과 네트워크(Supabase 접근 가능 여부) 확인 |
| 포트 8000 사용 중 | `python manage.py runserver 8001` |
| 스타일 수정이 반영되지 않음 | `npm run build:css` 후 강제 새로고침(`Ctrl+Shift+R`) |

<br>

## 🔑 환경 변수

코드(`config/settings/*`, `apps/*`)에서 실제로 읽는 환경 변수만 정리했습니다. **실제 값은 문서나 git에 남기지 마세요.**

| 이름 | 용도 | 필요한 환경 |
|---|---|---|
| `RENDER` | 값이 있으면 운영 설정(`prod.py`)을 사용. Render가 자동으로 넣어 줌 | 운영 (자동) |
| `RENDER_EXTERNAL_HOSTNAME` | `ALLOWED_HOSTS` · `CSRF_TRUSTED_ORIGINS` 에 자동 추가. Render가 자동으로 넣어 줌 | 운영 (자동) |
| `SECRET_KEY` | Django 비밀 키. 없으면 운영 서버가 시작되지 않음 | 운영 **필수** |
| `DEBUG` | `1` 이면 운영에서도 DEBUG 모드 (기본 `0`) | 운영 (선택) |
| `DJANGO_DEV_SECRET_KEY` | 개발용 비밀 키 (없으면 개발 전용 기본값 사용) | 개발 (선택) |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | PostgreSQL(Supabase) 접속 정보 | 운영 **필수**, 개발은 `USE_POSTGRES=1` 일 때 |
| `USE_POSTGRES` | `1` 이면 개발 환경에서도 PostgreSQL 사용 (기본 SQLite) | 개발 (선택) |
| `USE_SUPABASE_STORAGE` | `1` 이면 개발 환경에서도 Supabase Storage 사용 (운영은 항상 켜짐) | 개발 (선택) |
| `SUPABASE_URL` | Supabase 프로젝트 URL | 운영 **필수**, 개발은 `USE_SUPABASE_STORAGE=1` 일 때 |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Storage 업로드용 키 | 운영 **필수**, 개발은 `USE_SUPABASE_STORAGE=1` 일 때 |
| `SUPABASE_BUCKET` | 이미지 버킷 이름 (기본 `product-images`) | 운영 / 개발 (선택) |
| `GEMINI_API_KEY` | Gemini API 키. 없으면 AI 기능만 비활성화 | AI 기능을 쓸 때 |
| `GEMINI_MODEL` | 사용할 Gemini 모델 (기본 `gemini-3.5-flash-lite`) | 선택 |
| `APP_LOG_LEVEL` | `apps` 로거 로그 레벨 (기본 `INFO`) | 선택 |
| `RUN_LIVE_AI` | `1` 이면 테스트에서 실제 Gemini 호출 허용 + 라이브 스모크 테스트 실행 | 테스트 (선택) |
| `SEED_DEMO_ALLOW_POSTGRES` | `1` 이면 SQLite가 아닌 DB에서도 `seed_demo` 실행 허용 | 개발 (선택) |

<br>

## 🧰 기술 스택

| 구분 | 사용 기술 |
|---|---|
| Backend | Python 3.10+, Django 5.2, python-dotenv (`.env` 로드) |
| 실시간 통신 | Django Channels (InMemoryChannelLayer), Daphne(개발), WebSocket |
| 서버 (운영) | Gunicorn + Uvicorn Worker (ASGI), WhiteNoise (정적 파일) |
| Database | 개발 SQLite / 운영 PostgreSQL (Supabase, `psycopg`) |
| 파일 저장소 | 개발 로컬 `media/` / 운영 Supabase Storage (`supabase` SDK) |
| AI | Google Gemini (`google-genai` SDK), 이미지 전처리 Pillow |
| Frontend | Django Template, Tailwind CSS 3 (+ `@tailwindcss/forms`), HTMX 2, Vanilla JS |
| 폰트 | Pretendard Variable |
| 배포 | Render |

<br>

## 📁 프로젝트 구조

```
Django_danggeun_market/
├── config/
│   ├── settings/
│   │   ├── __init__.py         # RENDER 유무로 dev / prod 자동 선택
│   │   ├── base.py             # 공통 설정 (앱, 템플릿, Channels, AI, Supabase, 로깅, env_bool)
│   │   ├── dev.py              # 개발/테스트: SQLite + 로컬 미디어 (USE_POSTGRES / USE_SUPABASE_STORAGE 예외)
│   │   └── prod.py             # 운영: PostgreSQL + Supabase Storage + 보안 쿠키/HTTPS
│   ├── urls.py                 # 앱별 namespace include
│   ├── asgi.py                 # HTTP + WebSocket 라우팅
│   └── wsgi.py
│
├── apps/
│   ├── core/                   # 공통: 홈/헬스체크/스타일가이드, 이미지 업로드(storage.py), nav 컨텍스트, 템플릿 태그, seed_demo
│   ├── accounts/               # 회원가입·로그인, 프로필(Profile)·동네(Region), 마이페이지, 판매자 프로필
│   ├── products/               # 상품·사진·카테고리·찜·최근 본 상품, 목록/검색/상세/등록/상태 변경
│   ├── chat/                   # 채팅방·메시지, WebSocket consumer, 읽음 처리
│   ├── trades/                 # 거래완료, 거래 후기(Review), 매너온도
│   ├── notifications/          # 알림 생성·목록·드롭다운·배지
│   ├── moderation/             # 신고(Report)·차단(Block)
│   └── ai/                     # Gemini 클라이언트, AI 서비스 4종, 프롬프트, 결과 캐시·사용 기록·사기 분석
│       ├── client.py           # GeminiClient 래퍼, AIServiceError (한국어 안내 문구)
│       ├── cache.py            # cached_call: AIResultCache 재사용 + AIUsageLog 기록
│       ├── images.py           # 업로드 이미지 정규화 (긴 변 1024px JPEG)
│       ├── costs.py            # 토큰 기반 예상 비용
│       ├── prompts/            # description · vision · fraud · negotiation 프롬프트
│       └── services/           # description · vision · fraud · negotiation 서비스
│
├── templates/
│   ├── base.html               # 공통 레이아웃 (헤더 · 알림 · 토스트)
│   ├── 403.html / 404.html / 500.html
│   ├── components/             # 재사용 조각: product_card, avatar, status_badge, manner_temp, modal, pagination, empty_state, form_field, icon, messages, _styleguide …
│   └── core/ accounts/ products/ chat/ trades/ notifications/ moderation/ ai/
│       └── partials/           # HTMX 응답용 HTML 조각
│
├── static/
│   ├── src/input.css           # Tailwind 입력 (디자인 토큰 · 컴포넌트 클래스)
│   ├── css/app.css             # ⭐ 빌드 결과 (커밋됨)
│   ├── js/app.js               # 공용 JS (토스트 · 드롭다운 · 토글)
│   ├── js/chat.js              # 채팅 WebSocket · 재연결 · 읽음
│   ├── js/ai.js                # 상품 폼 AI 패널 · 협상 초안 채우기
│   ├── vendor/htmx.min.js
│   └── img/                    # 로고 · 파비콘 · 플레이스홀더 (SVG)
│
├── docs/reports/               # 보고서 (중간 보고서 등)
├── build.sh                    # Render 빌드 스크립트
├── requirements.txt
├── package.json / tailwind.config.js
└── manage.py
```

각 기능 앱은 대체로 `models.py` · `services.py`(쓰기) · `selectors.py`(조회) · `views.py` · `forms.py` · `urls.py` 구성을 따릅니다.

<br>

## 🏛️ 아키텍처 원칙

### 1. 뷰는 얇게: views → services / selectors

- **뷰**는 요청 파싱 · 권한 확인 · 응답(템플릿/HTMX 조각)만 담당합니다.
- **쓰기**(데이터 변경·비즈니스 규칙)는 각 앱의 `services.py` 를 거칩니다.
  예) `apps.products.services.create_product`, `apps.chat.services.send_message`, `apps.trades.services.complete_trade` · `create_review`, `apps.accounts.services.register_user`
- **조회**는 `selectors.py` 에 모아 `select_related` / `prefetch_related` / `annotate` 로 N+1을 피합니다.
  예) `apps.products.selectors.with_card_data`, `apps.chat.selectors`, `apps.trades.selectors.chat_partners`
- 앱 사이 공통 기능도 서비스 함수로만 씁니다.
  - 알림: `apps.notifications.services.notify`
  - 이미지 업로드: `apps.core.storage.upload_image` (확장자·크기·실제 파일 포맷 검사 후 로컬 또는 Supabase에 저장)
  - 차단 관계: `apps.moderation.services.blocked_user_ids` · `is_blocked_between`
- WebSocket consumer(`apps/chat/consumers.py`)도 뷰와 똑같이 `apps.chat.services` 만 통해 메시지를 만들고 읽음 처리합니다.

### 2. AI는 `apps/ai/services` 로만

- 뷰와 다른 앱은 **반드시 `apps.ai.services` 패키지를 통해서만** AI를 호출합니다. 뷰에서 SDK를 직접 부르지 않습니다.
- 호출 흐름: `apps/ai/views.py` 또는 다른 앱 서비스 → `apps/ai/services/*` → `apps/ai/client.py`(`get_client` → `GeminiClient`)
- 응답은 항상 JSON 스키마로 받고, 각 서비스의 검증 함수(`normalize`, 사기 탐지는 `_parse_ai`)가 길이·허용값(카테고리, 상품 상태, 점수 범위 등)을 검증합니다.
- 프롬프트는 `apps/ai/prompts/` 에 기능별로 분리했습니다.
- 다른 앱과의 연결점:
  - `apps.products.services.run_fraud_analysis` → `apps.ai.services.fraud.analyze_product` (상품 등록·수정 시)
  - `apps.chat.services.message_flags` → `fraud.check_text_rules`, `negotiation.detect_negotiation` (메시지 표시·전송 시, AI 호출 없는 규칙 검사)

### 3. AI 결과 캐싱 (`apps/ai/models.py`)

| 모델 | 역할 |
|---|---|
| `AIResultCache` | 기능 · 모델 · 입력(프롬프트 버전/텍스트/이미지 바이트)의 sha256 해시가 같으면 저장된 응답을 재사용 (`apps.ai.cache.cached_call`) |
| `AIUsageLog` | 캐시 적중을 포함한 모든 호출의 성공 여부 · 토큰 수 · 지연 시간 · 오류 기록 |
| `FraudAnalysis` | 상품당 1개의 사기 분석 결과. 내용 해시(`content_hash`)가 같고 AI 판단까지 끝났으면 재분석하지 않음 |

사용자가 **다시 생성**(`regenerate`)을 누르거나 사기 탐지에서 **다시 분석하기**를 누를 때만 캐시를 건너뜁니다. 세 모델은 모두 `/admin/` 에서 확인할 수 있습니다.

### 4. 실패해도 서비스는 계속 (Graceful failure)

- SDK · 네트워크 예외는 `apps.ai.client.AIServiceError` 로 바꾸고, 사용자에게 보여줄 수 있는 한국어 안내 문구를 담습니다. (시간 초과, 요청 과다, 서버 불안정, 응답 해석 실패 등)
- AI 뷰는 실패하면 `templates/ai/partials/error.html` 안내 조각을 돌려줍니다. HTMX 요청(협상 초안·사기 재분석)은 화면에 넣을 수 있도록 200으로, 그 외(`static/js/ai.js` 가 fetch로 부르는 설명 생성·사진 인식)는 400/502/503 상태 코드로 응답하며 `ai.js` 가 조각을 그대로 표시합니다.
- `GEMINI_API_KEY` 가 없으면 `AIUnavailableError` 로 "직접 입력해 주세요" 안내만 나오고 나머지 기능은 그대로 동작합니다.
- 사기 탐지는 상품 저장 요청 안에서 짧게(8초, 재시도 없음) 한 번만 시도합니다. AI가 실패하면 **규칙 기반 결과(RULE)로 저장**하고, 다음 저장이나 '다시 분석하기' 때 다시 시도합니다. 분석이 아예 실패해도 상품 저장에는 영향이 없습니다.
- 채팅의 협상 감지 · 사기 규칙 검사에서 오류가 나도 로그만 남기고 메시지 전송은 계속됩니다.
- 헤더 배지 조회(`apps.core.context_processors.nav`)에서 DB 오류가 나도 페이지 전체가 깨지지 않습니다.
- 테스트 실행 중에는 실제 Gemini 호출이 자동으로 차단됩니다 (`RUN_LIVE_AI=1` 일 때만 허용).

<br>

## 🔗 주요 URL

각 앱은 `app_name` namespace로 include 됩니다. 템플릿에서는 `{% url 'products:detail' pk %}` 처럼 사용합니다.

### core

| 이름 | 경로 | 설명 |
|---|---|---|
| `core:home` | `/` | 홈 (뷰는 products 앱 소유) |
| `core:health` | `/state/` | 헬스체크 (`server OK`) |
| `core:styleguide` | `/dev/styleguide/` | 디자인 스타일가이드 (DEBUG에서만, 아니면 404) |

### accounts

| 이름 | 경로 | 설명 |
|---|---|---|
| `accounts:signup` | `/accounts/signup/` | 회원가입 |
| `accounts:check_duplicate` | `/accounts/signup/check/` | 아이디·닉네임 중복 확인 (HTMX) |
| `accounts:login` | `/accounts/login/` | 로그인 |
| `accounts:logout` | `/accounts/logout/` | 로그아웃 (POST) |
| `accounts:mypage` | `/accounts/me/` | 마이페이지 |
| `accounts:profile_edit` | `/accounts/me/edit/` | 프로필 수정 |
| `accounts:seller_profile` | `/users/<username>/` | 판매자 프로필 |

### products

| 이름 | 경로 | 설명 |
|---|---|---|
| `products:list` | `/products/` | 상품 목록 · 검색 (`?q=&category=&region=&status=&sort=&page=`) |
| `products:create` | `/products/new/` | 상품 등록 |
| `products:detail` | `/products/<pk>/` | 상품 상세 |
| `products:update` | `/products/<pk>/edit/` | 상품 수정 (작성자) |
| `products:delete` | `/products/<pk>/delete/` | 상품 삭제 (작성자 또는 스태프) |
| `products:wishlist_toggle` | `/products/<pk>/wishlist/` | 찜하기 / 취소 (POST) |
| `products:status_change` | `/products/<pk>/status/` | 판매 상태 변경 (POST, 작성자) |

### chat

| 이름 | 경로 | 설명 |
|---|---|---|
| `chat:list` | `/chats/` | 내 채팅 목록 |
| `chat:room` | `/chats/<room_id>/` | 채팅방 |
| `chat:start` | `/chats/start/<product_id>/` | 판매자와 채팅 시작 |
| `chat:mark_read` | `/chats/<room_id>/read/` | 읽음 처리 (POST) |
| – | `/ws/chat/<room_id>/` | 채팅 WebSocket (`apps/chat/routing.py`) |

### trades

| 이름 | 경로 | 설명 |
|---|---|---|
| `trades:complete` | `/trades/<product_id>/complete/` | 거래완료 처리 (구매자 선택) |
| `trades:review_create` | `/trades/<product_id>/review/` | 거래 후기 작성 |

### notifications

| 이름 | 경로 | 설명 |
|---|---|---|
| `notifications:list` | `/notifications/` | 알림 목록 |
| `notifications:dropdown` | `/notifications/dropdown/` | 헤더 알림 드롭다운 (HTMX 조각) |
| `notifications:read_all` | `/notifications/read-all/` | 모두 읽음 (POST) |
| `notifications:badge` | `/notifications/badge/` | 안 읽은 알림 배지 (HTMX 조각) |
| `notifications:go` | `/notifications/<pk>/go/` | 알림 읽음 처리 후 대상 페이지로 이동 |

### moderation

| 이름 | 경로 | 설명 |
|---|---|---|
| `moderation:report_product` | `/moderation/report/product/<pk>/` | 상품 신고 |
| `moderation:report_user` | `/moderation/report/user/<username>/` | 사용자 신고 |
| `moderation:block_toggle` | `/moderation/block/<username>/` | 차단 / 차단 해제 (POST) |
| `moderation:block_list` | `/moderation/blocks/` | 차단 목록 |

### ai

| 이름 | 경로 | 설명 |
|---|---|---|
| `ai:describe` | `/ai/describe/` | 사진 + 키워드 설명 생성 (POST multipart) |
| `ai:recognize` | `/ai/recognize/` | 사진 인식 자동 분류 (POST multipart) |
| `ai:negotiate` | `/ai/negotiate/<message_id>/` | 가격 협상 답장 초안 (POST, 판매자만) |
| `ai:fraud_refresh` | `/ai/fraud/<product_id>/` | 사기 위험 다시 분석 (POST, 판매자·스태프) |

### 기타

| 경로 | 설명 |
|---|---|
| `/admin/` | 관리자 페이지 |

<br>

## 🧪 테스트

테스트는 `RENDER` 가 없으면 개발 설정(`USE_POSTGRES` 를 켜지 않았다면 SQLite)으로 실행되며, 실제 Gemini 호출은 자동으로 막힙니다.

```bash
python manage.py test                   # 전체
python manage.py test apps.ai           # 앱 하나만
python manage.py test apps.chat.tests.test_consumers
```

실제 Gemini API를 부르는 라이브 스모크 테스트(`apps/ai/tests/test_views.py` 의 `LiveSmokeTests`)는 기본적으로 건너뜁니다. `GEMINI_API_KEY` 를 준비한 뒤 `RUN_LIVE_AI=1` 로 실행하세요. (API 사용량이 발생합니다)

<table>
<tr><th>🐧 Linux / macOS</th><th>🪟 Windows (PowerShell)</th></tr>
<tr><td>

```bash
RUN_LIVE_AI=1 python manage.py test apps.ai.tests.test_views
```

</td><td>

```powershell
$env:RUN_LIVE_AI="1"; python manage.py test apps.ai.tests.test_views
```

</td></tr>
</table>

<br>

## 🚀 배포 (Render)

Render는 배포 환경에 `RENDER` 환경 변수를 자동으로 넣어 주므로 운영 설정(`config/settings/prod.py`)이 자동으로 선택됩니다.

### 빌드 & 시작 명령

| 항목 | 값 |
|---|---|
| Build Command | `./build.sh` |
| Start Command | `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker` |
| Health Check Path | `/state/` |

`build.sh` 는 다음 순서로 실행됩니다.

```bash
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
```

- Tailwind CSS는 커밋된 `static/css/app.css` 를 그대로 쓰므로 **빌드 중 npm은 실행하지 않습니다.** 스타일을 바꿨다면 로컬에서 `npm run build:css` 후 `app.css` 를 함께 커밋하세요.
- 정적 파일은 WhiteNoise(`CompressedManifestStaticFilesStorage`)가 제공합니다.
- 운영 이미지는 항상 Supabase Storage(`SUPABASE_BUCKET`, 기본 `product-images`)에 저장됩니다.
- Render 환경 변수에 `SECRET_KEY`, `DB_*`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, (AI 사용 시) `GEMINI_API_KEY` 를 등록하세요. 자세한 내용은 [환경 변수](#-환경-변수) 표를 참고하세요.
- 채널 레이어가 `InMemoryChannelLayer` 이므로 **단일 인스턴스**로 운영합니다.

### ⚠️ 첫 배포 전: 기존 운영 DB 초기화 필요

이번 리팩토링에서 기존 단일 앱(`market`) 구조를 기능별 앱(`apps/*`)으로 나누면서 **마이그레이션을 새로 만들었습니다** (각 앱의 `0001_initial` 부터 시작).
기존 구조의 테이블과 마이그레이션 기록이 남아 있는 운영 DB에서는 `migrate` 가 올바르게 적용되지 않으므로, **리팩토링 버전을 처음 배포하기 전에 기존 운영 DB를 초기화해야 합니다.**

- 기존 테이블과 `django_migrations` 기록을 모두 지운 빈 DB에서 `build.sh` 의 `migrate` 가 새 스키마를 만들도록 합니다.
- 초기화하면 **기존 회원 · 상품 · 채팅 데이터가 모두 삭제됩니다.** 필요한 데이터는 미리 백업하세요.
- 관리자 계정은 초기화 후 다시 만들어야 합니다 (`python manage.py createsuperuser`).
- `seed_demo` 는 운영 환경(`RENDER` 설정 또는 `DEBUG=False`)에서는 실행되지 않습니다.
