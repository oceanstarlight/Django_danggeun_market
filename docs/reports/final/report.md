# 기말 보고서 — 폴리마켓: Django 기반 동네 중고거래 웹 서비스 (리팩토링 · 기능 확장 · AI 4종)

| 항목 | 내용 |
|---|---|
| 과목 담당 | 고진형 교수님 |
| 제출자 | 학번: 2605111001 / 이름: 김민규 |
| 완성일 | 2026-11-24 |
| 저장소 | https://github.com/oceanstarlight/Django_danggeun_market |
| 분석 기준 | git HEAD `9ac08b6` (Merge pull request #6) |

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [개발 환경 및 기술 스택](#2-개발-환경-및-기술-스택)
3. [시스템 구조](#3-시스템-구조)
4. [데이터 모델](#4-데이터-모델)
5. [기본 기능 구현](#5-기본-기능-구현)
6. [AI 기능 4종 (Gemini)](#6-ai-기능-4종-gemini)
7. [화면 구성](#7-화면-구성)
8. [테스트](#8-테스트)
9. [배포](#9-배포)
10. [중간 보고서 개선 계획 이행 결과](#10-중간-보고서-개선-계획-이행-결과)
11. [한계점 및 향후 과제](#11-한계점-및-향후-과제)
12. [결론](#12-결론)

> 본 보고서는 git HEAD(`9ac08b6`) 시점의 소스 코드와, 로컬 개발 환경(SQLite + `seed_demo` 데모 데이터)에서 직접 실행한 결과만을 근거로 작성했다. 본문의 파일 경로와 행 번호는 모두 HEAD 기준이다. 화면 캡처는 `python manage.py seed_demo`로 만든 데모 계정으로 로그인해 촬영했다.

---

## 1. 프로젝트 개요

### 1.1 목적과 기말 단계의 목표

**폴리마켓(Poly Market)**은 우리 동네 이웃끼리 물건을 사고파는 **동네 중고거래 웹 서비스**다. 중간 단계에서는 단일 앱(`market`) 위에 회원가입·로그인, 상품 CRUD, 찜, 1:1 실시간 채팅까지 핵심 흐름을 구현했다. 기말 단계의 목표는 중간 보고서 8.4절에 세운 계획 네 가지를 실제로 완성하는 것이었다.

1. **구조 개편**: 단일 앱을 기능별 앱 8개로 나누고, 서비스 레이어(`services.py` / `selectors.py`)를 도입해 뷰를 얇게 만든다. 중간에 발견한 설정 버그를 함께 바로잡고 테스트를 작성한다.
2. **디자인 개편**: 공통 `base.html` + Tailwind CSS + HTMX로 화면을 다시 만든다.
3. **기본 기능 확장**: 동네, 카테고리, 거래상태, 다중 이미지, 거래 후기·매너온도, 알림, 신고·차단, 판매자 프로필, 최근 본 상품, 채팅 읽음 표시 등.
4. **AI 기능 4종**: Google Gemini로 판매글 설명 생성, 사진 인식 자동 분류, 사기 의심 글 탐지, 가격 협상 답장 초안.

### 1.2 구현 범위 요약 (중간 → 기말)

| 영역 | 중간 버전 | 기말 버전 |
|---|---|---|
| 앱 구조 | `market` 단일 앱, 함수형 뷰 491행에 로직 집중 | 기능별 앱 8개(`apps/*`) + `services.py`(쓰기) / `selectors.py`(조회) |
| 설정 | `config/settings.py` 1개, `DEBUG = False` 하드코딩 | `config/settings/` base · dev · prod 분리, `RENDER` 환경 변수로 자동 선택 |
| 회원 | 가입·로그인 | + 프로필(닉네임·아바타·소개), HTMX 중복 확인, 마이페이지, 판매자 프로필 |
| 동네 | 없음 (`href="#"`) | 전국 행정동 3,559개, 시/도 → 시/군/구 → 읍/면/동 3단 선택 |
| 상품 | 이미지 1장, 카테고리·상태 없음 | 사진 최대 10장, 카테고리 15종, 판매중/예약중/거래완료, 상품 상태 5단계, 검색·필터·정렬·페이지네이션 |
| 채팅 | 생성 시각순 목록, 읽음·재연결 없음 | 마지막 메시지순, 읽음 표시·안 읽은 수, 자동 재연결 + 놓친 메시지 보충 |
| 거래 | 없음 | 거래완료(구매자 선택), 양방향 후기, 별점에 따른 매너온도 |
| 알림 · 신고 | 없음 | 새 메시지·가격 변동·후기·거래 상태 알림, 상품/사용자 신고, 사용자 차단 |
| AI | 없음 | Gemini 기반 4종 + 결과 캐시 · 사용 기록 |
| 화면 | 공용 CSS, 템플릿 9개가 `<head>` 반복 | `base.html` 상속, Tailwind 디자인 토큰, HTMX 부분 갱신, 템플릿 65개 |
| 테스트 | 없음 (`tests.py` 기본 파일) | **410개** (모두 통과, 실제 Gemini 호출 스모크 테스트 1개만 기본 skip) |

### 1.3 개발 일정 (Git 이력)

| 날짜 | 커밋 | 내용 |
|---|---|---|
| 2026-09-10 ~ 11-05 | `567f2b5` ~ `ee841ef` | 중간 버전 (단일 앱, Render 배포) |
| 2026-11-12 | `d5201df` | 중간 보고서 사실 검증 |
| 2026-11-12 | `6ee93ee` | 리팩토링 체크포인트: 앱 분리, 디자인 시스템, 기능 구현 일부 |
| 2026-11-12 | `61f850b` | 통합: 에러 페이지(403/404/500), `seed_demo`, 플레이스홀더 제거 |
| 2026-11-12 | `346e3af` | 코드 리뷰 지적사항 19건 수정 (보안 · AI 캐시 · 사기 탐지 오탐 · 접근성) |
| 2026-11-12 | `28fe2b1` | 배포 준비: Python 3.13 고정, 기존 운영 DB에 초기화 없이 배포 가능하도록 정리 |
| 2026-11-12 | `58b5b51` | 배포용 관리자 계정 명령 `ensure_admin` |
| 2026-11-12 | `effa38b` | 닉네임 띄어쓰기 허용 (공백 정규화, 공백·대소문자 무시 중복 확인) |
| 2026-11-12 | `0163095`, `d0a928f` | 전국 행정동 3,559개 데이터 + 동네 3단 선택 |
| 2026-11-12 | `f1c2fe5` | 운영 DB: 재사용 전 연결 상태 확인 (간헐적 500 방지) |

중간 버전 HEAD(`ee841ef`)와 비교하면 390개 파일이 바뀌었고 24,425행이 추가, 36,246행이 삭제되었다. 삭제가 더 많은 이유는 잘못 커밋되어 있던 `staticfiles/` 127개 파일과 옛 `market` 앱을 정리했기 때문이다. 현재 애플리케이션 코드(마이그레이션·테스트 제외)는 약 7,200행, 테스트 코드는 약 4,800행, 템플릿은 약 3,200행이다.

---

## 2. 개발 환경 및 기술 스택

### 2.1 기술 스택

| 구분 | 사용 기술 |
|---|---|
| Backend | Python 3.13(`.python-version`), Django 5.2, python-dotenv |
| 실시간 통신 | Django Channels 4 (`InMemoryChannelLayer`), Daphne(개발), WebSocket |
| 서버 (운영) | Gunicorn + Uvicorn Worker (ASGI), WhiteNoise |
| Database | 개발 SQLite / 운영 PostgreSQL (Supabase, `psycopg` 3) |
| 파일 저장소 | 개발 로컬 `media/` / 운영 Supabase Storage |
| AI | Google Gemini (`google-genai` SDK, 기본 모델 `gemini-3.5-flash-lite`), 이미지 전처리 Pillow |
| Frontend | Django Template, Tailwind CSS 3 (+ `@tailwindcss/forms`), HTMX 2, Vanilla JS |
| 배포 | Render |

### 2.2 의존성 (`requirements.txt`)

중간 보고서에서 지적한 UTF-16 인코딩, `psycopg`/`psycopg2`·`dotenv`/`python-dotenv` 중복, Pillow 누락, 오타 파일 `requirments.txt`를 모두 정리했다. 현재 파일은 UTF-8이고 버전을 고정한 9개 패키지만 남았다.

```text
Django==5.2.19          channels==4.3.2        daphne==4.2.3
gunicorn==27.0.0        uvicorn[standard]==0.54.0   whitenoise==6.12.0
python-dotenv==1.2.4    psycopg[binary]==3.3.8 supabase==2.34.1
pillow==13.0.0          google-genai==3.2.0
```

### 2.3 설정 분리 (`config/settings/`)

설정을 세 파일로 나누고, 진입점 `config/settings/__init__.py`(10~13행)가 `RENDER` 환경 변수 유무로 하나를 고른다. Render는 배포 환경에 이 변수를 자동으로 넣어 주므로 별도 조작 없이 운영 설정이 선택된다.

| 파일 | 역할 |
|---|---|
| `base.py` | 공통: `INSTALLED_APPS`, 미들웨어, 템플릿, 채널 레이어, `LOGIN_URL`, 업로드 제한, Gemini·Supabase·로깅, `env_bool()` 헬퍼 |
| `dev.py` | `DEBUG = True`, SQLite + 로컬 `media/`. `.env`에 운영 접속 정보가 있어도 무시하고, `USE_POSTGRES=1` / `USE_SUPABASE_STORAGE=1`일 때만 예외 |
| `prod.py` | `DEBUG`는 환경 변수(기본 `0`), `SECRET_KEY`가 없으면 `ImproperlyConfigured`로 시작 거부, PostgreSQL + Supabase Storage, 보안 쿠키 · HTTPS 프록시 헤더 |

개발 설정이 운영 DB를 "기본으로 무시"하도록 만든 것은 실수로 로컬에서 운영 DB에 `seed_demo`나 테스트를 실행하는 사고를 막기 위해서다.

---

## 3. 시스템 구조

### 3.1 디렉터리 구조

```
Django_danggeun_market/
├── config/
│   ├── settings/ (__init__ · base · dev · prod)
│   ├── urls.py            # 앱별 namespace include
│   └── asgi.py            # HTTP + WebSocket 라우팅
├── apps/
│   ├── core/              # 홈 · 헬스체크 · 이미지 업로드(storage.py) · nav 컨텍스트 · 템플릿 태그 · seed_demo
│   ├── accounts/          # 회원 · Profile · Region(동네) · 마이페이지 · 판매자 프로필 · ensure_admin
│   ├── products/          # 상품 · 사진 · 카테고리 · 찜 · 최근 본 상품
│   ├── chat/              # 채팅방 · 메시지 · WebSocket consumer · 읽음 처리
│   ├── trades/            # 거래완료 · 거래 후기 · 매너온도
│   ├── notifications/     # 알림 생성 · 목록 · 드롭다운 · 배지
│   ├── moderation/        # 신고 · 차단
│   └── ai/                # Gemini 클라이언트 · 서비스 4종 · 프롬프트 · 캐시 · 사용 기록
├── templates/             # base.html, components/, 앱별 폴더, partials/(HTMX 조각)
├── static/                # src/input.css → css/app.css(빌드 결과), js/(app · chat · ai), vendor/htmx
└── docs/reports/          # 중간 · 기말 보고서
```

각 기능 앱은 대체로 `models.py` · `services.py` · `selectors.py` · `views.py` · `forms.py` · `urls.py` · `tests` 구성을 따른다.

### 3.2 계층 구조: views → services / selectors

중간 버전의 가장 큰 구조적 문제는 인증·상품·찜·채팅·업로드 로직이 모두 `market/views.py` 한 파일에 섞여 있다는 점이었다. 기말 버전에서는 다음 규칙으로 책임을 나눴다.

```
 요청 ─▶ views.py ──────────────┬─▶ services.py  (쓰기 · 비즈니스 규칙 · 트랜잭션)
        (파싱 · 권한 · 응답)     └─▶ selectors.py (조회 · select_related/prefetch/annotate)
 WebSocket ─▶ consumers.py ─────▶ chat/services.py  (뷰와 같은 함수 사용)
 다른 앱 ───────────────────────▶ notifications.services.notify / moderation.services.is_blocked_between
                                 / core.storage.upload_image / ai.services.*
```

- **뷰**는 요청 파싱, 권한 확인, 응답(전체 페이지 또는 HTMX 조각)만 맡는다.
- **서비스**는 데이터 변경과 규칙 검사를 맡고, 사용자에게 그대로 보여 줄 수 있는 예외(`ProductActionError`, `ChatError`, `TradeError`, `ModerationError`, `StorageError`)를 던진다. 뷰는 이 예외를 잡아 토스트 메시지로 바꾸기만 한다.
- **셀렉터**는 읽기 전용 쿼리를 모아 N+1 쿼리를 한 곳에서 막는다.
- **앱 사이 의존**도 서비스 함수로만 한다. 예를 들어 `chat.services.send_message`는 알림 모델을 직접 만들지 않고 `notifications.services.notify`를 부른다.

이 덕분에 HTTP 뷰와 WebSocket consumer가 **같은 서비스 함수**를 공유한다. 예컨대 메시지 길이 제한, 차단 확인, 알림 생성 규칙은 `apps/chat/services.py`의 `send_message`(120~156행) 한 곳에만 있다.

### 3.3 ASGI · WebSocket 라우팅 (`config/asgi.py`)

```python
django_asgi_app = get_asgi_application()          # 13행: 앱 레지스트리 먼저 로드
...
application = ProtocolTypeRouter({                 # 21~28행
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
```

중간 버전에서 지적한 `get_asgi_application()` 중복 호출을 없애고, 한 번 만든 `django_asgi_app`을 HTTP에 재사용한다. WebSocket은 `AllowedHostsOriginValidator`로 Origin을 검사한 뒤 세션 인증(`AuthMiddlewareStack`)을 거쳐 `/ws/chat/<room_id>/`로 라우팅된다. `INSTALLED_APPS` 맨 위의 `daphne`(`base.py` 22행) 덕분에 개발 중에는 `runserver`만으로 WebSocket까지 동작한다.

### 3.4 URL 구성 (`config/urls.py`)

각 앱은 `app_name` namespace로 include하고, 템플릿은 `{% url 'products:detail' pk %}`처럼 이름으로 참조한다.

| prefix | 앱 | 주요 경로 |
|---|---|---|
| `/` | core | `/`(홈), `/state/`(헬스체크), `/dev/styleguide/`(DEBUG 전용) |
| `/accounts/`, `/users/` | accounts | 가입 · 중복 확인 · 동네 옵션 · 로그인 · 로그아웃 · 마이페이지 · 프로필 수정 · `/users/<username>/` |
| `/products/` | products | 목록/검색, 등록, 상세, 수정, 삭제, 찜 토글, 상태 변경 |
| `/chats/` | chat | 목록, 채팅방, 채팅 시작, 읽음 처리 (+ `/ws/chat/<room_id>/`) |
| `/trades/` | trades | 거래완료, 후기 작성 |
| `/notifications/` | notifications | 목록, 드롭다운, 모두 읽음, 배지, 이동 |
| `/moderation/` | moderation | 상품/사용자 신고, 차단 토글, 차단 목록 |
| `/ai/` | ai | 설명 생성, 사진 인식, 협상 초안, 사기 재분석 |

중간 버전의 404 버그 원인이던 `LOGIN_URL`은 `base.py` 86행에서 `"accounts:login"`으로 지정했다.

---

## 4. 데이터 모델

### 4.1 모델 목록

공통 추상 모델 `apps.core.models.TimeStampedModel`(`created_at`, `updated_at`)을 상속하는 모델과 그렇지 않은 모델을 합쳐 **8개 앱에 모델 14개**가 있다.

| 앱 | 모델 | 핵심 필드 · 제약 |
|---|---|---|
| accounts | `Region` | `code`(행정동 코드, unique, null 허용), `sido`·`sigungu`·`dong`, `UniqueConstraint(sido, sigungu, dong)` |
| accounts | `Profile` | `user`(1:1), `nickname`(unique), `region`(FK, SET_NULL), `bio`, `avatar_url`, `manner_temperature`(Decimal, 기본 36.5) |
| products | `Category` | `slug`(unique), `name`, `icon`, `order` — 데이터 마이그레이션으로 15종 시드 |
| products | `Product` | `seller`, `category`(PROTECT), `region`, `title`, `content`, `price`, `negotiable`, `condition`(5단계), `status`(SELLING/RESERVED/SOLD), `view_count`, `buyer`; 인덱스 2개 |
| products | `ProductImage` | `product`(FK), `image_url`, `order` — 첫 번째가 대표 사진 |
| products | `Wishlist` | `UniqueConstraint(user, product)` |
| products | `RecentView` | `viewed_at`(auto_now), `UniqueConstraint(user, product)`, 사용자당 50개 유지 |
| chat | `ChatRoom` | `product`, `seller`, `buyer`, `last_message_at`; `UniqueConstraint(product, buyer)`; 정렬 `-last_message_at` |
| chat | `ChatMessage` | `room`, `sender`, `content`, `is_read`, `read_at`; 인덱스 `(room, created_at)`, `(room, is_read)` |
| trades | `Review` | `product`, `reviewer`, `reviewee`, `rating`(1~5 검증), `manner_tags`(JSON), `UniqueConstraint(product, reviewer)` |
| notifications | `Notification` | `user`, `kind`(5종), `message`, `url`, `is_read`; 인덱스 `(user, is_read)` |
| moderation | `Report` | `reporter`, `product` 또는 `reported_user`, `reason`(5종), `status` |
| moderation | `Block` | `blocker`, `blocked`, `UniqueConstraint(blocker, blocked)` |
| ai | `AIResultCache` · `AIUsageLog` · `FraudAnalysis` | 6장에서 설명 |

### 4.2 설계상 주요 결정

- **기본 `auth.User` 유지 + `Profile` 1:1**: 커스텀 User로 바꾸면 운영 DB의 기존 회원 테이블과 충돌한다. 기존 사용자를 그대로 로그인시키기 위해 `User`는 유지하고 닉네임·동네·매너온도 같은 부가 정보만 `Profile`로 분리했다. 첫 접속 때 프로필이 없으면 자동으로 만든다.
- **이미지를 별도 모델로 분리**: 중간 버전의 단일 `image_url` 필드를 `ProductImage`(순서 `order` 포함)로 바꿔 다중 이미지와 대표 사진을 지원한다. 개발 환경에서는 `/media/...` 상대 경로도 저장해야 해서 `URLField` 대신 `CharField`를 썼다(`products/models.py` 116~117행).
- **채팅방은 (상품, 구매자)당 하나**: `UniqueConstraint(product, buyer)`(`chat/models.py` 31~33행)와 서비스의 `IntegrityError` 처리로 동시 클릭에도 방이 중복 생성되지 않는다.
- **집계는 annotate 우선**: `Product.wish_count` / `chat_count` 프로퍼티(`products/models.py` 95~109행)는 셀렉터가 붙인 `num_wishes` / `num_chats` annotate 값이 있으면 그것을 쓰고, 없을 때만 COUNT 쿼리를 실행한다. 중간 버전의 "상품 수 × 2번 추가 쿼리" 문제를 이렇게 해결했다.
- **자주 쓰는 조회에 인덱스**: 목록 정렬(`status, created_at`), 카테고리 필터, 채팅 메시지 조회·안 읽은 수, 알림 배지에 각각 인덱스를 두었다.

### 4.3 관계 요약 (ERD)

```
User 1─1 Profile N─1 Region
User 1─N Product N─1 Category        Product N─1 Region
Product 1─N ProductImage             Product 1─1 FraudAnalysis
User N─M Product  (Wishlist, RecentView 중간 테이블)
Product 1─N ChatRoom N─1 User(seller / buyer)      ChatRoom 1─N ChatMessage N─1 User(sender)
Product 1─N Review  (reviewer → reviewee, 양방향 후기)
User 1─N Notification       User N─M User (Block)       Report → Product 또는 User
```

### 4.4 동네 데이터 마이그레이션

동네 목록은 통계청 SGIS 행정동 경계(2026-10-01 기준)를 정리한 CSV(`apps/accounts/data/`)를 데이터 마이그레이션 `0004_load_hangjeongdong`이 읽어 **3,559개 행정동**을 넣는다. 중간 이후 운영 DB에 이미 예전 시드(41개)가 들어 있었기 때문에, 이름이 같은 동네는 코드만 채우고, 목록에 없는 예전 이름은 **누군가의 프로필·상품이 참조하면 남기고(새로 고르는 목록에는 숨김) 아무도 안 쓰면 지우는** 방식으로 기존 데이터를 깨지 않게 했다. 데이터 출처(공공누리 제1유형, CC BY 4.0)는 CSV 머리말과 README에 표기했다.

---

## 5. 기본 기능 구현

### 5.1 회원 · 프로필 · 동네

- **회원가입**(`accounts/forms.py`, `services.register_user`): 아이디·닉네임은 입력 중 HTMX로 중복을 확인한다(`/accounts/signup/check/`). 닉네임은 띄어쓰기를 허용하되 연속 공백을 정규화하고, 공백·대소문자를 무시하고 중복을 비교한다.
- **동네 3단 선택**: 시/도를 고르면 HTMX가 `/accounts/regions/options/?level=sigungu&sido=...`를 불러 다음 `<select>`의 `<option>`을 채운다. 가입·프로필 수정·상품 등록/수정·목록 필터가 같은 컴포넌트(`templates/components/region_select.html`)를 공유한다. 조회 로직은 `apps/accounts/regions.py`에 모았고, 입력값은 `clean_param()`으로 길이 제한과 NUL 문자 제거를 거친다(PostgreSQL은 NUL이 든 문자열로 쿼리하면 오류가 난다).
- **마이페이지 / 판매자 프로필**: 판매 상품·찜·받은 후기·최근 본 상품을 탭으로 보여 주고, 판매자 프로필에는 매너온도, 판매·거래완료 수, 받은 후기 요약을 표시한다.

### 5.2 상품 등록 · 수정 · 삭제와 다중 이미지

`apps/products/services.py`의 `create_product`(66~78행)는 상품 저장과 이미지 저장을 하나의 트랜잭션으로 묶는다.

```python
def create_product(seller, data, images=()):
    with transaction.atomic():
        product = Product(seller=seller, **{k: v for k, v in data.items() if k in EDITABLE_FIELDS})
        if product.price == 0:
            product.negotiable = False          # 나눔 상품은 가격 제안 불가
        product.save()
        _save_images(product, list(images))     # 업로드 실패 → StorageError → 상품도 롤백
    run_fraud_analysis(product)                 # 트랜잭션 밖: 실패해도 저장에는 영향 없음
    return product
```

- `EDITABLE_FIELDS`(21행) 화이트리스트로 폼 밖의 필드(예: `seller`, `view_count`)가 덮어써지지 않게 했다.
- `update_product`(81~108행)는 **수정 전 가격을 DB에서 다시 읽는다**. ModelForm 검증이 인스턴스 값을 이미 바꿔 두기 때문에 인스턴스의 가격으로 비교하면 가격 변동을 놓친다. 가격이 바뀌면 `notify_price_change`가 찜한 사용자에게 "가격이 ○원에서 ○원으로 내려갔어요" 알림을 보낸다.
- 이미지를 지우면 `_renumber_images`(43~52행)가 순서를 0부터 다시 매겨 첫 번째 사진이 항상 대표 사진이 되게 한다. 폼(`products/forms.py` 12행)에서 최대 10장으로 제한한다.

### 5.3 이미지 업로드 보안 (`apps/core/storage.py`)

중간 버전의 `storage.py`는 import 시점에 Supabase 클라이언트를 만들었고 파일 검증이 없었다. 기말 버전은 다음과 같이 바꿨다.

| 검사 | 위치 | 내용 |
|---|---|---|
| 지연 생성 | 42~53행 | Supabase 클라이언트를 실제 업로드 시점에 한 번만 만든다. 설정이 없으면 `StorageError` |
| 확장자 · 크기 | 60~71행 | 허용 확장자 7종, 10MB 이하, 빈 파일 거부 |
| **실제 내용 판별** | 74~95행 | Pillow로 파일을 열어 `verify()`하고 실제 포맷에서 저장 확장자를 정한다. HEIC/HEIF는 `ftyp` 박스 브랜드로 판별. 확장자만 `.jpg`로 바꾼 HTML/JS 파일을 막는다 |
| 경로 조작 방지 | 104~107행 | 폴더 이름에서 `..`, `.`, 빈 조각 제거 |
| Content-Type | 21~29, 155행 | 클라이언트가 보낸 값은 쓰지 않고, 판별한 확장자에서 결정 |

파일 이름은 `uuid4().hex`로 새로 만들어 덮어쓰기와 이름 추측을 막는다(137행).

### 5.4 목록 · 검색 · 필터 · 정렬 (`apps/products/selectors.py`)

`search_products`(154~173행)는 검색어(공백으로 나눈 최대 5단어, 각 단어가 제목 또는 본문에 포함), 카테고리, 동네(특정 동 / 시·군·구 전체 / 시·도 전체), "거래 가능만", 정렬 4종(최신·인기·낮은 가격·높은 가격)을 조합한다. 결과는 `with_card_data`(23~35행)를 거친다.

```python
def with_card_data(queryset):
    return (
        queryset.select_related("region", "category")
        .prefetch_related(Prefetch("images", queryset=ProductImage.objects.order_by("order", "id")))
        .annotate(num_wishes=Count("wishlists", distinct=True),
                  num_chats=Count("chat_rooms", distinct=True))
    )
```

상품 카드가 쓰는 동네명·썸네일·찜 수·채팅 수를 **쿼리 몇 개로 한꺼번에** 가져오므로 상품 수가 늘어도 쿼리 수가 늘지 않는다. 두 집계를 동시에 JOIN하면 행이 곱해지므로 `distinct=True`를 붙였다.

목록은 20개씩 페이지네이션하고(`PAGE_SIZE`, 13행), 뷰(`products/views.py` 118~183행)는 HTMX 요청이면 그리드 조각(`partials/product_grid.html`)만 돌려준다. "더 보기"를 누르면 다음 페이지가 기존 그리드 뒤에 붙는다.

모든 목록 조회는 `visible_products`(38~44행)에서 시작해 **차단 관계(내가 차단했거나 나를 차단한) 사용자의 상품을 제외**한다. 홈의 인기 상품(`popular_products`, 182~190행)은 사기 위험도가 `HIGH`인 상품을 추천에서 뺀다.

### 5.5 찜 · 조회수 · 최근 본 상품

- **찜 토글**(`services.toggle_wishlist`, 137~149행): 먼저 삭제를 시도해 지워졌으면 해제, 아니면 생성한다. 동시에 두 번 눌러 `IntegrityError`가 나도 무시한다. 본인 상품은 찜할 수 없다. HTMX 응답은 하트 버튼 조각을 바꾸고 `HX-Trigger` 헤더로 "찜했어요" 토스트를 띄운다.
- **조회수**(`record_view`, 181~189행): 중간 버전처럼 `F("view_count") + 1`로 원자적으로 올리되, **판매자 본인의 조회는 세지 않는다**. 로그인 사용자는 `RecentView`를 `update_or_create`로 갱신하고, 50개를 넘는 오래된 기록은 지운다.

### 5.6 판매 상태 · 거래완료 · 후기 · 매너온도 (`apps/trades/services.py`)

- **상태 변경**: 판매중 ↔ 예약중은 상세 화면의 셀렉트로 바로 바꾼다(`products/services.change_status`). 거래완료는 구매자를 골라야 하므로 별도 화면으로 보낸다. 후기가 남은 거래는 다시 판매중으로 되돌릴 수 없게 막아 같은 상품으로 후기를 여러 번 받는 것을 방지했다.
- **거래완료**(`complete_trade`, 81~118행): 구매자는 **이 상품으로 판매자와 채팅한 사용자** 중에서만 고를 수 있고, 차단 관계는 제외한다. 동시에 두 번 눌러도 한 번만 처리되도록 `select_for_update()`로 행을 잠근다.

```python
with transaction.atomic():
    locked = Product.objects.select_for_update().get(pk=product.pk)
    if locked.status == Product.Status.SOLD:
        raise TradeError("이미 거래완료된 상품이에요.")
    locked.status = Product.Status.SOLD
    locked.buyer = buyer
    locked.save(update_fields=["status", "buyer", "updated_at"])
```

- **후기**(`create_review`, 153~198행): 판매자와 지정된 구매자가 **서로** 한 번씩 남길 수 있다. 별점 1~5와 매너 태그(받는 사람이 판매자/구매자인지에 따라 목록이 다름)를 서버에서 다시 검증한다.
- **매너온도**(`apply_manner_rating`, 207~220행): 별점 5 → +0.5, 4 → +0.2, 3 → 0, 2 → −0.3, 1 → −0.6℃를 반영하고 0~99℃로 제한한다. 프로필 행을 `select_for_update()`로 잠가 동시 후기에도 값이 유실되지 않는다.

### 5.7 실시간 채팅 (`apps/chat/`)

**서버 — consumer**(`consumers.py`): 중간 버전의 async consumer를 동기 `JsonWebsocketConsumer`로 바꿔 ORM과 서비스 함수를 그대로 호출한다. 연결 시 로그인 여부, 방 존재 여부, 참여자 여부를 검사하고, 실패 사유마다 애플리케이션 정의 닫기 코드(4401/4403/4404, 19~21행)를 보낸다. 클라이언트 → 서버 메시지는 `message`(전송)와 `read`(읽음) 두 종류다.

**서버 — 서비스**(`services.py`):

- `send_message`(120~156행): 참여자 확인 → 공백 제거 · 빈 메시지 · 1,000자 제한 → 차단 확인 → 저장과 `last_message_at` 갱신, 상대방 알림을 한 트랜잭션으로 처리한다. 같은 방의 안 읽은 새 메시지 알림은 `collapse_key`로 **하나로 합친다**.
- `mark_room_read`(159~167행): 상대가 보낸 안 읽은 메시지를 읽음 처리하고, `broadcast_read`가 방 그룹에 읽은 메시지 id를 보내 보낸 사람 화면에 "읽음"이 표시된다.
- 채널 레이어 전송 실패는 로그만 남기고 저장은 유지한다(173~180행).

**클라이언트**(`static/js/chat.js`):

- **자동 재연결**: `onclose`에서 치명적 닫기 코드(로그인 필요, 권한 없음, 방 없음)가 아니면 1초 → 2초 → 4초 … 최대 15초 간격(지수 백오프, 314~320행)으로 다시 연결한다.
- **놓친 메시지 보충**: 재연결되면 `catchUp()`(265~272행)이 `?after=<마지막 메시지 id>`로 끊긴 동안의 메시지를 HTML 조각으로 받아 붙인다(`chat/views.py` 116~125행).
- **HTTP 대체 전송**: WebSocket이 끊긴 상태에서도 폼 POST로 메시지를 보낼 수 있다.
- 탭이 보이지 않을 때 온 메시지는 읽음 처리를 미뤘다가 `visibilitychange`에서 처리한다.
- 메시지 본문은 계속 `textContent`로 넣어 XSS를 막는다.

채팅 목록은 `-last_message_at` 순으로 정렬되고 마지막 메시지 미리보기와 안 읽은 수 배지를 보여 준다. 헤더의 채팅 아이콘에도 전체 안 읽은 수가 표시된다.

### 5.8 알림 (`apps/notifications/`)

`notify(user, kind, message, url, collapse_key)`(`services.py` 9~34행) 하나로 모든 앱이 알림을 만든다. 종류는 가격 변동, 새 메시지, 거래 후기, 거래 상태, 시스템 5가지다. `collapse_key`가 있으면 같은 사용자·종류·URL의 **안 읽은** 알림을 새로 만들지 않고 내용과 시각만 갱신해 맨 위로 올린다. 헤더 배지는 HTMX로 주기적으로 갱신되고, 벨을 누르면 드롭다운 조각을 불러온다. 알림을 누르면 `/notifications/<pk>/go/`가 읽음 처리 후 대상 페이지로 보낸다.

### 5.9 신고 · 차단 (`apps/moderation/`)

- 상품과 사용자를 사유 5종(사기 의심, 판매 금지 물품, 욕설/비매너, 광고/도배, 기타)으로 신고할 수 있고, 관리자 페이지에서 검토 상태를 관리한다.
- `blocked_user_ids(user)`(`services.py` 9~19행)는 **양방향**(내가 차단 + 나를 차단) 사용자 id 집합을 돌려준다. 차단 관계가 있으면 상대의 상품이 목록·추천·최근 본 상품에서 숨겨지고, 새 채팅 시작·메시지 전송·찜·거래 상대 선택·후기 작성이 모두 서비스 단계에서 막힌다.

### 5.10 공통 처리

- **HTMX 인증 처리**(`products/views.py` 40~58행 `login_required_htmx`): HTMX 요청에서 로그인 페이지 HTML을 조각 자리에 끼워 넣지 않도록, 비로그인이면 `HX-Redirect` 헤더로 로그인 페이지 이동을 지시한다.
- **안전한 리다이렉트**: `next` 값은 같은 호스트일 때만 따른다(`_safe_next`).
- **에러 페이지**: `403.html` / `404.html` / `500.html`을 디자인 시스템에 맞춰 만들었다.
- **헤더 배지 장애 격리**: `apps.core.context_processors.nav`는 DB 오류가 나도 페이지 전체가 깨지지 않게 예외를 삼킨다.
- **데모 데이터**(`python manage.py seed_demo`): 사용자 5명, 상품 24개, 채팅방 8개, 메시지 23개, 알림 26개를 만든다. 모든 쓰기가 실제 서비스 함수를 거치므로 알림·매너온도·사기 분석이 실제 흐름과 똑같이 생긴다. 개발 환경 + SQLite + 로컬 저장소에서만 실행되도록 안전장치를 두었다.

---

## 6. AI 기능 4종 (Gemini)

### 6.1 공통 구조

```
apps/ai/views.py ─┐
다른 앱 서비스 ────┼─▶ apps/ai/services/{description, vision, fraud, negotiation}.py
                  │        └─ apps/ai/prompts/*.py  (프롬프트 · JSON 스키마 · VERSION)
                  └─▶ apps/ai/cache.py: cached_call ─▶ apps/ai/client.py: GeminiClient.generate_json
                                         ├─ AIResultCache (응답 재사용)
                                         └─ AIUsageLog   (모든 호출 기록)
```

- **SDK는 `client.py`에서만** 부른다. 뷰나 다른 앱은 반드시 `apps.ai.services`를 거친다.
- **항상 JSON으로 받는다**: `response_mime_type="application/json"`과 `response_schema`를 지정하고(`client.py` 105~111행), 각 서비스의 검증 함수(`normalize`, `validate_raw`, `_parse_ai`)가 길이·허용값·점수 범위를 다시 검사한다. 예를 들어 사진 인식은 **DB에 있는 카테고리 slug 안에서만** 고르도록 스키마 enum을 만들고, 그래도 목록 밖 값이 오면 '기타'로 보정한다(`vision.py` 43~70행).
- **오류를 한국어 안내로 변환**: 시간 초과, 요청 과다(429), 서버 오류(5xx), 응답 해석 실패, 안전 필터 차단, 네트워크 오류를 각각 사용자용 문구를 가진 `AIServiceError`로 바꾼다(`client.py` 22~45행). 429·5xx는 한 번 재시도한다.
- **AI가 없어도 서비스는 동작**: `GEMINI_API_KEY`가 없으면 `AIUnavailableError`로 "지금은 AI 기능을 쓸 수 없어요. 직접 입력해 주세요."만 표시되고 나머지 기능은 그대로 동작한다. 테스트 실행 중에는 실제 호출이 자동으로 차단된다.
- **AI 결과는 자동으로 덮어쓰지 않는다**: 결과 카드에서 사용자가 **적용** 버튼을 눌러야 폼에 반영된다.

### 6.2 결과 캐싱과 사용 기록 (`apps/ai/cache.py`)

`cached_call`(76~113행)은 (기능, 모델, 프롬프트 버전·텍스트·이미지 바이트)의 sha256 해시가 같으면 저장된 응답을 재사용한다. 해시를 만들 때 각 조각 앞에 길이를 넣어 조각 경계가 섞여 다른 입력이 같은 해시가 되는 것을 막았다(41~48행).

```python
def make_input_hash(feature, model_name, payload_parts):
    digest = hashlib.sha256()
    for part in (feature, model_name, *payload_parts):
        data = _to_bytes(part)
        digest.update(len(data).to_bytes(8, "big"))   # 경계 구분
        digest.update(data)
    return digest.hexdigest()
```

- 검증 함수(`validate`)를 통과하지 못한 응답은 **캐시에 저장하지 않고**, 예전에 저장된 잘못된 캐시는 무시하고 새로 호출한다.
- 캐시 적중을 포함한 모든 호출이 `AIUsageLog`에 성공 여부, 입력/출력 토큰, 지연 시간, 오류와 함께 남고, `costs.py`가 토큰 기반 예상 비용을 계산한다. 관리자 페이지에서 확인할 수 있다.
- 사용자가 **다시 생성**을 누를 때만 캐시를 건너뛰며, 이때는 temperature를 0.5 → 0.9로 올려 다른 결과가 나오게 한다(`description.py` 53행).

### 6.3 기능 ① 사진 + 키워드 판매글 생성 (`services/description.py`)

사진(최대 2장)이나 키워드 중 하나 이상과 (선택) 카테고리를 받아 `{title, content, suggested_tags}`를 만든다. 업로드 이미지는 `apps/ai/images.py`가 긴 변 1,024px JPEG로 정규화해 토큰 비용을 줄인다. 응답은 제목 100자·본문 2,000자로 자르고, 태그는 `#`과 공백을 제거해 최대 5개만 남긴다. 제목이나 본문이 비면 잘못된 응답으로 보고 오류를 낸다(28~35행).

### 6.4 기능 ② 사진 인식 자동 분류 (`services/vision.py`)

사진 1~2장으로 카테고리·제목·상품 상태(5단계)·신뢰도를 추천한다. 시스템 프롬프트와 스키마를 **현재 DB의 카테고리 목록으로 매번 만들고**(79~80행), 캐시에는 원본 응답을 저장한 뒤 카테고리 pk 같은 화면용 값은 매번 현재 DB 기준으로 보강한다(89~92행). 카테고리가 바뀌어도 오래된 캐시가 잘못된 pk를 돌려주지 않는다.

### 6.5 기능 ③ 사기 의심 게시글 탐지 (`services/fraud.py`)

**규칙 + 가격 이상치 + AI 판단**을 결합한 3단 구조다.

1. **텍스트 규칙**(68~98행): 선입금 요구(40점), 외부 메신저 유도(30점), 안전결제 링크 사칭(40점), 개인정보 요구(40점), 계좌번호(35점), 입금 재촉(20점), 택배만 고집(15점), 비대면 사유(15점), 외부 링크(15점), 개인 연락처(20점).
2. **오탐 줄이기**: "카톡은 안 해요", "선입금 x"처럼 매치 직후 10글자 안에 부정 표현이 있으면 무시한다(`NEGATION_RE`, 44~48행). 공백으로 띄운 숫자("250 260 270")는 근처에 '계좌·입금' 같은 말이 있을 때만 계좌로 본다(118~135행). 아주 긴 글로 CPU를 오래 잡지 않도록 5,000자까지만 검사한다.
3. **가격 이상치**(184~199행): 아이폰·맥북·다이슨 같은 고가 상품이 5만 원 미만이면서 케이스·부품 같은 액세서리 단어가 없으면 25점, 같은 카테고리 최근 상품 가격 중앙값의 15% 미만이면 25점.
4. **AI 판단**: 규칙 결과와 가격 참고 문장을 프롬프트에 넣어 0~100점과 근거 3개를 받는다.
5. **점수 결합**(`combine_scores`, 219~231행): AI 점수를 하한으로 두고 규칙 점수를 절반 가중으로 반영한다. 규칙 점수가 70 이상이면 AI가 낮게 봐도 규칙 점수를 유지한다. 30점 이상은 "주의", 70점 이상은 "위험"이다.

```python
score = max(ai_score, round((rule_score + ai_score) / 2))
if rule_score >= LEVEL_HIGH:
    score = max(score, rule_score)
```

상품 등록·수정 요청 안에서 실행되므로 **8초 타임아웃, 재시도 없음**으로 짧게 한 번만 시도한다(26~27행). AI가 실패하면 규칙 결과(`source=RULE`)로 저장하고 다음 저장이나 '다시 분석하기' 때 다시 시도한다. 분석 결과는 상품당 하나(`FraudAnalysis`, OneToOne)이며, 분석에 쓰이는 필드와 프롬프트 버전의 해시(`content_hash`)가 같고 AI 판단까지 끝났으면 다시 분석하지 않는다(287~291행).

위험도가 "주의" 이상이면 상품 상세에 경고 배너가 뜨고 "왜 그렇게 판단했나요?"를 펼치면 근거를 볼 수 있다. 채팅 메시지에도 **AI 호출 없이** 같은 텍스트 규칙(`check_text_rules`)을 적용해 메시지 아래에 경고를 표시한다.

### 6.6 기능 ④ 가격 협상 답장 초안 (`services/negotiation.py`)

- **감지는 규칙으로**(AI 없음): "깎아", "네고", "얼마까지", "45만원에 될까요" 같은 패턴을 정규식으로 찾는다(31~38행). 숫자 덩어리의 맨 앞에서만 매치가 시작되도록 lookbehind 가드(`_NUM_START`, 20행)를 넣어, 긴 숫자열에서 정규식 재시도가 제곱으로 늘어나는 문제(ReDoS 성격)를 막았다. 검사 길이도 500자로 제한했다.
- **제시가 추출**: "35만 5천원", "355,000원", "2.5만" 같은 표현을 원 단위로 바꾸고, "2만원 빼 주세요"처럼 금액 뒤에 '빼/깎/할인'이 오면 할인액으로 보고 판매가에서 뺀다(68행~).
- **초안 생성**: 판매자가 메시지 아래의 **AI 답장 초안** 버튼을 누르면 상품 정보, 판매가, 제시가, 최근 대화 10개를 바탕으로 "정중한 거절" · "소폭 양보" · "역제안" 세 가지 톤의 답장 3개를 만든다. 초안을 누르면 입력창에 채워지고, 보내기 전에 판매자가 고칠 수 있다. 이 버튼은 판매자에게만 보이고 뷰에서도 판매자만 호출할 수 있다.

---

## 7. 화면 구성

### 7.1 설계 개요

- **`base.html` 상속**: 모든 페이지가 `{% extends "base.html" %}`로 헤더(로고 · 카테고리 · 검색 · 글쓰기 · 채팅/알림 배지 · 프로필), 토스트 영역, 푸터를 공유한다. 중간 버전에서 9개 템플릿이 `<head>`를 반복하던 문제를 없앴다.
- **컴포넌트화**: `templates/components/`에 상품 카드, 아바타, 상태 배지, 매너온도, 모달, 페이지네이션, 빈 상태, 폼 필드, 아이콘, 동네 선택 등 재사용 조각을 두었다. `/dev/styleguide/`(DEBUG 전용)에서 모든 컴포넌트를 한 화면에 확인할 수 있다.
- **Tailwind 디자인 토큰**: `tailwind.config.js`와 `static/src/input.css`(773행)에 색상·간격·그림자·버튼/입력/배지 클래스를 정의했다. 빌드 결과 `static/css/app.css`를 커밋해 배포 시 npm 빌드가 필요 없다.
- **HTMX 부분 갱신**: 찜 토글, 목록 더 보기, 판매 상태 변경, 중복 확인, 동네 단계 선택, 알림 드롭다운·배지, 신고 폼, AI 협상 초안·사기 재분석이 페이지 새로고침 없이 동작한다. 서버는 `HX-Trigger` 헤더로 토스트를, `HX-Redirect`로 이동을 지시한다.
- **반응형 · 접근성**: 모바일에서 그리드 열 수와 헤더가 바뀌고, 아이콘 버튼과 섹션에 `aria-label` / `aria-labelledby`를 달았다(템플릿 전체 72곳). 디자인 접근성 지적 사항은 리뷰 수정 커밋 `346e3af`에서 함께 고쳤다.

### 7.2 페이지별 화면

**홈** — 내 동네 최신 상품, 인기 상품(사기 위험 '높음' 제외), 최근 본 상품, 카테고리 바로가기.

![홈 화면 (demo_minji 로그인)](images/01_home.png)

**상품 목록** — 검색어 · 카테고리 · 동네 3단 필터 · 거래 가능만 · 정렬, 20개씩 더 보기.

![상품 목록 화면](images/02_product_list.png)

**로그인 · 회원가입** — 가입 화면에서 아이디·닉네임 중복을 입력 중에 확인하고, 동네를 3단으로 고른다.

![로그인 화면](images/03_login.png)

![회원가입 화면 (동네 3단 선택)](images/04_signup.png)

**상품 상세** — 사진 슬라이더, 판매자 카드(매너온도), 상태 배지, 찜 · 채팅 버튼, 조회/찜/채팅 수, 같은 판매자의 다른 상품.

![상품 상세 화면](images/05_product_detail.png)

**사기 의심 경고 배너** — `demo_quick`의 의심 판매글. 선입금 · 카톡 아이디 · 계좌번호 · 택배만 등 규칙이 걸려 "위험" 배너가 표시된다.

![사기 의심 경고 배너](images/06_fraud_banner.png)

**상품 등록 + AI 판매글 도우미** — 사진 최대 10장, 키워드 입력 후 "AI로 작성하기" / "사진으로 분류하기". 결과 카드의 **적용**을 눌러야 입력칸이 바뀐다.

![상품 등록 화면과 AI 판매글 도우미](images/07_product_form_ai.png)

**채팅 목록** — 마지막 메시지 순 정렬, 미리보기, 안 읽은 수.

![채팅 목록 화면](images/08_chat_list.png)

**채팅방 (판매자 화면) — 가격 협상 감지** — 구매자의 "45만원에 네고 될까요?" 메시지 아래에 판매자에게만 **AI 답장 초안** 버튼이 표시된다. 보낸 메시지에는 "읽음"이 표시되고, 상단에서 판매 상태 변경과 거래완료를 할 수 있다.

![채팅방 – 가격 협상 감지](images/09_chat_negotiation.png)

**채팅방 (구매자 화면) — 메시지 사기 규칙 경고** — 판매자가 보낸 "카톡 아이디 … 선입금하시면 바로 택배" 메시지 아래에 규칙 기반 경고가 표시된다.

![채팅방 – 메시지 사기 경고](images/09b_chat_fraud.png)

**마이페이지 · 판매자 프로필**

![마이페이지](images/10_mypage.png)

![판매자 프로필](images/11_seller_profile.png)

**알림 목록**

![알림 목록](images/12_notifications.png)

**거래완료 (구매자 선택)** — 이 상품으로 채팅한 이웃 중에서 구매자를 고르거나 "채팅 밖에서 거래"를 선택한다.

![거래완료 – 구매자 선택](images/13_trade_complete.png)

**신고하기**

![상품 신고 화면](images/14_report_form.png)

**모바일 (iPhone 13 에뮬레이션) 상품 목록**

![모바일 상품 목록](images/15_mobile_list.png)

> AI 기능의 실제 생성 결과 화면은 Gemini API 키가 필요해 이 캡처 환경(키 없음)에서는 촬영하지 않았다. 키가 없을 때는 버튼을 눌러도 "지금은 AI 기능을 쓸 수 없어요. 직접 입력해 주세요." 안내가 표시되며, 사기 탐지 배너는 AI 없이 규칙 기반 결과(`source=RULE`)로 동작한다.

---

## 8. 테스트

### 8.1 구성과 결과

중간 버전에는 테스트가 없었다. 기말 버전은 Django `TestCase`와 Channels의 `WebsocketCommunicator`로 **410개**의 테스트를 작성했다.

| 앱 | 테스트 수 | 주요 검증 내용 |
|---|---:|---|
| accounts | 105 | 가입 검증 · 닉네임 정규화/중복, 로그인 리다이렉트, 프로필 수정, 동네 3단 선택 · 파라미터 정리, 행정동 마이그레이션 |
| ai | 70 | 서비스 4종 정규화 · 검증, 사기 규칙(부정 표현 · 계좌 문맥 오탐), 협상 감지 · 제시가 추출, 캐시 적중/무효 캐시 무시, 오류 → 안내 문구, 뷰 권한 |
| products | 55 | 등록/수정/삭제 권한, 다중 이미지 · 순서, 가격 변동 알림, 검색 · 필터 · 정렬, N+1 쿼리 수, 찜, 차단 상품 숨김 |
| chat | 55 | 방 생성 · 중복 방지, 메시지 검증, 읽음 처리, **WebSocket 연결 · 권한 닫기 코드 · 실시간 전송**, 놓친 메시지 조각 |
| trades | 44 | 거래완료 구매자 검증, 중복 처리 방지, 후기 권한 · 태그 검증, 매너온도 계산 · 범위 제한 |
| core | 32 | 업로드 검증(가짜 이미지 · 경로 조작 · Content-Type), 템플릿 필터, 헬스체크, 스타일가이드, `seed_demo` 안전장치 |
| notifications | 28 | 알림 생성 · 합치기(`collapse_key`), 배지 · 드롭다운 · 모두 읽음 |
| moderation | 21 | 신고, 양방향 차단, 차단 시 채팅 · 찜 · 거래 제한 |

```text
$ python manage.py test
Ran 410 tests in 87.380s
OK (skipped=1)
```

skip된 1개는 실제 Gemini API를 호출하는 라이브 스모크 테스트(`apps/ai/tests/test_views.py`의 `LiveSmokeTests`)로, `RUN_LIVE_AI=1`을 줄 때만 실행된다. 그 외 테스트에서는 실제 AI 호출이 자동으로 차단되고 가짜 클라이언트(`apps/ai/tests/helpers.py`)로 응답을 흉내 낸다.

### 8.2 테스트 작성 원칙

- 테스트는 개발 설정(SQLite)으로 실행되므로 운영 DB에 영향을 주지 않는다.
- 쿼리 수가 중요한 화면(홈, 상품 목록, 채팅방, 거래완료 구매자 목록)은 `CaptureQueriesContext`로 데이터가 늘어도 쿼리 수가 일정한지(N+1 없음) 확인했다.
- 보안 관련 입력(이미지로 위장한 HTML, 폴더 경로 조작, 외부 `next` URL, 다른 상품의 이미지 삭제 시도)을 직접 넣어 거부되는지 확인했다.
- AI 실패 경로(사기 분석 실패 시에도 상품 저장 성공 등)를 별도로 검증했다.

---

## 9. 배포

### 9.1 Render 설정

| 항목 | 값 |
|---|---|
| Build Command | `./build.sh` (`pip install` → `collectstatic` → `migrate` → `ensure_admin`) |
| Start Command | `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker` |
| Health Check Path | `/state/` |
| Python | 3.13 (`.python-version`) |

- Tailwind CSS는 커밋된 `app.css`를 쓰므로 빌드 중 npm을 실행하지 않는다.
- 정적 파일은 WhiteNoise의 `CompressedManifestStaticFilesStorage`(`prod.py`)로 압축·해시된 파일명을 제공한다. WhiteNoise 미들웨어는 문서 권장대로 `SecurityMiddleware` 바로 다음(`base.py` 43행)으로 옮겼다.
- `staticfiles/`, `media/`, `db.sqlite3`, `.env`는 `.gitignore`에 등록했다.
- **관리자 계정**: Render 무료 플랜에는 Shell이 없어서, 환경 변수 `DJANGO_SUPERUSER_*`가 있으면 빌드 때 `ensure_admin` 명령이 계정을 만들거나 비밀번호를 재설정한다.

### 9.2 운영 DB 안정화

Supabase 풀러는 한동안 쓰지 않은 연결을 서버 쪽에서 끊는다. 연결 재사용(`CONN_MAX_AGE = 60`)만 켜 두면, 30초마다 polling하는 알림 배지 요청이 끊긴 연결을 집어 들어 간헐적으로 500이 났다. `CONN_HEALTH_CHECKS = True`로 재사용 전에 연결 상태를 확인하게 고쳤고(`f1c2fe5`), 풀러의 transaction 모드에서는 서버측 커서가 유지되지 않으므로 `DISABLE_SERVER_SIDE_CURSORS = True`도 지정했다(`prod.py`).

### 9.3 기존 운영 DB 호환

리팩토링 버전은 기본 `auth.User`를 유지하고 새 앱 테이블(`accounts_*`, `products_*` …)만 **추가**한다. 중간 버전 스키마(`market_*`)가 있는 DB에 `migrate`해도 충돌 없이 새 테이블만 만들어지며, 기존 회원은 그대로 로그인할 수 있다. 중간 버전 스키마에 데이터를 넣은 DB로 `migrate` → 페이지 렌더링 → 상품 등록 → WebSocket 채팅까지 검증했다.

---

## 10. 중간 보고서 개선 계획 이행 결과

중간 보고서 8장에서 확인한 한계와 8.4절의 계획을 현재 코드와 대조했다.

### 10.1 버그 · 한계 해결 현황

| # | 중간 보고서 지적 사항 | 기말 결과 | 근거 |
|---|---|---|---|
| 1 | `LOGIN_URL` 미설정 → 404 | ✅ 해결 | `base.py` 86행 `LOGIN_URL = "accounts:login"` |
| 2 | Pillow 누락 | ✅ 해결 | `requirements.txt`의 `pillow==13.0.0`, 업로드 검증에 실제로 사용 |
| 3 | 상품당 이미지 1장 | ✅ 해결 | `ProductImage` 모델, 최대 10장, 순서 · 대표 사진 |
| 4 | 카테고리 · 거래상태 없음, `href="#"` | ✅ 해결 | `Category` 15종, `Product.Status` 3단계, 필터 · 동네 선택 연결 |
| 5 | 채팅 목록 생성 시각순 | ✅ 해결 | `ChatRoom.last_message_at`, 정렬 `-last_message_at`, 미리보기 |
| 6 | 읽음 표시 없음 | ✅ 해결 | `ChatMessage.is_read/read_at`, 실시간 읽음 이벤트, 안 읽은 수 배지 |
| 7 | WebSocket 재연결 없음 | ✅ 해결 | `chat.js` 지수 백오프 재연결 + 놓친 메시지 보충 + HTTP 대체 전송 |
| 8 | Storage 이미지 미정리 | ⚠️ 미해결 | 상품 · 사진 삭제 시 DB 행만 지우고 버킷 파일은 남는다 (11장) |
| 9 | 테스트 없음 | ✅ 해결 | 410개 테스트 통과 |
| 10 | 뷰에 로직 집중 · 단일 앱 | ✅ 해결 | 앱 8개 + services / selectors |
| 11 | N+1 쿼리 · 페이지네이션 없음 | ✅ 해결 | `with_card_data` annotate/prefetch, 20개 페이지네이션 |
| 12 | Storage 클라이언트 import 시점 생성 · 검증 없음 | ✅ 해결 | 지연 생성, 확장자 · 크기 · 실제 포맷 검사 |
| 13 | 공통 base 템플릿 없음 | ✅ 해결 | `base.html` + `components/` |
| 14 | asgi 중복 호출, admin 중복 import | ✅ 해결 | `asgi.py` 13행 한 번만 생성, 앱별 `admin.py` 재작성 |
| 15 | `DEBUG = False` 하드코딩 | ✅ 해결 | dev/prod 분리, 운영은 `DEBUG` 환경 변수, `SECRET_KEY` 필수 |
| 16 | `InMemoryChannelLayer` | ⚠️ 유지 | 단일 인스턴스 운영을 전제로 유지 (11장) |
| 17 | WhiteNoise 위치 · STORAGES 없음 | ✅ 해결 | `SecurityMiddleware` 다음, `CompressedManifestStaticFilesStorage` |
| 18 | requirements 인코딩 · 중복 · 오타 파일 | ✅ 해결 | UTF-8, 버전 고정 9개 패키지 |
| 19 | `staticfiles/` 커밋, `.gitignore` 오타 | ✅ 해결 | 삭제 후 `.gitignore` 등록, `Thumbs.db` 수정 |
| 20 | 문서 불일치 | ✅ 해결 | README · PROGRESS를 현재 구조 기준으로 다시 작성 |

### 10.2 기말 계획 이행 현황

| 계획 (중간 보고서 8.4) | 결과 |
|---|---|
| 1. 앱 분리 + 서비스 레이어 + 설정 정리 + 테스트 | ✅ 계획의 3개 앱보다 세분화한 8개 앱으로 완료 |
| 2. Tailwind CSS + HTMX 디자인 개편 | ✅ 완료 |
| 3. 동네 · 카테고리 · 거래상태 · 다중 이미지 · 후기/매너 · 알림 · 신고/차단 · 판매자 프로필 · 최근 본 상품 · 채팅 개선 | ✅ 모두 완료 (동네는 전국 행정동 3,559개로 확장) |
| 4. AI 4종 (설명 생성 · 사진 인식 · 사기 탐지 · 협상 초안) | ✅ 모두 완료 + 캐시 · 사용 기록 · 실패 대비 |

---

## 11. 한계점 및 향후 과제

| 구분 | 내용 | 개선 방향 |
|---|---|---|
| 확장성 | 채널 레이어가 `InMemoryChannelLayer`라 서버 프로세스가 여러 개가 되면 서로 다른 프로세스에 붙은 사용자끼리 메시지가 전달되지 않는다. 현재는 단일 인스턴스로 운영한다. | `channels-redis`로 Redis 채널 레이어 도입 |
| 저장소 정리 | 상품이나 사진을 지워도 Supabase 버킷의 파일은 남는다. | `core/storage.py`에 삭제 함수를 추가해 상품·사진 삭제 시 호출, 또는 참조 없는 파일을 주기적으로 정리 |
| AI 실행 방식 | 사기 탐지가 상품 저장 요청 안에서 동기로 실행되어(최대 8초) 저장 응답이 느려질 수 있다. | Celery 등 백그라운드 작업으로 분리 |
| 알림 실시간성 | 헤더 배지는 HTMX polling(30초)이라 즉시 반영되지 않는다. | 알림도 WebSocket으로 push |
| 검색 | `icontains` 기반이라 데이터가 많아지면 느리고 형태소 단위 검색이 안 된다. | PostgreSQL 전문 검색(`SearchVector`) 또는 trigram 인덱스 |
| 신고 처리 | 신고 검토가 관리자 페이지 수동 처리에 의존한다. | 누적 신고 시 자동 숨김, 사기 위험도와 연계 |
| AI 결과 검증 | AI 생성 결과는 사용자가 적용 전 확인하지만, 협상 초안 · 사기 판단의 품질을 정량 평가하는 장치가 없다. | `AIUsageLog`와 사용자 피드백(적용 여부)으로 품질 지표 수집 |

---

## 12. 결론

기말 단계에서 폴리마켓은 중간 보고서에서 세운 네 가지 계획을 모두 완성했다. 단일 앱에 섞여 있던 로직을 기능별 앱 8개와 서비스/셀렉터 계층으로 나눠, HTTP 뷰와 WebSocket consumer가 같은 비즈니스 규칙을 공유하도록 만들었다. 그 위에 동네(전국 행정동 3,559개), 카테고리, 거래상태, 다중 이미지, 거래완료·후기·매너온도, 알림, 신고·차단, 채팅 읽음·재연결까지 중고거래의 전체 흐름을 구현했고, Tailwind CSS와 HTMX로 화면을 일관된 디자인 시스템으로 다시 만들었다.

AI 기능 4종은 "AI가 없어도 서비스는 동작한다"는 원칙으로 설계했다. 모든 응답을 JSON 스키마와 서버 검증으로 제한하고, 입력 해시 기반 캐시로 비용을 줄이며, 실패는 한국어 안내로 바꾸고, 결과는 사용자가 직접 적용하게 했다. 특히 사기 탐지는 정규식 규칙·가격 이상치·AI 판단을 결합하고 부정 표현과 숫자 문맥으로 오탐을 줄여, AI가 실패해도 규칙만으로 경고를 띄울 수 있게 했다.

중간 보고서에서 확인한 20개 한계 중 18개를 해결했고, 테스트가 전혀 없던 상태에서 410개의 테스트가 통과하는 상태가 되었다. 남은 과제는 다중 인스턴스를 위한 Redis 채널 레이어, 저장소 파일 정리, AI 작업의 비동기화로, 서비스가 커질 때 우선 해결할 부분이다.
