"""Redis Sentinel 접속 진단 ("No master found for 'mymaster'" 원인 찾기).

파드 안에서 실행한다 (앱과 같은 네트워크, 같은 환경변수):

    python scripts/check_redis_sentinel.py
    python scripts/check_redis_sentinel.py --password-plain '평문비번'
    python scripts/check_redis_sentinel.py --sentinels h1:26379,h2:26379 \
        --master mymaster --password-plain '...' --sentinel-password-plain '...'

설정은 앱과 같은 순서로 읽는다: 환경변수 > config.{APP_ENV}.yml > config.yml.
REDIS / SENTINEL 이 들어간 키를 모두 모은 뒤 아래 이름에서 값을 찾고,
명령행 옵션이 있으면 그것이 이긴다. 비밀번호는 출력하지 않는다 (길이만).

암호화된 비밀번호는 --decrypt 로 앱이 쓰는 복호화 함수를 지정한다
("모듈경로:함수이름", 문자열 하나를 받아 평문을 돌려주는 함수).
평문을 직접 주려면 --password-plain / --sentinel-password-plain.

단계: (0) 설정과 TCP  (1) Sentinel PING, 인증 없이 / 인증 넣고
      (2) SENTINEL MASTERS  (3) get-master-addr-by-name
      (4) master_for 로 접속해 DB PING (sentinel_kwargs 넣고 / 빼고)
"""

from __future__ import annotations

import argparse
import importlib
import os
import socket
import sys
from pathlib import Path
from typing import Any

NODE_KEYS = (
    "REDIS_SENTINEL_NODES",
    "REDIS_SENTINEL_HOSTS",
    "REDIS_SENTINELS",
    "REDIS_SENTINEL_URLS",
    "REDIS_SENTINEL_URL",
    "REDIS_SENTINEL_ADDRESSES",
    "REDIS_SENTINEL_HOST",
    "SENTINEL_NODES",
    "SENTINEL_HOSTS",
)
PORT_KEYS = ("REDIS_SENTINEL_PORT", "SENTINEL_PORT")
MASTER_KEYS = (
    "REDIS_SENTINEL_MASTER",
    "REDIS_SENTINEL_MASTER_NAME",
    "REDIS_SENTINEL_SERVICE_NAME",
    "REDIS_SENTINEL_NAME",
    "REDIS_MASTER_NAME",
    "SENTINEL_MASTER",
    "SENTINEL_MASTER_NAME",
)
PASSWORD_KEYS = ("REDIS_PASSWORD", "REDIS_AUTH", "REDIS_PASS")
SENTINEL_PASSWORD_KEYS = (
    "REDIS_SENTINEL_PASSWORD",
    "REDIS_SENTINEL_AUTH",
    "SENTINEL_PASSWORD",
)
USERNAME_KEYS = ("REDIS_USERNAME", "REDIS_USER")
SENTINEL_USERNAME_KEYS = ("REDIS_SENTINEL_USERNAME", "SENTINEL_USERNAME")
DB_KEYS = ("REDIS_DB", "REDIS_DATABASE")
SSL_KEYS = ("REDIS_SSL", "REDIS_TLS", "REDIS_SENTINEL_SSL")

SECRET_WORDS = ("PASSWORD", "PASS", "AUTH", "SECRET", "KEY", "TOKEN")


def say(text: str = "") -> None:
    print(text, flush=True)


def mask(key: str, value: Any) -> str:
    text = str(value)
    if any(word in key.upper() for word in SECRET_WORDS):
        return f"(숨김, {len(text)}자)" if text else "(비어 있음)"
    if "://" in text and "@" in text:  # user:password@ in a URL
        head, _, tail = text.partition("://")
        return f"{head}://***@{tail.rpartition('@')[2]}"
    return text


def load_settings(root: Path, env: str) -> dict[str, tuple[Any, str]]:
    """REDIS/SENTINEL keys -> (value, where it came from), highest wins."""
    found: dict[str, tuple[Any, str]] = {}
    names = ["config.yml"] + ([f"config.{env}.yml"] if env else [])
    try:
        import yaml
    except ImportError:
        yaml = None
        say("  (PyYAML 없음: config 파일은 건너뛰고 환경변수만 봄)")
    for name in names:
        path = root / name
        if yaml is None or not path.is_file():
            if yaml is not None:
                say(f"  ({path} 없음)")
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, value in data.items():
            if _relevant(str(key)):
                found[str(key).upper()] = (value, name)
    for key, value in os.environ.items():
        if _relevant(key):
            found[key.upper()] = (value, "환경변수")
    return found


def _relevant(key: str) -> bool:
    upper = key.upper()
    return "REDIS" in upper or "SENTINEL" in upper


def pick(found: dict[str, tuple[Any, str]], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in found and found[key][0] not in (None, "", []):
            return found[key][0]
    return None


def parse_nodes(value: Any, default_port: int) -> list[tuple[str, int]]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip().strip("[]")
        items: list[Any] = [
            part.strip().strip("'\"")
            for part in text.replace(";", ",").split(",")
        ]
    else:
        items = list(value)
    nodes = []
    for item in items:
        if isinstance(item, dict):
            host = item.get("host") or item.get("HOST")
            port = item.get("port") or item.get("PORT") or default_port
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            host, port = item
        else:
            text = str(item).strip()
            if not text:
                continue
            text = text.split("://", 1)[-1].split("@")[-1].split("/")[0]
            host, _, port = text.rpartition(":")
            if not host:
                host, port = text, default_port
        if host:
            nodes.append((str(host), int(port)))
    return nodes


def decrypt_with(spec: str, value: str | None) -> str | None:
    if not spec or not value:
        return value
    module_name, _, func_name = spec.partition(":")
    func = getattr(importlib.import_module(module_name), func_name)
    return func(value)


def explain(exc: BaseException) -> str:
    """One line: what this failure usually means."""
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "noauth" in low or "authentication required" in low:
        return "인증 필요: 이 서버는 비밀번호를 요구하는데 보내지 않았음"
    if "wrongpass" in low or "invalid username-password" in low or (
        "invalid password" in low
    ):
        return "비밀번호(또는 사용자 이름)가 틀림. 복호화 결과가 맞는지 확인"
    if "without any password configured" in low or (
        "no password is set" in low
    ):
        return "이 서버는 비밀번호가 없는데 비밀번호를 보냄"
    if "unknown command" in low and "sentinel" in low:
        return "Sentinel 포트가 아니라 Redis 데이터 포트로 붙은 듯 (보통 26379)"
    if "name or service not known" in low or "getaddrinfo" in low or (
        "nodename nor servname" in low
    ):
        return "호스트 이름이 풀리지 않음 (DNS, 네임스페이스, 오타)"
    if "refused" in low:
        return "연결 거부: 포트가 틀렸거나 그 주소에서 듣고 있지 않음"
    if "timed out" in low or "timeout" in low:
        return "시간 초과: 방화벽/NetworkPolicy 로 막혔거나 주소가 틀림"
    if "ssl" in low or "wrong version number" in low:
        return "TLS 불일치: --ssl 을 켜거나 꺼서 다시 시도"
    if "connection closed" in low or "reset by peer" in low:
        return "서버가 끊음: TLS 포트에 평문으로 붙었거나 그 반대일 수 있음"
    if "no master found" in low:
        return "Sentinel 중 누구도 쓸 수 있는 master 를 주지 않음 (위 단계 참고)"
    return "위 오류 문구를 플랫폼 담당자에게 전달"


def tcp_check(host: str, port: int, timeout: float) -> str | None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as exc:
        return explain(exc) + f" [{exc}]"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Redis Sentinel 접속 진단",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--env", help="config.{env}.yml (기본: APP_ENV)")
    parser.add_argument("--config-dir", help="config*.yml 폴더 (기본: 저장소 루트)")
    parser.add_argument("--sentinels", help="host:port,host:port")
    parser.add_argument("--master", help="master 이름 (기본: 설정값 또는 mymaster)")
    parser.add_argument("--db", type=int, help="DB 번호 (기본: 설정값 또는 0)")
    parser.add_argument("--username", help="Redis ACL 사용자")
    parser.add_argument("--sentinel-username", help="Sentinel ACL 사용자")
    parser.add_argument("--password-plain", help="Redis 비밀번호 평문")
    parser.add_argument(
        "--sentinel-password-plain",
        help="Sentinel 비밀번호 평문 (기본: Redis 비밀번호와 같다고 봄)",
    )
    parser.add_argument(
        "--no-sentinel-password",
        action="store_true",
        help="Sentinel 에는 비밀번호가 없다고 보고 진행",
    )
    parser.add_argument(
        "--decrypt",
        default=os.environ.get("REDIS_CHECK_DECRYPT", ""),
        help="설정의 비밀번호를 푸는 함수 '모듈:함수' (평문 옵션에는 적용 안 함)",
    )
    parser.add_argument("--ssl", action="store_true", help="TLS 로 접속")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()

    try:
        import redis
        from redis.sentinel import Sentinel
    except ImportError:
        say("redis 패키지가 없습니다. 앱과 같은 파이썬(가상환경)으로 실행하세요.")
        return 2

    root = Path(args.config_dir) if args.config_dir else (
        Path(__file__).resolve().parents[1]
    )
    env = args.env or os.environ.get("APP_ENV", "")

    say(f"== 0. 설정 (APP_ENV={env or '없음'}, config 폴더={root}, "
        f"redis-py {redis.__version__})")
    found = load_settings(root, env)
    for key in sorted(found):
        value, source = found[key]
        say(f"  {key} = {mask(key, value)}   <- {source}")
    if not found:
        say("  REDIS/SENTINEL 이 들어간 설정이 하나도 없음")

    port = int(pick(found, PORT_KEYS) or 26379)
    nodes = parse_nodes(args.sentinels or pick(found, NODE_KEYS), port)
    master = args.master or pick(found, MASTER_KEYS) or "mymaster"
    db = args.db if args.db is not None else int(pick(found, DB_KEYS) or 0)
    username = args.username or pick(found, USERNAME_KEYS)
    sentinel_username = args.sentinel_username or pick(
        found, SENTINEL_USERNAME_KEYS
    )
    use_ssl = args.ssl or str(pick(found, SSL_KEYS) or "").lower() in (
        "1", "true", "yes", "on",
    )
    try:
        password = args.password_plain or decrypt_with(
            args.decrypt, pick(found, PASSWORD_KEYS)
        )
        sentinel_password = args.sentinel_password_plain or decrypt_with(
            args.decrypt, pick(found, SENTINEL_PASSWORD_KEYS)
        )
    except Exception as exc:  # noqa: BLE001 - report and stop
        say(f"  복호화 실패 ({args.decrypt}): {type(exc).__name__}: {exc}")
        say("  -> --password-plain 으로 평문을 직접 주고 다시 실행")
        return 2
    sentinel_password_guessed = False
    if args.no_sentinel_password:
        sentinel_password = None
    elif sentinel_password is None and password:
        sentinel_password, sentinel_password_guessed = password, True

    if not nodes:
        say()
        say("  Sentinel 주소를 찾지 못했습니다. 위 목록에 주소가 든 키가 있으면")
        say("  그 값을 --sentinels host:port,host:port 로 넘겨 다시 실행하세요.")
        return 2

    def length(value: str | None) -> str:
        return f"{len(value)}자" if value else "없음"

    say()
    say(f"  사용할 값: sentinels={nodes}")
    say(f"            master={master!r} (길이 {len(master)}), db={db}, "
        f"tls={use_ssl}")
    say(f"            redis 비밀번호={length(password)}, "
        f"sentinel 비밀번호={length(sentinel_password)}"
        + (" (따로 없어 redis 것과 같다고 가정)"
           if sentinel_password_guessed else ""))
    if master != master.strip():
        say("  !! master 이름 앞뒤에 공백이 있음: 이것만으로 못 찾습니다")
    for label, secret in (("redis", password), ("sentinel", sentinel_password)):
        if secret and secret != secret.strip():
            say(f"  !! {label} 비밀번호 앞뒤에 공백/줄바꿈이 있음")
    for host, node_port in nodes:
        problem = tcp_check(host, node_port, args.timeout)
        say(f"  TCP {host}:{node_port}  " + ("OK" if problem is None
                                             else f"실패 -> {problem}"))

    common: dict[str, Any] = {
        "socket_timeout": args.timeout,
        "socket_connect_timeout": args.timeout,
        "decode_responses": True,
    }
    if use_ssl:
        common["ssl"] = True
        common["ssl_cert_reqs"] = "none"
    sentinel_auth: dict[str, Any] = {}
    if sentinel_password:
        sentinel_auth["password"] = sentinel_password
    if sentinel_username:
        sentinel_auth["username"] = sentinel_username

    def sentinel_client(host: str, node_port: int, auth: bool) -> Any:
        return redis.Redis(
            host=host, port=node_port, **common, **(sentinel_auth if auth else {})
        )

    verdicts: list[str] = []

    # 1. PING each sentinel, without and with auth
    say()
    say("== 1. Sentinel PING")
    needs_auth = False
    auth_works = False
    for host, node_port in nodes:
        for auth in (False, True):
            if auth and not sentinel_auth:
                continue
            label = "인증 넣고" if auth else "인증 없이"
            try:
                sentinel_client(host, node_port, auth).ping()
                say(f"  {host}:{node_port} {label}: OK")
                auth_works = auth_works or auth
            except Exception as exc:  # noqa: BLE001
                say(f"  {host}:{node_port} {label}: 실패 -> {explain(exc)} "
                    f"[{type(exc).__name__}: {exc}]")
                if not auth and "auth" in str(exc).lower():
                    needs_auth = True
    if needs_auth and not sentinel_auth:
        verdicts.append(
            "Sentinel 이 비밀번호를 요구하는데 넘길 비밀번호가 없음: "
            "--sentinel-password-plain 으로 다시 실행"
        )
    elif needs_auth and not auth_works:
        verdicts.append("Sentinel 비밀번호가 틀림 (Redis 비밀번호와 다를 수 있음)")
    # use auth from here on only when it is needed or works
    use_auth = bool(sentinel_auth) and (needs_auth or auth_works)

    # 2. SENTINEL MASTERS
    say()
    say("== 2. SENTINEL MASTERS (Sentinel 이 아는 master 목록)")
    known: dict[str, dict[str, Any]] = {}
    for host, node_port in nodes:
        try:
            masters = sentinel_client(host, node_port, use_auth).sentinel_masters()
        except Exception as exc:  # noqa: BLE001
            say(f"  {host}:{node_port}: 실패 -> {explain(exc)} "
                f"[{type(exc).__name__}: {exc}]")
            continue
        if not masters:
            say(f"  {host}:{node_port}: master 가 하나도 등록되어 있지 않음")
        for name, state in masters.items():
            known.setdefault(name, state)
            say(f"  {host}:{node_port}: name={name!r} "
                f"addr={state.get('ip')}:{state.get('port')} "
                f"flags={state.get('flags')} "
                f"slaves={state.get('num-slaves')} "
                f"other-sentinels={state.get('num-other-sentinels')} "
                f"quorum={state.get('quorum')}")
            if state.get("is_sdown") or state.get("is_odown"):
                say("    !! s_down/o_down: Sentinel 이 이 master 를 죽었다고 봄. "
                    "redis-py 는 이런 master 를 건너뛰어 'No master found' 가 됨")
    if known and master not in known:
        verdicts.append(
            f"master 이름 불일치: 설정은 {master!r}, Sentinel 에 있는 이름은 "
            f"{sorted(known)} (대소문자, 공백 포함해서 정확히 같아야 함)"
        )
    elif master in known and (
        known[master].get("is_sdown") or known[master].get("is_odown")
    ):
        verdicts.append(
            "Sentinel 이 master 를 down 으로 보고 있음: Redis 쪽 상태 문제 "
            "(플랫폼 담당자 확인 필요)"
        )

    # 3. get-master-addr-by-name
    say()
    say(f"== 3. SENTINEL get-master-addr-by-name {master}")
    master_addr: tuple[str, int] | None = None
    for host, node_port in nodes:
        try:
            addr = sentinel_client(
                host, node_port, use_auth
            ).sentinel_get_master_addr_by_name(master)
        except Exception as exc:  # noqa: BLE001
            say(f"  {host}:{node_port}: 실패 -> {explain(exc)} "
                f"[{type(exc).__name__}: {exc}]")
            continue
        if not addr:
            say(f"  {host}:{node_port}: 그런 이름의 master 없음 (nil)")
            continue
        say(f"  {host}:{node_port}: {addr[0]}:{addr[1]}")
        master_addr = master_addr or (str(addr[0]), int(addr[1]))
    if master_addr:
        problem = tcp_check(*master_addr, args.timeout)
        say(f"  master TCP {master_addr[0]}:{master_addr[1]}  "
            + ("OK" if problem is None else f"실패 -> {problem}"))
        if problem:
            verdicts.append(
                f"Sentinel 이 알려 준 master 주소 {master_addr[0]}:"
                f"{master_addr[1]} 에 이 파드에서 닿지 않음 (내부 IP/다른 망)"
            )

    # 4. the way an app connects: Sentinel(...).master_for(name)
    say()
    say("== 4. master_for 접속 후 PING")
    data_auth: dict[str, Any] = {"db": db}
    if password:
        data_auth["password"] = password
    if username:
        data_auth["username"] = username
    variants = [
        ("sentinel_kwargs 에 Sentinel 인증을 넣음", {**common, **sentinel_auth}),
        ("sentinel_kwargs 없이 (Redis 비밀번호만 넘김)", None),
    ]
    results: dict[str, bool] = {}
    for label, sentinel_kwargs in variants:
        try:
            sentinel = Sentinel(
                nodes, sentinel_kwargs=sentinel_kwargs, **common, **data_auth
            )
            sentinel.master_for(master).ping()
            say(f"  {label}: OK")
            results[label] = True
        except Exception as exc:  # noqa: BLE001
            say(f"  {label}: 실패 -> {explain(exc)} "
                f"[{type(exc).__name__}: {exc}]")
            results[label] = False
    with_kwargs, without_kwargs = (results[label] for label, _ in variants)
    if with_kwargs and not without_kwargs:
        verdicts.append(
            "앱 코드 문제일 가능성 큼: Sentinel(...) 을 만들 때 "
            "sentinel_kwargs={'password': ...} 를 넘겨야 함. redis-py 는 "
            "password= 를 master/replica 에만 쓰고 Sentinel 에는 보내지 않으며, "
            "Sentinel 인증 실패는 'No master found' 로만 보임"
        )
    elif with_kwargs and without_kwargs:
        verdicts.append(
            "이 스크립트로는 정상 접속됨: 앱이 읽는 값(주소, master 이름, "
            "복호화된 비밀번호)이 위 0번과 다른지 확인"
        )
    elif not with_kwargs and master_addr and not any(
        "닿지 않음" in v for v in verdicts
    ):
        verdicts.append(
            "Sentinel 은 master 를 알려 주는데 master 접속/인증에서 실패: "
            "Redis 비밀번호, 사용자, TLS 를 확인"
        )

    say()
    say("== 결론")
    if not verdicts:
        verdicts.append("단정할 원인을 못 찾음: 위 출력 전체를 공유해 주세요")
    for line in verdicts:
        say(f"  - {line}")
    return 0 if with_kwargs else 1


if __name__ == "__main__":
    raise SystemExit(main())
