# pr-batch 서명 개인키

pr-batch 호출 토큰(RS256)을 서명하는 개인키(`auth_private.pem`)를 둔다. 폴더는 이미지에
그대로 복사되고(`COPY keys ./keys`), 설정 `batch_jwt_private_key_file`이 이 안의 파일을
가리킨다. 상대경로는 repo 루트(이미지에서는 `/app`) 기준이다.

```yaml
# config.<ENV>.yml
batch_jwt_private_key_file: keys/auth_private.pem
batch_jwt_issuer: batch-client      # pr-batch AUTH_ISSUER
batch_jwt_audience: batch-service   # pr-batch AUTH_AUDIENCE
```

- 키 쌍은 환경(dev/stg/prd)마다 현장에서 pr-batch의 `scripts/auth_keys.py`로 만든다.
  개인키는 여기에, 공개키는 pr-batch `keys/`에 두고 각각 빌드·배포한다.
- `*.pem`은 `.gitignore`로 막혀 있다. 개인키는 git에 올리지 않는다.
- 로컬 compose는 이 폴더 대신 `../pr-batch/.local-keys`를 마운트한다(`config.local.yml`).
