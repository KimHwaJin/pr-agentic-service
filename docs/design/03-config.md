# 설정 관리 (설계안)

상태: 구현됨.

## 1. 배포 환경 제약

- ConfigMap·Secret을 쓸 수 없습니다. Deployment의 `env:`는 쓸 수 있습니다.
- 사내 가이드: 내부망이라 API key 같은 값도 설정 파일에 적어 씁니다. 환경별 파일(`config.dev`, `config.stg`, `config.prd`)을 두고, 이미지를 만들 때 환경을 지정해 해당 파일을 읽게 합니다(필수는 아니고 env로 넣어도 됨).

## 2. 제안

### 2.1 파일

레포 루트에 환경별 설정 파일을 둡니다. 모두 이미지에 복사합니다. 확장자는 사내 규칙대로 `.yml`입니다(레포의 다른 YAML도 `.yml`로 통일).

```
config.yml         # 로컬 개발 (APP_ENV 비움, compose가 마운트, 이미지에는 넣지 않음)
config.dev.yml
config.stg.yml
config.prd.yml
```

각 파일은 지금 환경변수로 받는 설정(`core/config.py`의 `Settings`)과 모델 목록을 함께 담습니다. 키 이름은 `Settings` 필드 이름 그대로(소문자)입니다.

```yaml
# config.prd.yml
database_url: postgresql+psycopg://agentic:…@pg.prd.internal:5432/agentic
redis_url: redis://redis.prd.internal:6379/0
llm_base_url: http://model.frodo.com/v1
llm_api_key: sk-…
executor_base_url: http://executor.prd.internal:8000
storage_root: /mnt/data/agent/pr-agentic-service
storage_executor_path: pr-agentic-service
executor_result_root: /mnt/data/executor
notebook_lab_base_url: https://executor-jupyter-lab.frodo.com
batch_base_url: http://pr-batch.prd.internal:8100
batch_jwt_private_key_file: /path/to/auth_private.pem
cors_origins: ["https://front.frodo.com"]
cookie_secure: true

models:
  - name: qwen38-27b-nvfp4
    label: Qwen 3.8 27B
    default: true
    input: [text]
  - name: example-vl-model
    label: 예시 비전 모델
    input: [text, image]
    max_images: 8
  - name: gpt-oss-120b
    params:               # 이 모델 요청 본문에만 붙는 값
      reasoning_effort: low
```

`params`는 그 모델로 보내는 요청에만 그대로 붙습니다(값은 검사하지 않음). 전역 `llm_enable_thinking`이 먼저 `chat_template_kwargs.enable_thinking`으로 들어가고, 모델의 `params`가 그 위를 덮습니다(`chat_template_kwargs`처럼 dict인 값은 키 단위로 합침). `params`는 서버 설정이라 모델 목록 API 응답에는 나가지 않습니다.

### 2.2 어느 파일을 읽을지

**`APP_ENV`(dev | stg | prd)로 고릅니다.** 배포는 `config.{APP_ENV}.yml`을 읽고, 로컬은 `APP_ENV`를 비워 두며 `config.yml`과 `.env`, 환경변수만 읽습니다. `APP_ENV`는 환경변수나 `.env`에서 읽고, 비어 있으면 `Settings.env`가 `local`이 됩니다(`env`는 설정 키가 아니라 `APP_ENV`에서 나옵니다).

이미지에는 `config.dev/stg/prd.yml`만 들어가고(`config.yml`은 `.dockerignore`), Deployment `env:`의 `APP_ENV=prd`로 고릅니다. Dockerfile의 `ARG APP_ENV`로 빌드 때 고정할 수도 있고, Deployment `env:`가 있으면 그 값이 이깁니다. pr-batch와 같은 체계입니다.

### 2.3 우선순위

높음 → 낮음:

1. 환경변수 (Deployment `env:`, compose `environment:`)
2. `.env`
3. `config.{APP_ENV}.yml`
4. `config.yml`
5. 코드 기본값 (`Settings` 필드 기본값)

환경변수가 가장 높아서, 파일을 다시 굽지 않고 급한 값 하나만 Deployment `env:`로 덮을 수 있습니다. pydantic-settings의 `YamlConfigSettingsSource`로 구현합니다.

### 2.4 검사

기동 시 다음을 확인하고, 맞지 않으면 시작하지 않습니다.

- `APP_ENV`가 dev/stg/prd가 아니면 오류, 그 환경의 `config.{APP_ENV}.yml`이 없으면 오류
- k8s(`KUBERNETES_SERVICE_HOST`가 있음)에서 `APP_ENV`가 비어 있으면 오류
- `models`가 비어 있거나 `default: true`가 정확히 하나가 아니면 오류, `name` 중복 오류
- `APP_ENV`가 있는데 `SSO_ADAPTER=dev`면 오류

### 2.5 바뀌는 것

- `core/config.py`: YAML 소스 추가, `models` 필드(목록) 추가, `LLM_MODELS`·`LLM_DEFAULT_ALIAS` 제거
- `Dockerfile`: `COPY config.*.yml ./`, `ARG APP_ENV` + `ENV APP_ENV=${APP_ENV}`(기본 비움)
- `docker-compose.yml`: `config.yml`을 마운트(재시작으로 반영), 지금 compose의 `environment:` 값들은 이 파일로 옮김
- `deploy/kubernetes/deployment.yml`: `envFrom`(ConfigMap·Secret) 제거, `env:`에는 `APP_ENV`와 덮어쓸 값만
- `.env.example`: 로컬에서 덮어쓸 값만 남김
- README 운영 연결 지점 갱신

## 3. 주의

- 설정 파일에 비밀값이 들어가므로 **레포 접근 권한 = 비밀값 접근 권한**이 됩니다. 사내 가이드가 허용한 방식이지만, 레포 공개 범위는 그에 맞게 관리해야 합니다.
- 모델 목록이나 주소를 바꾸면 이미지를 다시 빌드·배포해야 합니다(A안이어도 파일이 이미지 안에 있으므로). 급한 값은 Deployment `env:`로 덮을 수 있지만, `models` 같은 목록은 파일로만 바꿉니다.

## 4. 결정 사항

- 파일 선택: `APP_ENV`(Deployment `env:`)로 `config.{APP_ENV}.yml`을 고릅니다. 로컬은 `APP_ENV`를 비우고 `config.yml`만 씁니다. k8s에서 `APP_ENV`가 없으면 기동하지 않습니다.
- `config.yml`은 레포에 두고 로컬 compose가 마운트하며, 이미지에는 넣지 않아 로컬 값이 배포에 섞이지 않습니다. `config.dev/stg/prd.yml`은 `<...>` 자리를 운영자가 채웁니다.
