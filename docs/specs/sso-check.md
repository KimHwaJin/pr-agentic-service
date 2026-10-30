# SSO 연결과 확인 (내부망)

실제 IdP로 로그인이 끝까지 되는지 확인하는 순서입니다. 외부망에서는 IdP에 닿지 않아 이 확인을 할 수 없습니다.

## 1. 채울 것

- `src/dtest/idp_login.py`(main 브랜치는 `src/idp_login.py`). 2026-10-30 개발 PC에서 `userinfo` 방식으로 로그인 성공.
  - `VERIFY_WITH = "userinfo"`(기본, 스트림릿 샘플 방식): 로그인은 `SSO_LOGIN_PAGE?TARGET=<콜백>`, 확인은 브라우저의 `SMSESSION`·`AMTOKEN` 쿠키를 workplace `USERINFO_URL`(경로 대소문자 `userInfo` 주의)로 보내 응답 JSON을 읽습니다. `SMOFC=logout`이면 로그아웃으로 봅니다. SDK가 필요 없습니다.
  - `FIELDS`: 왼쪽 이름은 그대로, 오른쪽만 응답 JSON의 키(`data.xxx`처럼 점으로 깊이). 사번·이름 필수, 나머지는 없으면 줄 삭제. 못 찾으면 `sso_userinfo result=no_employee keys=[…]`로 키 이름만 찍힙니다.
  - `VERIFY_WITH = "sdk"`(Flask 샘플 방식): SDK의 `check_day_cookie`·`get_sso_info`. 확인 때 새로 로그인한 쿠키도 거절했고 SDK의 `redirect_url`은 404였어서 쓰지 않습니다. SDK는 `pycryptodome`(`Crypto`)이 필요하고, Windows에서 `crypto` 패키지가 같이 깔리면 `No module named Crypto`가 납니다.
- 설정(`config.{APP_ENV}.yml` 또는 `.env`)
  - `SSO_ADAPTER: idp` (config.yml 기본값)
  - `PUBLIC_API_ORIGIN`: 브라우저가 보는 우리 API 주소. 콜백 주소가 여기서 만들어집니다.
  - `FRONTEND_ORIGIN`, `SSO_ALLOWED_RETURN_ROOTS`: 로그인 뒤 돌아갈 화면.
  - `SSO_ALLOWED_ORIGINS`: SDK가 돌려주는 로그인 페이지의 origin(예: `https://sso.<idp 도메인>`). 비어 있으면 로그인 이동이 502로 막힙니다.
  - `COOKIE_SECURE`: https면 true(stg·prd 필수).
  - 로컬 PC에서 확인할 때는 `.env`에서 `SSO_ADAPTER=idp`로 바꿉니다. `APP_ENV`를 비운 로컬에서도 idp는 허용됩니다.

## 2. 확인 순서

브라우저로 `PUBLIC_API_ORIGIN/api/v1/auth/login/sso?return_to=/` 를 엽니다(XHR 아님). 테스트 콘솔이면 `return_to=/dev/`.

| 단계 | 정상 | 로그(`src.dtest.api_service.auth`) |
| --- | --- | --- |
| 1. 처음 요청 | SSO 로그인 페이지로 302 | `sso_verify result=no_cookie` 또는 `rejected`(`sso_userinfo result=…`가 이유), `sso_login_redirect to=<SSO 호스트>` |
| 2. SSO 로그인 후 | `…/auth/login/sso/callback/<flow_id>`로 돌아옴 | `sso_verify result=ok`, `sso_login_ok from_callback=True` |
| 3. 화면 복귀 | `FRONTEND_ORIGIN + return_to`, `agentic_session` 쿠키 생김 | |
| 4. `GET /api/v1/users/me` | 200, 사번·이름이 맞음 | |

이미 SSO 쿠키가 있으면 1단계에서 SSO를 거치지 않고 바로 `sso_login_ok from_callback=False`가 나옵니다.

## 3. 실패할 때 보내 줄 것

쿠키 값, 로그인 URL 전체, 사번은 보내지 마세요. 상태 코드, 브라우저가 멈춘 주소의 경로 부분, 위 로그 줄이면 충분합니다.

| 증상 | 뜻 | 먼저 볼 것 |
| --- | --- | --- |
| 기동 시 `ModuleNotFoundError` | (sdk 방식) SDK import 경로가 틀림 | `idp_login.py`의 import |
| `sso_userinfo result=http_404` | userinfo 주소가 틀림 | 로그인된 Chrome에서 `USERINFO_URL`을 직접 열어 JSON이 나오는지(대소문자) |
| `sso_userinfo bad_fields` / `no_employee` | `FIELDS`가 응답과 안 맞음 | 왼쪽 이름은 그대로, 오른쪽을 `keys=[…]`의 이름으로 |
| 502 `invalid login URL` | SDK가 준 로그인 주소의 origin이 허용 목록에 없음 | `sso_login_url_rejected origin=…`의 값을 `SSO_ALLOWED_ORIGINS`에 추가 |
| 503 `SSO is unavailable` | SDK 호출이 예외를 냄 | `sso_verify_failed error_type=…`, `sso_verify_bad_check`, `sso_verify_bad_info` 로그 |
| 콜백에서 401 `could not verify` | SSO에서 돌아왔지만 SSO 쿠키가 안 오거나 검증 실패 | `sso_verify result=rejected cookies=…`에 나온 쿠키 이름(SSO 쿠키가 빠졌으면 도메인 문제) |
| 콜백에서 400 `Login flow expired` | 5분이 지났거나 같은 콜백을 다시 엶 | 처음부터 다시 로그인 |
| SSO와 우리 사이를 계속 왕복 | SDK가 콜백 주소를 잃어버림 | `sso_login_redirect`가 몇 번 찍히는지, SSO에서 돌아온 주소 |
| 로그인 후 403 `disabled` | 비활성 사용자 | `users.is_active` |

prj_re에서는 SDK가 복귀 주소의 query를 잘라 먹어 왕복이 생겼고, 그래서 콜백 주소에 query 없이 `flow_id`만 경로로 넣습니다.

## 4. 개발 PC에서 https로 띄우기

SSO 쿠키는 IdP 도메인 아래 주소에만 오고, 그 도메인은 https만 허용(HSTS)합니다. `localhost`로 열면 콜백에서 쿠키가 없어 401이 나고, http로 띄우면 브라우저가 https로 바꿔 보내서 `Invalid HTTP request received`가 납니다.

1. hosts 파일(관리자 권한): `127.0.0.1  dtest-local.<idp 도메인>`
2. `.env`: 두 주소를 `https://dtest-local.<idp 도메인>:5000`으로, `COOKIE_SECURE=true`
3. 레포 루트에서
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_local_https.ps1 -HostName dtest-local.<idp 도메인>
   ```
   처음 한 번 `.local/tls/`에 자체 서명 인증서를 만들고(`scripts/make_local_cert.py`), gaia 없이 uvicorn을 TLS로 띄웁니다. 포트는 `-Port`, 인증서 다시 만들기는 `-NewCert`.
4. 브라우저 인증서 경고는 한 번 "고급 → 계속"으로 넘깁니다.
