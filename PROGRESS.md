# 진행 상황

당근마켓 클론 Django 프로젝트의 작업 현황과 실행 방법을 정리한 문서입니다.

## 실행 방법

```powershell
# 가상환경 활성화
.venv\Scripts\activate

# 개발 서버 실행
python manage.py runserver
```

서버가 뜨면 http://127.0.0.1:8000/ 에서 메인 페이지를 볼 수 있습니다.

> DB는 PostgreSQL(Supabase)이며 접속 정보를 환경변수(`.env`)에서 읽습니다.
> `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`가 설정되어 있어야 합니다.

## 완료한 작업

- Django 프로젝트(`config`)와 앱(`market`) 생성
- 메인 페이지 뷰/URL/템플릿 연결 (`/` → `market/main.html`)
- DB를 PostgreSQL(Supabase)로 설정, 접속 정보는 환경변수로 분리
- `.gitignore`에 등록된 파일(`db.sqlite3`, `.vscode/`, `__pycache__/`)을 git 추적에서 제거

## 진행 중 / 예정 작업

- 모델 설계: 상품(Product), 사용자(User), 지역 등 (현재 `models.py`는 비어 있음)
- 마이그레이션 생성 및 Supabase DB에 적용
- 상품 목록 / 상세 / 등록 페이지 구현
- 메인 페이지 디자인 (현재는 환영 문구만 표시)
- `.gitignore`의 `Thunbs.db` 오타를 `Thumbs.db`로 수정
