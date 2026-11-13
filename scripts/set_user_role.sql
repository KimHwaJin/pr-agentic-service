-- pr-agentic-service: 유저 권한(users.role) 변경
-- 허용 값: 'user' | 'admin'  (DB 제약은 없으므로 오타 주의)
-- 실행: psql postgresql://<user>:<pw>@<host>:5432/agentic -v emp=A10054 -f scripts/set_user_role.sql  (단계별로 나눠 실행 권장)
-- 대상 지정: employee_id(사번, 대소문자 무시). 스크립트: scripts/set_user_role.py
-- 반영: 각 파드의 유저 캐시(30초)가 지나면 다음 요청부터 적용, 재로그인 불필요

-- 1) 현재 상태 확인
SELECT id, employee_id, name, department, role, is_active, updated_at
FROM users
WHERE lower(employee_id) = lower(:'emp');

-- 현재 관리자 목록
SELECT id, employee_id, name, department, is_active
FROM users
WHERE role = 'admin'
ORDER BY name;

-- 2) 권한 변경 (트랜잭션 안에서 결과 확인 후 COMMIT)
BEGIN;

UPDATE users
SET role = 'admin',            -- 강등은 'user'
    updated_at = now()
WHERE lower(employee_id) = lower(:'emp')
RETURNING id, employee_id, name, role, updated_at;
-- 정확히 1행이 나왔는지 확인. 아니면 ROLLBACK;

-- (강등 시) 활성 관리자가 최소 1명 남는지 확인
SELECT count(*) AS active_admins FROM users WHERE role = 'admin' AND is_active;

COMMIT;
