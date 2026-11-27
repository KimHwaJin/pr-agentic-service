"""Writes every column into 04 (logical ERD), 05 (physical ERD) and the new
06-table-definition.md. Sections it owns are replaced on each run."""
import os
import re
import sys

from names import full_schema, _rename

H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "handover") + os.sep
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep
S = full_schema(H + "03-db-physical.md")
T = S["tables"]
ALL = S["order"] + S["extra_order"]
logical = open(H + "02-db-logical.md", encoding="utf-8").read()
DESC = {m.group(1): m.group(3).replace("`", "").strip()
        for m in re.finditer(r"\*\*([a-z_]+) \(([^)]+)\)\*\*\n(.+)", logical)}


def about(n):
    return _rename(T[n].get("about") or DESC.get(n, ""))


def esc(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def expand_indexes():
    out = []
    for x in S["indexes"] + S["extra_indexes"]:
        if ", _" in x["name"] and x["cols"].strip() == "각 컬럼":
            parts = [p.strip() for p in x["name"].split(",")]
            base = parts[0]
            first_col = base.split("_")[-1]
            stem = base[: -len(first_col)]
            # ix_code_sources_session_id: the column is the part after the table name
            tname = x["table"]
            prefix = f"ix_{tname}_"
            names = [base] + [prefix + p.lstrip("_") for p in parts[1:]]
            for nm in names:
                out.append(dict(x, name=nm, cols=nm[len(prefix):]))
        else:
            out.append(x)
    return out


USE = {"ix_code_sources_session_id": "대화별 코드 조회", "ix_code_sources_run_id": "run별 코드 조회",
       "ix_code_sources_execution_id": "실행별 코드 조회", "ix_code_sources_created_at": "보존 정리",
       "ix_batch_report_jobs_owner_id": "내 리포트 목록", "ix_batch_report_jobs_execution_id": "실행별 리포트 찾기",
       "ix_batch_report_jobs_batch_id": "배치별 리포트 목록", "ix_batch_report_jobs_state": "처리할 작업 고르기",
       "ix_batch_report_events_job_id": "작업의 이벤트", "ix_batch_report_events_created_at": "보존 정리"}
IDX = [dict(x, use=USE.get(x["name"], x["use"])) for x in expand_indexes()]


def nullable(c):
    return "필수" if c["null"] == "N" else "선택"


def replace_section(text, head, body, before=None):
    """Replace the section that starts with `head` (up to the next same-level
    heading) or insert it before `before` / at the end."""
    n = len(head.split(" ")[0])
    pat = re.compile(r"^" + re.escape(head) + r".*?(?=^#{1," + str(n) + r"} |\Z)", re.M | re.S)
    if pat.search(text):
        return pat.sub(lambda m: body.rstrip() + "\n\n", text, count=1)
    if before and before in text:
        i = text.index(before)
        return text[:i] + body.rstrip() + "\n\n" + text[i:]
    return text.rstrip() + "\n\n" + body.rstrip() + "\n"


# ---------------------------------------------------------------- 04 logical
def logical_section(num):
    out = [f"## {num}. 엔티티별 속성", "",
           "모든 엔티티의 모든 속성입니다. 앱 테이블 19개와 같은 데이터베이스에 있는 LangGraph, Alembic 테이블 7개를 함께 적었습니다. "
           "키는 PK 기본키, FK 외래키 제약, UK 유일 제약입니다. 필수는 값이 반드시 있어야 하는 속성입니다.", ""]
    for i, n in enumerate(ALL, 1):
        t = T[n]
        out += [f"### {num}.{i} {n} ({t['ko']})", ""]
        if about(n):
            out += [about(n), ""]
        out += ["| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |", "| --- | --- | --- | --- | --- | --- |"]
        for j, c in enumerate(t["cols"], 1):
            out.append(f"| {j} | {esc(c['ko'])} | `{c['name']}` | {c['key']} | {nullable(c)} | {esc(c['desc'])} |")
        out.append("")
    return "\n".join(out)


p = D + "04-erd-logical.md"
t = open(p, encoding="utf-8").read()
t = t.replace("| 그림 원본 | `diagrams/04-erd-logical.drawio` (페이지 3장) |",
              "| 그림 원본 | `diagrams/04-erd-logical.drawio` (페이지 4장) |")
t = t.replace("컬럼 단위 정의는 `06-table-definition.xlsx`(Table 정의서)에 있습니다.",
              "엔티티마다 모든 속성은 9절에 있습니다. 데이터 타입과 기본값은 `06-table-definition.md`, `06-table-definition.xlsx`(Table 정의서)에 있습니다.")
t = replace_section(t, "### 3.4 LangGraph", "### 3.4 LangGraph 체크포인트와 store, 마이그레이션 버전\n\n"
                    "Agent의 대화 상태와 store, 스키마 버전 기록입니다. 앱 테이블과 외래키 제약은 없고 값으로만 이어집니다.\n\n"
                    "![논리 ERD LangGraph, Alembic](diagrams/export/04-erd-logical-4.png)\n", before="## 4. 엔티티 정의")
t = re.sub(r"이 테이블들은 LangGraph 라이브러리가 만들고 관리합니다\. 구조를 직접 바꾸지 않습니다\.( 모든 속성은 9\.20~9\.26절에 있습니다\.)*",
           "이 테이블들은 LangGraph 라이브러리가 만들고 관리합니다. 구조를 직접 바꾸지 않습니다. 모든 속성은 9.20~9.26절에 있습니다.", t)
t = t.replace("| 프로젝트 메모리 | store | namespace에 프로젝트 id | 주제 목록과 주제별 본문 |",
              "| store | store | prefix = 이름공간 | `project_memory.{project_id}` 프로젝트 메모리 본문, `tool_effects.{run_id}` 도구의 executor 요청 결과, `batch_memory.{batch_id}` 배치 리포트 요약 |")
REL = [
    # 부모, 자식, 관계, 조인 조건, FK 제약, 비고
    ("users", "projects", "1:N", "projects.created_by = users.id", "있음", "프로젝트를 만든 사용자"),
    ("projects", "project_members", "1:N", "project_members.project_id = projects.id", "있음", "users와 projects의 N:M 연결 테이블. 현재는 프로젝트당 owner 1명"),
    ("users", "project_members", "1:N", "project_members.user_id = users.id", "있음", ""),
    ("projects", "sessions", "1:N", "sessions.project_id = projects.id", "있음", ""),
    ("users", "sessions", "1:N", "sessions.user_id = users.id", "있음", ""),
    ("sessions", "messages", "1:N", "messages.session_id = sessions.id", "있음", ""),
    ("sessions", "runs", "1:N", "runs.session_id = sessions.id", "있음", ""),
    ("runs", "sessions", "1:0..1", "sessions.active_run_id = runs.id", "없음", "지금 진행 중인 run. 세션당 1개, 없으면 NULL"),
    ("projects", "runs", "1:N", "runs.project_id = projects.id", "없음", "조회용 사본. runs.session_id로 찾은 세션의 project_id와 같음"),
    ("users", "runs", "1:N", "runs.user_id = users.id", "없음", "조회용 사본"),
    ("runs", "messages", "1:N", "messages.run_id = runs.id", "없음", "한 턴의 사용자 메시지와 답변. 비어 있을 수 있음"),
    ("runs", "run_events", "1:N", "run_events.run_id = runs.id", "없음", ""),
    ("sessions", "run_events", "1:N", "run_events.session_id = sessions.id", "없음", ""),
    ("sessions", "run_requests", "1:N", "run_requests.session_id = sessions.id", "없음", "기본키 (session_id, key)의 앞부분"),
    ("runs", "run_requests", "1:N", "run_requests.run_id = runs.id", "없음", "그 요청 키로 처음 만든 run"),
    ("runs", "executor_inbox", "1:N", "runs.waiting->>'execution_id' = executor_inbox.execution_id", "없음", "executor를 기다리는 run만. runs.waiting은 jsonb"),
    ("runs", "code_sources", "1:N", "code_sources.run_id = runs.id", "없음", ""),
    ("sessions", "code_sources", "1:N", "code_sources.session_id = sessions.id", "없음", ""),
    ("projects", "code_sources", "1:N", "code_sources.project_id = projects.id", "없음", ""),
    ("users", "code_sources", "1:N", "code_sources.user_id = users.id", "없음", "코드를 만든 사용자"),
    ("users", "code_sources", "1:N", "code_sources.approved_by = users.id", "없음", "승인한 사용자. 승인 전에는 NULL"),
    ("sessions", "images", "1:N", "images.session_id = sessions.id", "없음", ""),
    ("projects", "images", "1:N", "images.project_id = projects.id", "없음", ""),
    ("users", "images", "1:N", "images.user_id = users.id", "없음", ""),
    ("runs", "images", "1:N", "images.run_id = runs.id", "없음", "이미지를 처음 쓴 run. 비어 있을 수 있음"),
    ("projects", "memory_history", "1:N", "memory_history.project_id = projects.id", "없음", ""),
    ("sessions", "memory_history", "1:N", "memory_history.session_id = sessions.id", "없음", "Agent가 바꾼 경우만"),
    ("runs", "memory_history", "1:N", "memory_history.run_id = runs.id", "없음", "Agent가 바꾼 경우만"),
    ("users", "memory_history", "1:N", "memory_history.actor_id = users.id (actor_type = 'user')", "없음", "actor_type이 agent이면 actor_id는 run id"),
    ("projects", "memory_extraction_state", "1:1", "memory_extraction_state.project_id = projects.id", "없음", "기본키가 project_id"),
    ("messages", "memory_extraction_state", "1:N", "memory_extraction_state.processed_until_id = messages.id", "없음", "정리를 마친 마지막 메시지. 처음에는 빈 문자열"),
    ("users", "workflows", "1:N", "workflows.author_id = users.id", "있음", ""),
    ("runs", "workflows", "1:N", "workflows.source_run_id = runs.id", "없음", "워크플로우를 만든 대화의 run"),
    ("workflows", "workflows", "1:N", "workflows.source_workflow_id = workflows.id", "없음", "복사해 온 원본 워크플로우"),
    ("workflows", "workflow_query_vectors", "1:N", "workflow_query_vectors.workflow_id = workflows.id", "있음", ""),
    ("users", "batch_report_jobs", "1:N", "batch_report_jobs.owner_id = users.id", "없음", "배치를 만든 사용자. 그 사용자만 리포트를 봄"),
    ("batch_report_jobs", "batch_report_events", "1:N", "batch_report_events.job_id = batch_report_jobs.id", "없음", ""),
    ("users", "gaia_sessions", "1:N", "gaia_sessions.user_id = users.id", "있음", ""),
    ("sessions", "gaia_sessions", "1:N", "gaia_sessions.session_id = sessions.id", "있음", ""),
    ("users", "api_clients", "1:N", "api_clients.created_by = users.id", "없음", "키를 발급한 관리자"),
    ("sessions", "checkpoints", "1:N", "checkpoints.thread_id = sessions.id", "없음", "LangGraph 테이블"),
    ("checkpoints", "checkpoints", "1:N", "checkpoints.parent_checkpoint_id = checkpoints.checkpoint_id (같은 thread_id, checkpoint_ns)", "없음", "바로 앞 체크포인트"),
    ("checkpoints", "checkpoint_blobs", "1:N", "checkpoint_blobs.(thread_id, checkpoint_ns) = checkpoints.(thread_id, checkpoint_ns), channel과 version은 checkpoints.checkpoint의 channel_versions 값", "없음", "같은 버전의 값은 여러 체크포인트가 함께 참조"),
    ("checkpoints", "checkpoint_writes", "1:N", "checkpoint_writes.(thread_id, checkpoint_ns, checkpoint_id) = checkpoints.(thread_id, checkpoint_ns, checkpoint_id)", "없음", ""),
    ("projects", "store", "1:N", "store.prefix = CONCAT('project_memory.', projects.id)", "없음", "프로젝트 메모리 본문"),
    ("runs", "store", "1:N", "store.prefix = CONCAT('tool_effects.', runs.id)", "없음", "도구 실행 결과"),
    ("batch_report_jobs", "store", "1:N", "store.prefix = CONCAT('batch_memory.', batch_report_jobs.batch_id)", "없음", "배치 리포트 요약. batch_id는 batch 서비스의 배치 id"),
]
EXT_REF = [
    # 컬럼, 가리키는 것
    ("executor_inbox.execution_id, code_sources.execution_id, batch_report_jobs.execution_id, runs.waiting->>'execution_id'", "executor의 실행 id"),
    ("executor_inbox.event_id, executor_inbox.event_sequence", "executor가 보낸 이벤트 id와 실행 안 순번"),
    ("code_sources.operation_id, code_sources.step_id", "executor의 작업(operation)과 단계(step) id"),
    ("batch_report_jobs.artifact_id", "executor에 저장된 리포트 Artifact id"),
    ("batch_report_jobs.batch_id, batch_report_jobs.batch_run_id", "batch 서비스의 배치 id와 배치 실행 id"),
    ("gaia_sessions.gaia_session_id", "gaia 채팅 화면의 세션 id"),
    ("code_sources.tool_call_id", "Agent 대화 안의 도구 호출 id (체크포인트의 메시지에 있음)"),
    ("api_clients.tenant", "executor tenant 이름"),
]


def rel_section(num, title="관계와 카디널리티", note=""):
    out = [f"## {num}. {title}", "",
           "테이블 사이의 모든 참조를 한 줄에 하나씩 적었습니다. 조인 조건은 그대로 SQL에 쓸 수 있는 형태입니다. "
           "FK 제약이 없음인 관계는 DB가 값을 검사하지 않으므로, 부모 행이 지워졌거나 값이 비어 있을 수 있습니다(LEFT JOIN 권장)." + note, "",
           "| 부모 | 자식 | 관계 | 조인 조건 | FK 제약 | 비고 |", "| --- | --- | --- | --- | --- | --- |"]
    out += [f"| {p} | {c} | {r} | `{j}` | {fk} | {esc(note)} |" for p, c, r, j, fk, note in REL]
    out += ["", f"### {num}.1 DB 밖을 가리키는 식별자", "",
            "아래 컬럼은 우리 DB의 다른 테이블이 아니라 다른 시스템의 값을 담습니다. 우리 DB 안에서는 조인 대상이 없습니다.", "",
            "| 컬럼 | 가리키는 것 |", "| --- | --- |"]
    out += [f"| `{c}` | {w} |" for c, w in EXT_REF]
    return "\n".join(out) + "\n"


def build_ref():
    """(table, column) -> what the column points at, for the 참조 column of 05."""
    ref = {}
    for p, c, r, j, fk, note in REL:
        m = re.fullmatch(r"([a-z_]+)\.([a-z_]+) = ([a-z_]+\.[a-z_]+)", j)
        if m:
            ref[(m.group(1), m.group(2))] = m.group(3) + (" (FK)" if fk == "있음" else " (값만)")
    ref.update({
        ("runs", "waiting"): "executor_inbox.execution_id (값만, waiting->>'execution_id')",
        ("memory_history", "actor_id"): "users.id 또는 runs.id (값만, actor_type에 따라)",
        ("checkpoints", "parent_checkpoint_id"): "checkpoints.checkpoint_id (값만)",
        ("checkpoint_blobs", "thread_id"): "sessions.id (값만)",
        ("checkpoint_writes", "thread_id"): "sessions.id (값만)",
        ("checkpoint_writes", "checkpoint_id"): "checkpoints.checkpoint_id (값만)",
        ("store", "prefix"): "접두어 + projects.id, runs.id, batch_id (값만)",
    })
    for cols, what in EXT_REF:
        for c in cols.split(", "):
            if "->>" in c:
                continue
            tb, col = c.split(".")
            ref.setdefault((tb, col), "DB 밖: " + what)
    return ref


REF = build_ref()
for _n in ALL:
    for _c in T[_n]["cols"]:
        _c["ref"] = REF.get((_n, _c["name"])) or ((_c["fk"] + " (FK)") if _c["fk"] else "")


t = replace_section(t, "## 5. 관계와 카디널리티", rel_section(5))
t = replace_section(t, "## 9. 엔티티별 속성", logical_section(9))
open(p, "w", encoding="utf-8").write(t.rstrip() + "\n")

# ---------------------------------------------------------------- 05 physical
def physical_section(num):
    out = [f"## {num}. 테이블별 컬럼", "",
           "모든 테이블의 모든 컬럼입니다. NULL이 N이면 NOT NULL, 기본값의 (앱)은 DB가 아니라 애플리케이션이 넣는 값입니다. "
           "참조의 (FK)는 외래키 제약이 있는 것, (값만)은 제약 없이 값으로만 가리키는 것, DB 밖은 다른 시스템의 값입니다. 조인 조건은 7절에 있습니다. "
           "설명까지 담은 정의는 `06-table-definition.md`에 있습니다.", ""]
    for i, n in enumerate(ALL, 1):
        t = T[n]
        out += [f"### {num}.{i} {n} ({t['ko']})", "", f"기본키 {t['pk']}. 행 증가: {t['growth']}. 자동 정리: {t['cleanup']}.", "",
                "| No | 컬럼 | 데이터 타입 | NULL | 키 | 기본값 | 참조 |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for j, c in enumerate(t["cols"], 1):
            out.append(f"| {j} | `{c['name']}` | {c['type']} | {c['null']} | {c['key']} | {esc(c['default'])} | {esc(c['ref'])} |")
        out.append("")
    return "\n".join(out)


p = D + "05-erd-physical.md"
t = open(p, encoding="utf-8").read()
t = t.replace("| 그림 원본 | `diagrams/05-erd-physical.drawio` (페이지 2장) |",
              "| 그림 원본 | `diagrams/05-erd-physical.drawio` (페이지 3장) |")
t = t.replace("컬럼의 NULL 여부, 기본값, 설명은 `06-table-definition.xlsx`(Table 정의서)에 있습니다.",
              "모든 테이블의 모든 컬럼은 6절에 있습니다. 컬럼 설명까지 담은 정의는 `06-table-definition.md`, `06-table-definition.xlsx`(Table 정의서)에 있습니다.")
t = t.replace("회색 테이블(users, projects)은 2.1의 테이블을 다시 그린 것입니다.",
              "회색 테이블(users, projects)은 2.1의 테이블을 모든 컬럼과 함께 다시 그린 것입니다.")
t = replace_section(t, "### 2.3 LangGraph", "### 2.3 LangGraph 체크포인트와 store, 마이그레이션 버전\n\n"
                    "LangGraph 라이브러리와 Alembic이 만드는 테이블입니다. 회색 sessions는 2.1의 테이블입니다.\n\n"
                    "![물리 ERD 3](diagrams/export/05-erd-physical-3.png)\n", before="## 3. 테이블 목록")
t = t.replace("기본키와 UNIQUE 제약의 인덱스는 생략했습니다.",
              "기본키와 UNIQUE 제약이 만드는 인덱스는 6절 표의 PK, UK 컬럼에 있습니다. 아래는 그 밖의 인덱스 전부입니다.")
# rewrite the index table of section 4 from the full index list
lines = t.split("\n")
s = lines.index("## 4. 인덱스")
i = s
while not lines[i].startswith("|"):
    i += 1
j = i
while j < len(lines) and lines[j].startswith("|"):
    j += 1
table = ["| 테이블 | 인덱스 | 컬럼 | 받치는 조회 |", "| --- | --- | --- | --- |"]
table += [f"| {x['table']} | {x['name']} | {esc(x['cols'])} | {esc(x['use'])} |" for x in IDX]
lines[i:j] = table
t = "\n".join(lines)
t = replace_section(t, "## 6. 테이블별 컬럼", physical_section(6))
t = replace_section(t, "## 7. 참조 관계와 조인 조건", rel_section(7, "참조 관계와 조인 조건",
                    " FK 제약은 모두 ON DELETE 지정이 없어(NO ACTION) 부모 행을 지우기 전에 자식 행을 먼저 지워야 합니다. "
                    "다만 프로젝트, 세션, 워크플로우는 실제로 지우지 않고 deleted_at만 적습니다."))
t = t.replace("모든 테이블의 모든 컬럼은 6절에 있습니다. 컬럼 설명까지",
              "모든 테이블의 모든 컬럼은 6절, 테이블 사이의 모든 참조와 조인 조건은 7절에 있습니다. 컬럼 설명까지")
open(p, "w", encoding="utf-8").write(t.rstrip() + "\n")

# ---------------------------------------------------------------- 06 table definition
out = ["# Table 정의서", "",
       "| 항목 | 내용 |", "| --- | --- |",
       "| 시스템 | gaia-api-service (사내 데이터 분석 Agent 서비스) |",
       "| 스키마 버전 | 마이그레이션 0008 |",
       "| DBMS | PostgreSQL, `vector` 확장(pgvector) 필요. 스키마 `public` |",
       "| 데이터베이스 | dev: `dtest` / prd: `dtestprd` (`DATABASE_URL`의 마지막 부분) |",
       "| 모델 정의 | `src/dtest/core/models.py`, `src/dtest/gaia_bridge/models.py` |",
       "| 마이그레이션 | `src/dtest/migrations/versions/` (Alembic, 0001~0008) |",
       "| 같은 내용의 엑셀 | `06-table-definition.xlsx` |", "",
       "## 1. 표기 규칙", "",
       "| 항목 | 규칙 |", "| --- | --- |",
       "| 타입 | `varchar(36)`은 UUID 문자열입니다. 시각 컬럼은 모두 `timestamptz`이고 UTC로 저장합니다 |",
       "| NULL | N이면 NOT NULL입니다 |",
       "| 키 | PK 기본키, FK 외래키 제약, UK UNIQUE 제약 |",
       "| 기본값 | (앱)은 DB 기본값이 아니라 애플리케이션이 넣는 값입니다. DB에 직접 INSERT할 때는 직접 넣어야 합니다 |",
       "| 참조 | FK 제약은 핵심 계층(사용자, 프로젝트, 세션, 메시지, run, 워크플로우)에만 있습니다. 나머지는 값으로만 참조합니다 |",
       "| 삭제 | 프로젝트, 세션, 워크플로우는 지우지 않고 `deleted_at`에 시각을 적습니다(논리 삭제) |", "",
       "## 2. 테이블 목록", "",
       "| No | 테이블 | 한글명 | 영역 | 기본키 | 컬럼 수 | 행 증가 | 자동 정리 |",
       "| --- | --- | --- | --- | --- | --- | --- | --- |"]
for n in ALL:
    t = T[n]
    out.append(f"| {t['no']} | {n} | {t['ko']} | {t['area']} | {esc(t['pk'])} | {len(t['cols'])} | {esc(t['growth'])} | {esc(t['cleanup'])} |")
total = sum(len(T[n]["cols"]) for n in ALL)
out += ["", f"모두 {len(ALL)}개 테이블, {total}개 컬럼입니다. 1~19는 앱 테이블이고, 번호가 없는 7개는 LangGraph와 Alembic이 같은 데이터베이스에 만드는 테이블입니다.", "",
        "## 3. 테이블 정의", ""]
for i, n in enumerate(ALL, 1):
    t = T[n]
    out += [f"### 3.{i} {n} ({t['ko']})", "",
            "| 항목 | 내용 |", "| --- | --- |",
            f"| 영역 | {t['area']} |", f"| 기본키 | {esc(t['pk'])} |",
            f"| 설명 | {esc(about(n))} |", f"| 행 증가 | {esc(t['growth'])} |", f"| 자동 정리 | {esc(t['cleanup'])} |", "",
            "| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for j, c in enumerate(t["cols"], 1):
        out.append(f"| {j} | `{c['name']}` | {esc(c['ko'])} | {c['type']} | {c['null']} | {c['key']} | {esc(c['default'])} | {esc(c['desc'])} |")
    idx = [x for x in IDX if x["table"] == n]
    out += ["", "인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):", ""]
    if idx:
        out += ["| 인덱스 | 컬럼 | 받치는 조회 |", "| --- | --- | --- |"]
        out += [f"| {x['name']} | {esc(x['cols'])} | {esc(x['use'])} |" for x in idx]
    else:
        out.append("없음")
    out.append("")
open(D + "06-table-definition.md", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("tables", len(ALL), "columns", total, "indexes", len(IDX))
