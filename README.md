# 🥕 폴리마켓 (Poly Market)

> Django로 만드는 동네 중고거래 플랫폼 — 당근마켓 클론 코딩 프로젝트

회원가입부터 상품 등록, 찜, 판매자와의 실시간 채팅까지 중고거래의 기본 흐름을 구현했습니다.
화면은 당근마켓 웹 UI를 참고해 디자인했습니다.

<br>

## 📌 목차

1. [로컬 환경 세팅](#️-로컬-환경-세팅)
2. [주요 기능](#-주요-기능)
3. [화면 구성](#-화면-구성)
4. [기술 스택](#-기술-스택)
5. [프로젝트 구조](#-프로젝트-구조)
6. [URL 목록](#-url-목록)
7. [디자인 가이드](#-디자인-가이드)
8. [변경 이력](#-변경-이력)

<br>

## ⚙️ 로컬 환경 세팅

> 필요한 것: **Python 3.10 이상**(개발 환경은 3.14), **Git**, 그리고 DB·이미지 저장소 접속 정보(`.env`)

### 1. 프로젝트 받기

```bash
git clone https://github.com/oceanstarlight/Django_danggeun_market.git
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

Linux / Windows 공통입니다. (`requirements.txt` 는 없으므로 직접 설치합니다.)

```bash
python -m pip install --upgrade pip
pip install "django~=5.2" daphne channels python-dotenv supabase "psycopg[binary]" pillow
```

### 4. `.env` 파일 만들기

프로젝트 루트(`manage.py` 와 같은 폴더)에 `.env` 파일을 만들고 값을 채웁니다.

```env
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

| 운영체제 | 파일 만들기 |
|---|---|
| Linux / macOS | `touch .env` 후 편집기로 열기 |
| Windows | `New-Item .env` (PowerShell) 후 메모장 등으로 열기. **확장자가 `.txt` 가 되지 않게 주의** |

> ⚠️ `.env` 에는 비밀번호와 키가 들어 있으므로 **절대 git에 커밋하지 마세요.** (`.gitignore` 에 등록되어 있습니다)
> 접속 정보는 프로젝트 담당자에게 받거나 본인의 Supabase 프로젝트 값을 사용하세요.

### 5. DB 마이그레이션 & 서버 실행

```bash
python manage.py migrate
python manage.py createsuperuser   # 관리자 계정 (선택)
python manage.py runserver
```

브라우저에서 👉 http://127.0.0.1:8000/

> `daphne` 가 `INSTALLED_APPS` 맨 위에 있어서 `runserver` 만으로 WebSocket 채팅까지 동작합니다.

### 자주 겪는 문제

| 증상 | 해결 |
|---|---|
| `ModuleNotFoundError` | 가상환경 활성화 여부 확인 후 3번 패키지 설치를 다시 실행 |
| DB 연결 오류 (`connection refused` 등) | `.env` 의 `DB_*` 값과 네트워크(Supabase 접근 가능 여부) 확인 |
| 상품 사진 업로드 실패 | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 및 `product-images` 버킷 존재 여부 확인 |
| 포트 8000 사용 중 | `python manage.py runserver 8001` |
| 스타일이 적용되지 않음 | 강제 새로고침(`Ctrl+Shift+R`) |

<br>

## ✨ 주요 기능 (현재 구현 상태)

### 👤 회원

| 기능 | 설명 |
|---|---|
| 회원가입 | 아이디 · 이름 · 생년월일 · 휴대폰번호 · 비밀번호 입력 (아이디/휴대폰번호 중복 검사) |
| 로그인 / 로그아웃 | 로그인 실패 시 에러 메시지 표시, 로그아웃은 POST 요청으로 처리 |
| 프로필 | `Profile` 모델에 생년월일, 휴대폰번호 저장 |

### 🛍️ 중고거래

| 기능 | 설명 |
|---|---|
| 상품 목록 | 최신순 정렬, 3열 카드 그리드 |
| 상품 검색 | 상단 검색창 / 인기 검색어 → 제목 · 본문 · 지역에서 검색 (`?q=`) |
| 상품 상세 | 들어갈 때마다 조회수 +1, 찜 수 · 채팅 수 표시 |
| 상품 등록 / 수정 / 삭제 | 로그인 필요, 수정 · 삭제는 **작성자 본인만** 가능 |
| 상품 사진 업로드 | Supabase Storage(`product-images` 버킷)에 업로드 후 URL 저장 |
| 지금 뜨는 중고거래 | 메인 화면에 조회수 상위 5개 상품 표시 |

### ❤️ 찜

- 상품 상세에서 **찜하기 / 찜 취소** 토글
- 자기 상품은 찜할 수 없음, 같은 상품은 한 번만 찜 가능

### 💬 실시간 채팅

- 상품 상세에서 **판매자와 채팅하기** → 상품 · 구매자 조합당 채팅방 1개 생성
- Django Channels + WebSocket 으로 새로고침 없이 메시지 송수신
- 채팅방 참여자(판매자 · 구매자)만 접속 가능
- 내 메시지는 오른쪽 오렌지 말풍선, 상대 메시지는 왼쪽 회색 말풍선

### 🛠️ 관리자

- `/admin/` 에서 Profile, Product, Wishlist, ChatRoom, ChatMessage 관리

<br>

## 🖥️ 화면 구성

모든 페이지가 같은 3단 레이아웃을 사용합니다.

```
┌──────┬──────────────────────────┬────────────────┐
│ 폴리 │  🔍 검색어를 입력하세요   │  로그인 / 회원가입 │   ← 공통 헤더
├──────┼──────────────────────────┼────────────────┤
│      │                          │                │
│      │   본문 (.main)           │  사이드 (.side) │
│      │                          │                │
└──────┴──────────────────────────┴────────────────┘
```

| 페이지 | 본문 | 사이드 |
|---|---|---|
| 메인 | 카테고리 타일 8개, 지금 뜨는 중고거래 | 지도 박스, 나의 폴리 |
| 상품 목록 | 카테고리 탭, 툴바, 상품 카드 그리드 | 인기 검색어 |
| 상품 상세 | 상품 사진, 판매자, 본문 | 가격, 찜 · 채팅 버튼 |
| 로그인 · 회원가입 · 등록 · 삭제 | 흰색 폼 카드 | – |
| 채팅 목록 · 채팅방 | 채팅방 리스트 / 말풍선 채팅 | – |

화면이 좁아지면 **3단 → 2단 → 1단**으로 자동 전환됩니다.

<br>

## 🧰 기술 스택

| 구분 | 사용 기술 |
|---|---|
| Backend | Python 3, Django 5.2 |
| 실시간 통신 | Django Channels, Daphne (ASGI), WebSocket |
| Database | PostgreSQL (Supabase) |
| 파일 저장소 | Supabase Storage |
| Frontend | Django Template, CSS (공용 스타일시트 1개), Vanilla JS |
| 폰트 | Pretendard |

<br>

## 📁 프로젝트 구조

```
Django_danggeun_market/
├── config/                     # 프로젝트 설정
│   ├── settings.py             # DB, Channels, 정적파일 설정 (.env 사용)
│   ├── urls.py
│   └── asgi.py                 # HTTP + WebSocket 라우팅
│
├── market/                     # 메인 앱
│   ├── models.py               # Profile, Product, Wishlist, ChatRoom, ChatMessage
│   ├── views.py                # 페이지 로직
│   ├── forms.py                # SignUpForm, ProductForm
│   ├── urls.py                 # URL 라우팅
│   ├── consumers.py            # 채팅 WebSocket 처리
│   ├── routing.py              # WebSocket URL
│   ├── storage.py              # Supabase 이미지 업로드
│   ├── admin.py
│   └── static/market/css/
│       └── style.css           # ⭐ 모든 페이지 공용 스타일시트
│
├── templates/market/
│   ├── header.html             # ⭐ 공통 헤더 (로고 · 검색창 · 로그인 박스)
│   ├── main.html
│   ├── login.html / signup.html
│   ├── product_list.html / product_detail.html
│   ├── product_form.html / product_delete.html
│   └── chat_list.html / chat_room.html
│
└── manage.py
```

<br>

## 🔗 URL 목록

| URL | 이름 | 설명 | 로그인 |
|---|---|---|:---:|
| `/` | `main` | 메인 | |
| `/signup/` | `signup` | 회원가입 | |
| `/login/` | `login` | 로그인 | |
| `/logout/` | `logout` | 로그아웃 (POST) | |
| `/products/` | `product_list` | 상품 목록 · 검색 (`?q=`) | |
| `/products/new/` | `product_create` | 상품 등록 | ✅ |
| `/products/<id>/` | `product_detail` | 상품 상세 | |
| `/products/<id>/edit/` | `product_update` | 상품 수정 (작성자) | ✅ |
| `/products/<id>/delete/` | `product_delete` | 상품 삭제 (작성자) | ✅ |
| `/products/<id>/wishlist/` | `wishlist_toggle` | 찜하기 / 취소 (POST) | ✅ |
| `/products/<id>/chat/` | `chat_start` | 판매자와 채팅 시작 | ✅ |
| `/chats/` | `chat_list` | 내 채팅 목록 | ✅ |
| `/chats/<room_id>/` | `chat_room` | 채팅방 | ✅ |
| `ws/chat/<room_id>/` | – | 채팅 WebSocket | ✅ |
| `/admin/` | – | 관리자 페이지 | |

<br>

## 🎨 디자인 가이드

### 공용 스타일시트 하나로 관리

페이지마다 CSS를 만들지 않고 **`market/static/market/css/style.css` 하나**를 모든 템플릿이 불러옵니다.

```html
{% load static %}
<link rel="stylesheet" href="{% static 'market/css/style.css' %}">
```

### 색상 · 크기 바꾸기

파일 맨 위 `:root` 변수만 고치면 전체 페이지에 반영됩니다.

| 변수 | 값 | 용도 |
|---|---|---|
| `--color-primary` | `#ff6f0f` | 메인 오렌지 (버튼, 로고) |
| `--color-bg` | `#f7f7f8` | 페이지 배경 |
| `--color-dark` | `#212124` | 활성 탭, 강조 버튼 |
| `--col-main` / `--col-side` | `600px` / `316px` | 본문 · 사이드 폭 |

### 자주 쓰는 클래스

| 클래스 | 설명 |
|---|---|
| `.site` / `.main` / `.side` | 3단 레이아웃 |
| `.btn` + `.btn-primary` · `.btn-dark` · `.btn-gray` · `.btn-danger` | 버튼 |
| `.card` / `.form-card` | 흰색 둥근 박스 |
| `.chip` / `.badge` | 검색어 칩 / 작은 태그 |
| `.product-grid` / `.product-card` | 상품 카드 그리드 |

### 🖼️ 이미지 넣을 자리 (`사진!`)

이미지가 들어가야 하는 곳은 템플릿에 **`<!-- 사진! (...) -->`** 주석으로 표시해 두었습니다.
지금은 회색 박스나 이모지로 대신 표시되어 있습니다.

```bash
grep -rn "사진!" templates/     # 이미지 자리 한 번에 찾기
```

| 위치 | 파일 |
|---|---|
| 로고 | `header.html` |
| 지도, 카테고리 아이콘 | `main.html` |
| 상품 기본 썸네일 | `product_list.html`, `product_detail.html` |
| 프로필 사진 | `main.html`, `product_detail.html`, `chat_list.html` |

이미지는 `market/static/market/img/` 폴더에 넣고 주석의 `<img>` 예시로 바꾸면 됩니다.

<br>

## 📝 변경 이력

### 2026-10-29 (오늘)

**UI 디자인 적용** — [PR #1](https://github.com/oceanstarlight/Django_danggeun_market/pull/1)

- 당근마켓 웹 UI를 참고해 **전체 9개 페이지 리디자인** (템플릿 11개 수정)
- 공용 스타일시트 `market/static/market/css/style.css` 추가, 템플릿의 인라인 스타일 제거
- 공통 헤더 `header.html` 추가 (로고 · 검색창 · 로그인 박스)
- 메인: 카테고리 타일 8개, 지도 박스, **지금 뜨는 중고거래** (조회수 순 5개)
- 상품 목록: 카테고리 탭, 3열 카드, 인기 검색어, **검색 기능** (`?q=`)
- 상품 상세: 사진 · 본문 + 가격 · 찜 · 채팅 사이드 박스
- 채팅방: 내 메시지 / 상대 메시지 **말풍선 구분**, 입장 시 최신 메시지로 자동 스크롤
- 가격에 천 단위 쉼표 표시 (`15000원` → `15,000원`)
- 서비스 이름을 **폴리 / 폴리마켓**으로 변경
- 화면 폭에 따라 3단 → 2단 → 1단 반응형 레이아웃

**문서**

- README 정리: 맨 위에 Linux / Windows 로컬 환경 세팅 방법 추가, 기능 · 구조 · URL · 디자인 가이드 최신화

<br>

### 이전 작업

| 날짜 | 내용 |
|---|---|
| 2026-10-22 | 상품 CRUD, 찜하기, 조회수, Django Channels 기반 1:1 실시간 채팅 |
| 2026-10-08 | 회원가입 · 로그인 · 로그아웃 페이지 |
| 2026-09-17 | Supabase(PostgreSQL · Storage) 연동, 접속 정보 `.env` 분리 |
| 2026-09-10 | Django 프로젝트(`config`) · 앱(`market`) 생성 |
