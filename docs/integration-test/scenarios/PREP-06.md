# PREP-06 세 서비스 중지 후 동시 리셋

| 항목 | 값 |
| --- | --- |
| 서비스구분 | PREP 사전 준비 |
| 우선순위 | P0 |
| 화면 | X 화면 밖 · DB·PV·Redis 리셋 |
| 필요 권한 | 운영 |
| 단독 수행 | 예 |

## 1. 목적
예전 사용자 ID(uuid)와 테스트 흔적을 지워, 세 서비스가 같은 상태에서 시작하게 합니다.

## 2. 사전 조건
- 세 서비스 중지 가능 시간 확보, 인프라 담당 참석

## 3. 수행 절차
처음 수행하는 사람은 아래 3-1절 "화면 조작 안내"를 먼저 읽습니다. 번호 줄은 할 일이고, 그 아래 작은 항목은 실제로 누르고 입력하고 확인할 내용입니다. "※ 미확인"은 코드로 확인하지 못해 환경에서 한 번 확인이 필요한 내용입니다. 우리 화면(`/dev/`)은 테스트를 수행하기 위한 보조 도구이고 통합 테스트 대상이 아닙니다. 통과·실패는 서버 응답(상태 코드, 응답 본문, 이벤트)과 세 서비스의 기록으로 판정하고, 화면에 보이는 글자나 버튼은 그 값을 읽는 수단으로만 씁니다.

1. 우리, executor, pr-batch를 모두 내립니다.
   - 단독 수행입니다. 시작 전에 테스트 채널에 "세 서비스를 내리고 데이터를 지운다"고 알립니다. 지우면 되돌릴 수 없으니 대상 환경이 맞는지 인프라 담당과 함께 확인합니다.
   - 우리 서비스, executor, pr-batch의 Pod를 모두 0개로 줄입니다. 셋 다 내려간 것을 확인한 뒤 다음 단계로 갑니다.
   - 운영 방법: 우리 서비스에는 HPA(최소 2개)가 있어 그대로 0으로 줄이면 다시 올라옵니다. `kubectl -n <namespace> delete hpa pr-agentic-service` 뒤 `kubectl -n <namespace> scale deployment/pr-agentic-service --replicas=0`을 실행합니다. executor와 pr-batch도 같은 방법으로 내립니다. 리셋이 끝나고 PREP-07에서 배포할 때 HPA도 다시 적용합니다.
2. 세 서비스 DB를 비웁니다.
   - 서비스마다 DB가 따로 있습니다(셋). 각 DB의 테이블을 모두 비웁니다. ※ 미확인: DB 이름과 비우는 방법(스키마 삭제 후 마이그레이션 등)은 환경마다 달라 각 서비스 담당의 방법을 따릅니다.
3. 공유 PV의 `tenants/*/users/*`와 우리 `STORAGE_ROOT` 아래를 지웁니다.
   - 공유 PV에서 `tenants/` 아래 각 tenant 폴더의 `users/` 아래를 지웁니다. 우리 서비스의 `STORAGE_ROOT` 설정값이 가리키는 폴더 아래도 지웁니다.
   - 폴더 자체(`tenants/`, `STORAGE_ROOT`)는 남깁니다.
4. Redis의 `executor.events.*` 스트림과 컨슈머 그룹을 지웁니다.
   - Redis에 접속해 `redis-cli --scan --pattern "executor.events.*"`로 키를 찾고, 나온 키를 `DEL`로 지웁니다. 스트림을 지우면 컨슈머 그룹도 함께 없어집니다.
5. 우리 `STORAGE_ROOT`에 UID 1000이 쓸 수 있는지 확인합니다.
   - 우리 서비스는 UID 1000으로 돕니다. PV를 붙인 Pod나 노드에서 UID 1000으로 `STORAGE_ROOT` 아래에 빈 파일을 하나 만들어 보고 지웁니다. 권한 오류가 나면 폴더 소유자를 1000으로 바꿉니다.

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
- DB 테이블이 비어 있음
- Redis에 `executor.events.*` 키 없음
- UID 1000으로 파일 쓰기 성공

## 5. 확인 방법
DB 조회, `redis-cli --scan --pattern "executor.events.*"`, PV에서 쓰기 시험

## 6. 정리 (원상복구)
prd는 본 테스트가 끝나고 오픈 전에 한 번 더 수행

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
