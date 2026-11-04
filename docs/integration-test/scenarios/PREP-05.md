# PREP-05 internal/gaia만

| 항목 | 값 |
| --- | --- |
| 서비스구분 | PREP 사전 준비 |
| 우선순위 | P0 |
| 화면 | X 화면 밖 · gaia 설정 |
| 필요 권한 | 운영 |
| 단독 수행 | 아니오 |
| 연동 경로 | - |
| 11/01판 ID | G0-5 |

## 1. 목적
내부망 gaia 이미지(internal/gaia)의 SSO와 템플릿 값을 채웁니다.

## 2. 사전 조건
- SSO 담당에게 받은 로그인 페이지·userinfo 주소와 응답 필드명

## 3. 수행 절차
1. `src/dtest/idp_login.py`의 `SSO_LOGIN_PAGE`·`USERINFO_URL`·`FIELDS`를 채웁니다.
2. 템플릿 고정값 `PORT`, `PROJECT_NAME`, `SERVICE_NAME`과 `GAIA_DEPLOYMENT`를 채웁니다.
3. HCP·gaia 의존성을 추가하고 `uv lock`을 다시 만듭니다.

## 4. 예상 결과
- userinfo 응답 필드명이 코드와 같음
- 이미지가 빌드되고 기동함

## 5. 확인 방법
빌드 로그, 기동 로그

## 6. 정리 (원상복구)
없음

---

## 7. 수행 기록
| 환경 | 수행자 | 수행 일시 | 빌드(main / internal/gaia 커밋) | 결과 |
| --- | --- | --- | --- | --- |
| dev | | | | |
| prd | | | | |

## 8. 실제 결과와 증빙
- 단계별 실제 결과 (예상과 다르면 무엇이 달랐는지):
- 증빙 (화면 캡처, 응답 본문, request id, run id, 실행 ID):

## 9. 결함
| 결함번호 | 심각도 | 요약 | 재현 단계 | 예상 | 실제 | 발생 시각 | request id / run id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |
