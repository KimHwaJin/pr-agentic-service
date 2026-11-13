"""pr-agentic-service 유저 권한(users.role) 변경 스크립트.

저장소 루트에서 서비스와 같은 설정(APP_ENV, config.*.yml, .env)으로 실행:

    uv run python scripts/set_user_role.py --list
    uv run python scripts/set_user_role.py A10054 admin --dry-run
    uv run python scripts/set_user_role.py A10054 admin
    uv run python scripts/set_user_role.py a10054 user

대상은 사번(employee_id, 대소문자 무시) 또는 users.id. --dsn 이나 환경변수
DATABASE_URL 을 주면 config 대신 그 DB 에 접속한다.

변경은 각 파드의 유저 캐시(api_service.deps.USER_CACHE_SECONDS=30초)가 지나면
다음 요청부터 적용되고 재로그인은 필요 없다. ADMIN_EMPLOYEE_IDS 는 최초
로그인 때만 쓰이므로 이후 로그인이 여기서 바꾼 값을 덮어쓰지 않는다.
"""

import argparse
import os
import sys

import psycopg

ROLES = ("user", "admin")
COLS = "id, employee_id, name, department, role, is_active"


def dsn_of(arg: str | None) -> str:
    url = arg or os.environ.get("DATABASE_URL")
    if not url:
        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "src")
        )
        from core.config import get_settings

        url = get_settings().database_url
    return url.replace("postgresql+psycopg://", "postgresql://")


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
        "--dsn", help="PostgreSQL URL (기본: DATABASE_URL 또는 config)"
    )
    a = p.parse_args()
    if not a.list and not (a.target and a.role):
        p.error("target 과 role 이 필요합니다 (또는 --list)")

    with psycopg.connect(dsn_of(a.dsn)) as conn:
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
