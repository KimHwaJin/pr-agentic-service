"""pr-agentic-service 유저 권한(users.role) 변경 스크립트.

저장소 루트에서 실행:

    uv run python scripts/set_user_role.py --env prd --list
    uv run python scripts/set_user_role.py --env prd A10054 admin --dry-run
    uv run python scripts/set_user_role.py --env prd A10054 admin
    uv run python scripts/set_user_role.py --env prd a10054 user

대상은 사번(employee_id, 대소문자 무시) 또는 users.id.

접속할 DB(DATABASE_URL): --dsn 이 가장 우선. --env prd 를 주면
config.prd.yml(없으면 config.yml)의 값만 쓰고 환경변수와 .env 는 보지 않는다.
--env 가 없으면 서비스와 같은 순서로 찾는다: 환경변수 DATABASE_URL, .env,
config.{APP_ENV}.yml, config.yml. 어느 곳의 어떤 DB 인지 실행 전에 출력한다
(비밀번호는 가림).

변경은 각 파드의 유저 캐시(api_service.deps.USER_CACHE_SECONDS=30초)가 지나면
다음 요청부터 적용되고 재로그인은 필요 없다. ADMIN_EMPLOYEE_IDS 는 최초
로그인 때만 쓰이므로 이후 로그인이 여기서 바꾼 값을 덮어쓰지 않는다.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg
import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]

ROLES = ("user", "admin")
COLS = "id, employee_id, name, department, role, is_active"


def _key(values: dict | None, key: str) -> str | None:
    """A config value by case-insensitive key (as the service reads it)."""
    for k, v in (values or {}).items():
        if isinstance(k, str) and k.lower() == key.lower() and v:
            return str(v)
    return None


def dsn_of(dsn: str | None, env: str | None) -> tuple[str, str]:
    """(DATABASE_URL, where it came from), highest precedence first."""
    found = [("--dsn", dsn)]
    if not env:  # the service's order: environment, .env, then files
        dotenv = dotenv_values(ROOT / ".env", encoding="utf-8")
        env = os.environ.get("APP_ENV") or dotenv.get("APP_ENV")
        found.append(("DATABASE_URL", os.environ.get("DATABASE_URL")))
        found.append((".env", _key(dotenv, "DATABASE_URL")))
    if env:
        path = ROOT / f"config.{env}.yml"
        if not path.is_file():
            sys.exit(f"{path.name} 이 없습니다.")
        found.append((path.name, _key(_yaml(path), "DATABASE_URL")))
    common = ROOT / "config.yml"
    if common.is_file():
        found.append((common.name, _key(_yaml(common), "DATABASE_URL")))
    for source, url in found:
        if url:
            return url.replace(
                "postgresql+psycopg://", "postgresql://"
            ), source
    sys.exit("DATABASE_URL 을 찾지 못했습니다. --env 나 --dsn 을 주세요.")


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text("utf-8")) or {}


def masked(url: str) -> str:
    return re.sub(r"(//[^:/@]+:)[^@]*@", r"\1***@", url)


def show(rows) -> None:
    for r in rows:
        state = "active" if r[5] else "inactive"
        print(
            f"  {r[1]:<12} {r[4]:<6} {state:<8} "
            f"{r[2]} ({r[3] or '-'})  id={r[0]}"
        )


def main() -> int:
    p = argparse.ArgumentParser(description="유저 권한(user|admin) 변경")
    p.add_argument("target", nargs="?", help="사번(employee_id) 또는 users.id")
    p.add_argument("role", nargs="?", choices=ROLES)
    p.add_argument("--list", action="store_true", help="관리자 목록만 출력")
    p.add_argument(
        "--dry-run", action="store_true", help="바꾸지 않고 결과만 확인"
    )
    p.add_argument(
        "--env",
        choices=("dev", "stg", "prd"),
        help="config.{env}.yml 의 DATABASE_URL (기본: APP_ENV)",
    )
    p.add_argument("--dsn", help="PostgreSQL URL (가장 우선)")
    a = p.parse_args()
    if not a.list and not (a.target and a.role):
        p.error("target 과 role 이 필요합니다 (또는 --list)")

    url, source = dsn_of(a.dsn, a.env)
    print(f"DB: {masked(url)}  ({source})")
    with psycopg.connect(url) as conn:
        if a.list:
            rows = conn.execute(
                f"SELECT {COLS} FROM users WHERE role = 'admin' ORDER BY name"
            ).fetchall()
            print(f"관리자 {len(rows)}명")
            show(rows)
            return 0

        rows = conn.execute(
            f"SELECT {COLS} FROM users WHERE id = %s"
            " OR lower(employee_id) = lower(%s) FOR UPDATE",
            (a.target, a.target),
        ).fetchall()
        if len(rows) != 1:
            print(
                f"대상 유저가 {len(rows)}명입니다: {a.target}", file=sys.stderr
            )
            show(rows)
            return 1
        user = rows[0]
        print("변경 전")
        show([user])
        if user[4] == a.role:
            print(f"이미 {a.role} 입니다. 변경 없음.")
            return 0

        if user[4] == "admin" and a.role != "admin":
            left = conn.execute(
                "SELECT count(*) FROM users"
                " WHERE role = 'admin' AND is_active AND id <> %s",
                (user[0],),
            ).fetchone()[0]
            if left == 0:
                print(
                    "마지막 활성 관리자는 강등할 수 없습니다.", file=sys.stderr
                )
                return 1

        after = conn.execute(
            "UPDATE users SET role = %s, updated_at = now()"
            f" WHERE id = %s RETURNING {COLS}",
            (a.role, user[0]),
        ).fetchall()
        print("변경 후")
        show(after)
        if a.dry_run:
            conn.rollback()
            print("--dry-run: 롤백했습니다.")
        else:
            conn.commit()
            print("커밋했습니다. 30초 안에 모든 파드에 적용됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
