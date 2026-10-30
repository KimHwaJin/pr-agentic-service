# 사내 SSO 연결과 확인 (내부망)

실제 사내 SDK로 로그인이 끝까지 되는지 확인하는 순서입니다. 사외에서는 SDK가 없어서 이 확인을 할 수 없습니다.

## 1. 채울 것

- `src/dtest/company_sso.py`(main 브랜치는 `src/company_sso.py`)
  - `from your_private_module import SSO`를 SDK의 실제 import로 바꿉니다.
  - `create_sdk(request, callback_url)`는 Flask 샘플처럼 `SSO(request)`를 돌려줍니다. 샘플이 복귀 주소를 `request.args["ORIGIN"]`이 아닌 다른 방법(생성자 인자 등)으로 받으면 `callback_url`을 그 방법으로 넘깁니다.
- 설정(`config.{APP_ENV}.yml` 또는 `.env`)
  - `SSO_ADAPTER: company` (config.yml 기본값)
  - `PUBLIC_API_ORIGIN`: 브라우저가 보는 우리 API 주소. 콜백 주소가 여기서 만들어집니다.
  - `FRONTEND_ORIGIN`, `SSO_ALLOWED_RETURN_ROOTS`: 로그인 뒤 돌아갈 화면.
  - `SSO_ALLOWED_ORIGINS`: SDK가 돌려주는 로그인 페이지의 origin(예: `https://sso.회사도메인`). 비어 있으면 로그인 이동이 502로 막힙니다.
  - `COOKIE_SECURE`: https면 true(stg·prd 필수).
  - 로컬 PC에서 확인할 때는 `.env`에서 `SSO_ADAPTER=company`로 바꿉니다. `APP_ENV`를 비운 로컬에서도 company는 허용됩니다.

## 2. 확인 순서

브라우저로 `PUBLIC_API_ORIGIN/api/v1/auth/login/sso?return_to=/` 를 엽니다(XHR 아님). 테스트 콘솔이면 `return_to=/dev/`.

| 단계 | 정상 | 로그(`src.dtest.api_service.auth`) |
| --- | --- | --- |
| 1. 처음 요청 | 사내 SSO 로그인 페이지로 302 | `sso_verify result=no_cookie` 또는 `rejected`, `sso_login_redirect to=<SSO 호스트>` |
| 2. SSO 로그인 후 | `…/auth/login/sso/callback/<flow_id>`로 돌아옴 | `sso_verify result=ok`, `sso_login_ok from_callback=True` |
| 3. 화면 복귀 | `FRONTEND_ORIGIN + return_to`, `agentic_session` 쿠키 생김 | |
| 4. `GET /api/v1/users/me` | 200, 사번·이름이 맞음 | |

이미 회사 SSO 쿠키가 있으면 1단계에서 SSO를 거치지 않고 바로 `sso_login_ok from_callback=False`가 나옵니다.

## 3. 실패할 때 보내 줄 것

쿠키 값, 로그인 URL 전체, 사번은 보내지 마세요. 상태 코드, 브라우저가 멈춘 주소의 경로 부분, 위 로그 줄이면 충분합니다.

| 증상 | 뜻 | 먼저 볼 것 |
| --- | --- | --- |
| 기동 시 `ModuleNotFoundError` | SDK import 경로가 틀림 | `company_sso.py`의 import |
| 502 `invalid login URL` | SDK가 준 로그인 주소의 origin이 허용 목록에 없음 | `sso_login_url_rejected origin=…`의 값을 `SSO_ALLOWED_ORIGINS`에 추가 |
| 503 `Corporate SSO is unavailable` | SDK 호출이 예외를 냄 | `sso_verify_failed error_type=…`, `sso_verify_bad_check`, `sso_verify_bad_info` 로그 |
| 콜백에서 401 `could not verify` | SSO에서 돌아왔지만 회사 쿠키가 안 오거나 검증 실패 | `sso_verify result=rejected cookies=…`에 나온 쿠키 이름(회사 쿠키가 빠졌으면 도메인 문제) |
| 콜백에서 400 `Login flow expired` | 5분이 지났거나 같은 콜백을 다시 엶 | 처음부터 다시 로그인 |
| SSO와 우리 사이를 계속 왕복 | SDK가 콜백 주소를 잃어버림 | `sso_login_redirect`가 몇 번 찍히는지, SSO에서 돌아온 주소 |
| 로그인 후 403 `disabled` | 비활성 사용자 | `users.is_active` |

prj_re에서는 SDK가 복귀 주소의 query를 잘라 먹어 왕복이 생겼고, 그래서 콜백 주소에 query 없이 `flow_id`만 경로로 넣습니다.
