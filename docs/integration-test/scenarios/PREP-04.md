# PREP-04 우리 설정 채우기

| 항목 | 값 |
| --- | --- |
| 서비스구분 | PREP 사전 준비 |
| 우선순위 | P0 |
| 화면 | X 화면 밖 · 설정 파일 |
| 필요 권한 | 운영 |
| 단독 수행 | 아니오 |

## 1. 목적
우리 서비스의 환경별 설정을 채웁니다.

## 2. 사전 조건
- DB·Redis·SSO·LLM·executor·pr-batch 주소

## 3. 수행 절차
처음 수행하는 사람은 아래 3-1절 "화면 조작 안내"를 먼저 읽습니다. 번호 줄은 할 일이고, 그 아래 작은 항목은 실제로 누르고 입력하고 확인할 내용입니다. "※ 미확인"은 코드로 확인하지 못해 환경에서 한 번 확인이 필요한 내용입니다. 우리 화면(`/dev/`)은 테스트를 수행하기 위한 보조 도구이고 통합 테스트 대상이 아닙니다. 통과·실패는 서버 응답(상태 코드, 응답 본문, 이벤트)과 세 서비스의 기록으로 판정하고, 화면에 보이는 글자나 버튼은 그 값을 읽는 수단으로만 씁니다.

1. `config.<env>.yml`의 `<...>` 자리를 모두 채웁니다(DATABASE_URL, REDIS_URL, PUBLIC_API_ORIGIN, FRONTEND_ORIGIN, CORS_ORIGINS, LLM_API_KEY, MODELS, EXECUTOR_BASE_URL, BATCH_BASE_URL).
   - 우리 저장소 루트의 `config.dev.yml` 또는 `config.prd.yml`을 엽니다. 값이 `<...>`로 적힌 자리가 채워야 할 곳입니다.
   - 각 값의 뜻과 예시는 `config.example.yml`의 같은 이름 항목 주석에 있습니다. DB·Redis 주소는 인프라 담당, LLM 키와 모델 목록은 LLM 게이트웨이 담당, executor·pr-batch 주소는 각 서비스 담당에게 받습니다.
   - 다 채운 뒤 파일에서 `<`를 검색해 남은 자리표시가 없는지 봅니다.
2. `SSO_ALLOWED_ORIGINS`, `ADMIN_EMPLOYEE_IDS`(관리자 사번)를 채웁니다.
   - `SSO_ALLOWED_ORIGINS`에는 SSO 로그인 페이지의 주소(스킴과 호스트)를 넣습니다. 비어 있으면 prd는 기동하지 않습니다.
   - `ADMIN_EMPLOYEE_IDS`에는 관리자로 쓸 사번을 SSO가 보내는 그대로 넣습니다(예: `["a10054"]`). 그 사람이 처음 로그인할 때만 적용되므로 반드시 첫 로그인 전에 넣습니다. 이미 일반으로 로그인한 사번은 `scripts/set_user_role.py`로 바꿉니다.
3. REDIS_URL이 executor가 이벤트를 쓰는 Redis와 같은지 확인합니다. `EXECUTOR_RESULT_ROOT`는 `/mnt/data/dtest`입니다.
   - executor 담당에게 executor가 이벤트를 쓰는 Redis 주소를 받아 우리 `REDIS_URL`과 호스트·포트·DB 번호까지 같은지 비교합니다. 다르면 실행 결과가 우리 쪽으로 오지 않아 run이 끝나지 않습니다.
   - `EXECUTOR_RESULT_ROOT` 값이 `/mnt/data/dtest`인지 봅니다.
4. prd는 `WEB_CONSOLE_ENABLED: true`인지 확인합니다(오픈 때 false).
   - `config.prd.yml`에서 `WEB_CONSOLE_ENABLED: true`인지 봅니다. 이 값이 꺼져 있으면 prd에서 `/dev/` 화면이 열리지 않아 화면 시나리오를 할 수 없습니다.
5. 임베딩을 쓰면 `EMBEDDING_PROVIDER: openai`, `EMBEDDING_SEND_DIMENSIONS: false`로 두고 PowerShell에서 `scripts\check_embedding.ps1`로 확인합니다.
   - 임베딩을 쓰지 않으면(`EMBEDDING_PROVIDER: none`) 이 단계는 건너뛰고 RUN-08은 "보류"로 둡니다.
   - 쓰는 경우 PowerShell에서 저장소 루트로 이동해 `scripts\check_embedding.ps1`을 실행합니다. 스크립트는 게이트웨이에 요청을 몇 가지 보내고 어느 요청이 거절되는지 알려 줍니다. 모든 경우가 통과해야 합니다.

## 3-1. 화면 조작 안내

**운영 담당과 함께 할 때**
- "운영 담당이 …"로 시작하는 단계는 수행자가 직접 하지 않습니다. 클러스터 권한이 있는 운영 담당에게 요청하고, 끝났다는 답을 받은 뒤 다음 단계로 갑니다. 아래는 운영 담당이 쓰는 방법입니다. `<namespace>`는 환경의 네임스페이스로 바꿉니다.
- **우리 서비스 설정을 잠깐 바꾸기**: 설정값은 이미지에 들어 있는 `config.<환경>.yml`에서 읽지만, 같은 이름의 환경 변수가 있으면 환경 변수가 우선합니다. 그래서 테스트용 변경은 이미지를 다시 만들지 않고 Deployment의 환경 변수로 합니다. `kubectl -n <namespace> set env deployment/pr-agentic-service 이름=값`을 실행하면 Pod가 하나씩 새 값으로 다시 뜹니다. `kubectl -n <namespace> rollout status deployment/pr-agentic-service`가 "successfully rolled out"으로 끝나면 새 Pod가 모두 뜬 것입니다. 그 시각을 적습니다.
- **바꾸기 전에 지금 값 보관**: `kubectl -n <namespace> set env deployment/pr-agentic-service --list`로 지금 환경 변수를 봅니다. 바꾸려는 이름이 이미 목록에 있으면(예: PREP-03에서 환경 변수로 넣은 키) 그 값을 보관해 두고, 되돌릴 때 같은 명령으로 원래 값을 다시 넣습니다.
- **되돌리기**: 목록에 없던 이름은 `kubectl -n <namespace> set env deployment/pr-agentic-service 이름-`(이름 뒤에 빼기 기호)로 환경 변수를 지웁니다. 그러면 다시 설정 파일의 값을 씁니다. 되돌린 뒤에도 `rollout status`로 끝난 것을 확인합니다.
- **목록 값**은 JSON으로 넣습니다. 예: `SSO_ALLOWED_ORIGINS='["https://sso.example.com"]'`.
- **재시작만**: `kubectl -n <namespace> rollout restart deployment/pr-agentic-service`.
- **서비스 내리기와 올리기**(executor, pr-batch): `kubectl -n <namespace> get deployment`로 이름과 지금 Pod 수를 확인하고, `kubectl -n <namespace> scale deployment/<이름> --replicas=0`으로 내립니다. `kubectl -n <namespace> get pod`에서 그 서비스의 Pod가 없어지면 내려간 것입니다. 올릴 때는 `--replicas=<원래 수>`로 실행하고 `rollout status`로 확인합니다. 그 Deployment에 HPA가 걸려 있으면(`kubectl -n <namespace> get hpa`) Pod를 다시 올려 버리므로, 내리는 동안 HPA를 먼저 지우고 끝난 뒤 다시 적용합니다. 우리 서비스에는 HPA(최소 2개)가 있습니다.
- **로그 찾기**: `kubectl -n <namespace> logs -l app=pr-agentic-service --prefix --since=10m --tail=-1 | grep <검색어>`. 로그 확인을 요청하는 사람은 검색어(단계에 적힌 로그 이름), 동작한 시각(초 단위), 있으면 request id나 run id를 전달합니다. 운영 담당은 찾은 줄을 그대로 복사해 주고, 수행자는 8절 증빙에 붙입니다.
- ※ 미확인: 위 명령은 저장소의 `deploy/kubernetes/deployment.yml`(Deployment 이름 `pr-agentic-service`, 레이블 `app=pr-agentic-service`) 기준입니다. 내부망에서 이름이 다르거나, kubectl을 직접 못 쓰고 배포 파이프라인으로만 배포한다면 같은 환경 변수를 배포 설정의 `env`에 넣어 배포합니다. executor와 pr-batch의 Deployment 이름, 설정 방식, 사내 로그 도구는 각 담당의 방법을 따릅니다.
- "단독 수행: 예"인 시나리오는 다른 사람의 테스트를 깨뜨립니다. 시작 전에 테스트 채널에 시작을 알리고, 6절 정리까지 끝낸 뒤 끝났다고 알립니다.

**끝난 뒤 기록**
- 각 단계에서 예상 결과와 비교할 화면을 캡처합니다(Windows는 Win+Shift+S). API 키 원문, 쿠키, CSRF 토큰이 보이면 가리고 올립니다.
- 이 페이지 7절 "수행 기록"에 환경, 수행자, 수행 일시, 빌드 커밋, 결과를 적고, 8절에 단계별 실제 결과와 증빙(캡처, 응답 본문, request id, run id, 실행 ID)을 붙입니다.
- 상황판(엑셀)에서 이 시나리오의 TC 줄마다 상태를 **통과** 또는 **실패**로 바꾸고 시작일자와 완료일자를 적습니다. 4절 예상 결과의 한 줄이 TC 하나입니다.
- 판정 근거는 서버가 준 값입니다. 4절 예상 결과에 화면 표시로 적힌 항목도 요청·응답 창의 응답 본문이나 이벤트에서 같은 값을 확인해 판정합니다. 화면만 이상하고(글자 깨짐, 버튼 위치, 새로 고침해야 보임 등) 서버 응답은 예상과 같으면 **통과**이고, 화면 문제는 결함으로 올리지 않고 테스트 담당에게 따로 알립니다.
- 화면으로 수행할 수 없게 되면(화면이 열리지 않음 등) 같은 요청을 **시스템 > API 호출 시험**이나 curl로 보내 수행해도 됩니다.
- 예상과 다르면 더 진행하지 말고 상태를 **실패**로 두고 9절에 결함(재현 단계, 예상, 실제, 발생 시각, request id)을 적은 뒤 결함번호를 상황판에 넣습니다.

## 4. 예상 결과
- 설정 파일에 `<`가 남은 값 0개
- 임베딩 확인 스크립트 통과(쓰는 경우)

## 5. 확인 방법
설정 파일 검토, 확인 스크립트 출력

## 6. 정리 (원상복구)
없음

---

## 7. 수행 기록
| 환경 | 수행자 | 수행 일시 | 빌드(commit) | 결과 |
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
