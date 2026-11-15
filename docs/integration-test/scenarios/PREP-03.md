# PREP-03 해시 교환

| 항목 | 값 |
| --- | --- |
| 서비스구분 | PREP 사전 준비 |
| 우선순위 | P0 |
| 화면 | X 화면 밖 · 각 서비스 설정 |
| 필요 권한 | 운영 |
| 단독 수행 | 아니오 |

## 1. 목적
각 서비스가 상대의 키를 알아보게 합니다.

## 2. 사전 조건
- PREP-02 완료

## 3. 수행 절차
처음 수행하는 사람은 아래 3-1절 "화면 조작 안내"를 먼저 읽습니다. 번호 줄은 할 일이고, 그 아래 작은 항목은 실제로 누르고 입력하고 확인할 내용입니다. "※ 미확인"은 코드로 확인하지 못해 환경에서 한 번 확인이 필요한 내용입니다. 우리 화면(`/dev/`)은 테스트를 수행하기 위한 보조 도구이고 통합 테스트 대상이 아닙니다. 통과·실패는 서버 응답(상태 코드, 응답 본문, 이벤트)과 세 서비스의 기록으로 판정하고, 화면에 보이는 글자나 버튼은 그 값을 읽는 수단으로만 씁니다.

1. executor `AUTH_CLIENTS`의 `pr-agentic-service`·`pr-batch`·`ops` 해시를 실제 값으로 바꿉니다.
   - executor 담당이 executor 설정의 `AUTH_CLIENTS` 목록에서 이름이 `pr-agentic-service`, `pr-batch`, `ops`인 항목의 `key_sha256` 값을 PREP-02에서 받은 해시로 바꿉니다.
   - 바꾸기 전 값이 `0000…`(0이 64개) 같은 자리표시인지 확인하고, 바꾼 뒤에는 남아 있지 않아야 합니다.
2. pr-batch `AUTH_CLIENTS`의 `pr-agentic-service` 해시를 바꿉니다(`admin: true`, `allowed_tenants: ["*"]` 유지).
   - pr-batch 담당이 pr-batch 설정의 `AUTH_CLIENTS`에서 `pr-agentic-service` 항목의 `key_sha256`을 우리→pr-batch 키의 해시로 바꿉니다.
   - 같은 항목의 `admin: true`와 `allowed_tenants: ["*"]`는 지우거나 바꾸지 않습니다. 이 둘이 없으면 사용자 비활성화·tenant 폐기 때 배치 끄기가 실패합니다.
3. 키 원문을 우리 `EXECUTOR_API_KEY`·`EXECUTOR_ADMIN_API_KEY`·`BATCH_API_KEY`와 pr-batch `EXECUTOR_API_KEY`에 넣습니다(Deployment env 권장).
   - 우리 서비스 배포 설정에 `EXECUTOR_API_KEY`(우리→executor 원문), `EXECUTOR_ADMIN_API_KEY`(ops 원문), `BATCH_API_KEY`(우리→pr-batch 원문)를 넣습니다.
   - pr-batch 배포 설정의 `EXECUTOR_API_KEY`에는 pr-batch→executor 키 원문을 넣습니다.
   - 설정 파일에 적어 저장소에 올리지 말고 Deployment의 환경 변수로 넣는 것을 권장합니다.
4. `EXECUTOR_API_KEY`·`BATCH_API_KEY` 같은 `*_API_KEY`에는 반드시 키 원문을, `AUTH_CLIENTS`의 `key_sha256`에는 해시를 넣습니다(바꿔 넣으면 401, 배치는 `SUBMIT_REJECTED`).
   - 헷갈리기 쉬운 부분입니다. 이름이 `…_API_KEY`로 끝나는 값은 "부르는 쪽"이 보내는 키 원문이고, `AUTH_CLIENTS`의 `key_sha256`은 "받는 쪽"이 대조하는 해시입니다.
   - 확인 방법: `…_API_KEY` 값이 64자리 hex 모양이면 해시를 잘못 넣은 것입니다. 원문을 PREP-02의 해시 명령에 넣어 나온 값이 상대 서비스의 `key_sha256`과 같아야 합니다.

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
- 세 서비스 설정에 0000… 해시가 남아 있지 않음
- `*_API_KEY` 값이 64자리 hex(해시 모양)가 아님. 원문의 SHA-256이 상대 서비스 `key_sha256`과 같음

## 5. 확인 방법
세 서비스 설정 diff

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
