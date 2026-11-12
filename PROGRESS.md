# 진행 상황

실행 방법·구조·환경 변수는 [README.md](README.md)를 참고하세요.

## 완료

- 중간 버전: 단일 앱(`market`) 구조, 상품 CRUD · 찜 · 실시간 채팅 (보고서: `docs/reports/midterm/`)
- 리팩토링
  - 기능별 앱 8개(`apps/*`) + 서비스 레이어(`services.py` / `selectors.py`)
  - 설정 분리(`config/settings/` base · dev · prod)
  - Tailwind + HTMX 디자인 시스템
- 기본 기능: 회원·동네, 상품(다중 사진·카테고리·상태), 검색·필터, 찜·최근 본 상품, 1:1 채팅(읽음), 거래완료·후기·매너온도, 알림, 신고·차단, 판매자 프로필
- AI 기능 4종 (Gemini): 설명 생성, 사진 인식 자동 분류, 사기 의심 탐지, 가격 협상 답장 초안
- 테스트 359개 통과

## 예정

- 운영 DB 초기화 후 Render 재배포 (새 마이그레이션 적용)
- 기말 보고서 (`docs/reports/final/`)
