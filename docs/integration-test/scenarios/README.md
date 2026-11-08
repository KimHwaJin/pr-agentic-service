# 통합테스트 시나리오 페이지

시나리오마다 한 파일입니다. 컨플루언스에 페이지로 옮기고 상황판 링크 칸에 주소를 넣습니다. 양식과 작성 규칙은 [../scenario-page-template.md](../scenario-page-template.md), 전체 계획은 [../integration-test-plan.md](../integration-test-plan.md)입니다.

- 수행자 PC는 Windows, 브라우저는 Chrome 또는 Edge입니다.
- 키 호출은 관리자 화면 **시스템 > API 호출 시험**에서 합니다.
- "단독"은 시간을 정해 혼자 수행합니다.

| ID | 시나리오 | 우선 | 화면 | 필요 권한 | 단독 |
| --- | --- | --- | --- | --- | --- |
| [PREP-01](PREP-01.md) | 기준 커밋 고정 | P0 | X | 운영 |  |
| [PREP-02](PREP-02.md) | 환경별 키 생성 | P0 | X | 운영 |  |
| [PREP-03](PREP-03.md) | 해시 교환 | P0 | X | 운영 |  |
| [PREP-04](PREP-04.md) | 우리 설정 채우기 | P0 | X | 운영 |  |
| [PREP-05](PREP-05.md) | internal/gaia만 | P0 | X | 운영 |  |
| [PREP-06](PREP-06.md) | 세 서비스 중지 후 동시 리셋 | P0 | X | 운영 | 단독 |
| [PREP-07](PREP-07.md) | 배포 | P0 | X | 운영 | 단독 |
| [PREP-08](PREP-08.md) | 연결 스모크(S0, 아래) | P0 | 일부 | 운영 |  |
| [PREP-09](PREP-09.md) | 관리자 최초 로그인 → /users/me에서 admin 확인 → 테스트 키 2개 발급 | P0 | O | 관리자 |  |
| [PREP-10](PREP-10.md) | 테스트 데이터 | P0 | 일부 | 운영 |  |
| [AUTH-01](AUTH-01.md) | SSO 첫 로그인 | P0 | O | 일반 |  |
| [AUTH-02](AUTH-02.md) | `ADMIN_EMPLOYEE_IDS`에 있는 사번의 최초 로그인 | P0 | O | 관리자 |  |
| [AUTH-03](AUTH-03.md) | 브라우저 쓰기 요청에 `X-CSRF-Token` 없음 | P0 | O | 관리자 |  |
| [AUTH-04](AUTH-04.md) | 키 + `X-User-Id`로 `GET /users/me` | P0 | O | 관리자 |  |
| [AUTH-05](AUTH-05.md) | `X-User-Id`가 우리 DB에 없는 사번 / 형식 위반 | P0 | O | 관리자 |  |
| [AUTH-06](AUTH-06.md) | 키로 관리자 API 호출 | P0 | O | 관리자 |  |
| [AUTH-07](AUTH-07.md) | 키 개별 폐기 | P0 | O | 관리자 |  |
| [AUTH-08](AUTH-08.md) | 우리 tenant 키를 `own_tenant` 없이 발급 | P1 | O | 관리자 |  |
| [AUTH-09](AUTH-09.md) | 쿠키와 키를 함께 보냄 | P1 | O | 관리자 |  |
| [AUTH-10](AUTH-10.md) | SSO 로그인 페이지 도메인이 `SSO_ALLOWED_ORIGINS`에 없음 | P1 | X | 운영 | 단독 |
| [AUTH-11](AUTH-11.md) | 비관리자 사용자가 dev 역할 변경 `POST /auth/dev/role` | P1 | O | 관리자 |  |
| [RUN-01](RUN-01.md) | 브라우저: 새 세션 + 분석 요청 → plan_approval 승인 → executor 실행 → 리포트 | P0 | O | 일반 |  |
| [RUN-02](RUN-02.md) | 같은 흐름을 키 호출자로 (Swagger 가이드 1절) | P0 | O | 관리자 |  |
| [RUN-03](RUN-03.md) | Ingress를 거친 SSE `GET /sessions/{id}/events` | P0 | O | 일반 |  |
| [RUN-04](RUN-04.md) | code_approval·question·workflow_save 응답 | P0 | O | 일반 |  |
| [RUN-05](RUN-05.md) | 실행 중 run 취소 (채팅 중지 버튼) | P0 | O | 일반 |  |
| [RUN-06](RUN-06.md) | `waiting_executor` 중 우리 워커 재시작 | P0 | 일부 | 운영 | 단독 |
| [RUN-07](RUN-07.md) | reject_templates (`allow_reject_templates: true`인 카드) | P1 | O | 일반 |  |
| [RUN-08](RUN-08.md) | 자동 실행 조건 충족(후보 1개, 유사도 0.77 이상). 임베딩을 켠 환경(`EMBEDDING_PROVIDER: openai`, `EMBEDDING_SEND_DIMENSIONS: false`)에서만 | P1 | O | 일반 |  |
| [RUN-09](RUN-09.md) | 진행 중 세션에 새 턴 | P1 | O | 관리자 |  |
| [RUN-10](RUN-10.md) | 오래된 `interrupt_id`로 재개 | P1 | O | 관리자 |  |
| [RUN-11](RUN-11.md) | 필수 입력을 비우고 승인 | P1 | O | 일반 |  |
| [RUN-13](RUN-13.md) | 실행 중 세션 삭제 | P1 | O | 일반 |  |
| [RUN-14](RUN-14.md) | 분석 시나리오 묶음 `scripts/run_scenarios.py` | P1 | X | 운영 |  |
| [RUN-15](RUN-15.md) | 코드 레벨 4로 분석 요청 (세션 또는 프로젝트 설정) | P1 | O | 일반 |  |
| [RUN-16](RUN-16.md) | 임베딩 없는 환경(`EMBEDDING_PROVIDER: none`)에서 템플릿이 있는 요청 | P1 | O | 일반 |  |
| [RUN-17](RUN-17.md) | 일회성 지시와 지속 선호를 섞어 대화 | P1 | O | 일반 |  |
| [EXEC-01](EXEC-01.md) | 우리 tenant 키 + `X-User-Id`로 `GET /executor/executions` | P0 | O | 관리자 |  |
| [EXEC-02](EXEC-02.md) | INLINE `print(1+1)` 제출(curl) | P0 | O | 관리자 |  |
| [EXEC-03](EXEC-03.md) | 외부 tenant(`it-ext`) 키로 실행 제출 | P0 | 일부 | 운영 |  |
| [EXEC-04](EXEC-04.md) | 키로 runtime·maintenance·attempts 경로 | P0 | O | 관리자 |  |
| [EXEC-05](EXEC-05.md) | 결과물 `/artifacts/{id}`·`/view/artifacts/{id}` | P0 | O | 일반 |  |
| [EXEC-06](EXEC-06.md) | 일반키·마스터키의 조회 범위와 `X-User-Id` 필수 | P1 | O | 관리자 |  |
| [EXEC-07](EXEC-07.md) | 우리 tenant 키로 남의 프로젝트·세션 헤더 | P1 | O | 관리자 |  |
| [EXEC-08](EXEC-08.md) | 관리자 시스템 > 런타임·점검 탭 | P1 | 일부 | 관리자 |  |
| [BAT-01](BAT-01.md) | 분석 노트북으로 스크립트 등록(`from-notebook`) | P0 | O | 일반 |  |
| [BAT-02](BAT-02.md) | 일정 있는 배치 생성 | P0 | O | 일반 |  |
| [BAT-03](BAT-03.md) | 지금 실행 | P0 | O | 일반 |  |
| [BAT-04](BAT-04.md) | 배치 리포트 | P0 | O | 일반 |  |
| [BAT-05](BAT-05.md) | 일정에 의한 실행(5분 뒤 1회) | P0 | O | 일반 |  |
| [BAT-06](BAT-06.md) | 실패하는 스크립트 | P0 | O | 일반 |  |
| [BAT-07](BAT-07.md) | 같은 배치 2회차 | P1 | O | 일반 |  |
| [BAT-08](BAT-08.md) | 우리 워커를 내린 채 배치 성공 → 재기동 | P1 | 일부 | 운영 | 단독 |
| [BAT-09](BAT-09.md) | 일정 없는 배치 / 지난 일정만 있는 배치 | P1 | O | 일반 |  |
| [BAT-10](BAT-10.md) | 외부 tenant 키로 배치 등록·실행 | P1 | 일부 | 운영 |  |
| [TEN-01](TEN-01.md) | 외부 tenant `it-ext` 일괄 폐기 (BAT-10 배치가 켜진 상태) | P0 | 일부 | 운영 | 단독 |
| [TEN-02](TEN-02.md) | pr-batch를 내린 채 tenant 폐기 | P0 | 일부 | 운영 | 단독 |
| [TEN-03](TEN-03.md) | 사용자 B 비활성화 | P0 | O | 관리자 | 단독 |
| [TEN-04](TEN-04.md) | tenant의 마지막 active 키를 개별 폐기 | P1 | 일부 | 운영 | 단독 |
| [TEN-05](TEN-05.md) | 우리 tenant 키 폐기 | P1 | O | 관리자 |  |
| [TEN-06](TEN-06.md) | B 재활성화 | P1 | O | 관리자 |  |
| [TEN-07](TEN-07.md) | pr-batch를 내린 채 사용자 비활성화 | P1 | 일부 | 운영 | 단독 |
| [ADM-01](ADM-01.md) | 시스템 > API 키 발급·목록·폐기 | P0 | O | 관리자 |  |
| [ADM-02](ADM-02.md) | 일반 사용자의 관리자 화면·API 접근 | P0 | O | 일반 |  |
| [ADM-03](ADM-03.md) | 사용자 관리 화면에서 비활성화·재활성화 | P0 | O | 관리자 |  |
| [ADM-04](ADM-04.md) | `/users/me` `permissions` | P1 | O | 일반 |  |
| [ADM-05](ADM-05.md) | 관리자 전체 실행 보기 + 사용자 필터 | P1 | O | 관리자 |  |
| [ADM-06](ADM-06.md) | 워크플로 승격·삭제 | P1 | O | 관리자 |  |
| [OPS-01](OPS-01.md) | executor를 내린 채 분석 요청, 이후 복구 | P0 | 일부 | 운영 | 단독 |
| [OPS-02](OPS-02.md) | Redis 재시작 | P0 | 일부 | 운영 | 단독 |
| [OPS-03](OPS-03.md) | 키 해시 불일치(일부러 틀린 키) | P0 | 일부 | 운영 | 단독 |
| [OPS-04](OPS-04.md) | pr-batch를 내린 채 배치 화면 | P1 | 일부 | 운영 | 단독 |
| [OPS-05](OPS-05.md) | 백그라운드 루프 정지 | P1 | X | 운영 | 단독 |
| [OPS-06](OPS-06.md) | prd 설정에 `<...>` 자리 남김, 빈 `SSO_ALLOWED_ORIGINS` | P1 | X | 운영 | 단독 |
| [OPS-07](OPS-07.md) | 32MB에 가까운 요청, 이미지 한도 초과 | P1 | O | 일반 |  |
| [OPS-08](OPS-08.md) | 없는 모델, LLM 장애 | P1 | 일부 | 운영 |  |
| [OPS-09](OPS-09.md) | 동시 사용자 부하(`scripts/loadtest.py`) | P1 | X | 운영 | 단독 |
| [OPS-10](OPS-10.md) | 항상 실패하는 코드를 요구하는 요청 | P0 | O | 일반 |  |
| [GAIA-01](GAIA-01.md) | gaia completion 첫 호출 | P0 | X | gaia 화면 |  |
| [GAIA-02](GAIA-02.md) | 계획 승인 자동 응답 | P0 | X | gaia 화면 |  |
| [GAIA-03](GAIA-03.md) | question에서 멈춤 → 다음 gaia 메시지 | P0 | X | gaia 화면 |  |
| [GAIA-04](GAIA-04.md) | SSO와 gaia의 사번 대소문자 표기 | P0 | X | gaia 화면 |  |
| [GAIA-05](GAIA-05.md) | 같은 대화가 웹 콘솔 세션에 보임 | P1 | O | 일반 |  |
| [GAIA-06](GAIA-06.md) | 호출이 끊긴 뒤 재호출 | P1 | X | gaia 화면 |  |
| [GAIA-07](GAIA-07.md) | gaia `GAIA_DEPLOYMENT=development` 이상에서 accesskey 없이 호출 | P0 | O | 관리자 |  |
