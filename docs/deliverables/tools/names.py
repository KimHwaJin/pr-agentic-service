"""Korean logical names and exact descriptions for every column, plus the
tables outside the app models (Alembic, LangGraph checkpoint and store)."""

# default Korean attribute name per column name
KO = {
    "id": "ID", "employee_id": "사번", "name": "이름", "english_name": "영문 이름",
    "department": "부서", "email": "메일", "role": "역할", "is_active": "활성 여부",
    "batches_disable_pending": "배치 끄기 대기", "created_at": "생성 시각",
    "updated_at": "수정 시각", "description": "설명", "system_prompt": "프로젝트 지시문",
    "code_level": "코드 생성 수준", "is_default": "기본 프로젝트 여부", "created_by": "생성자 ID",
    "deleted_at": "삭제 시각", "project_id": "프로젝트 ID", "user_id": "사용자 ID",
    "title": "제목", "title_source": "제목 출처", "active_run_id": "진행 중 실행 ID",
    "session_id": "세션 ID", "run_id": "실행 ID", "content": "본문", "attachments": "첨부",
    "status": "상태", "model": "모델", "input": "입력", "resume": "재개 값", "waiting": "대기 대상",
    "error": "오류", "cancel_requested": "취소 요청 여부", "lease_owner": "처리 인스턴스",
    "lease_expires_at": "처리 권한 만료 시각", "attempts": "시도 횟수", "finished_at": "종료 시각",
    "recovery_checked_at": "이벤트 복구 확인 시각", "type": "종류", "data": "내용",
    "key": "요청 키", "request_hash": "요청 해시", "resumed": "재개 요청 여부",
    "event_id": "이벤트 ID", "execution_id": "executor 실행 ID", "event_type": "이벤트 종류",
    "event_sequence": "이벤트 순번", "payload": "이벤트 내용", "received_at": "수신 시각",
    "tool_call_id": "도구 호출 ID", "path": "파일 경로", "sha256": "파일 해시",
    "size_bytes": "파일 크기", "kind": "종류", "skill": "skill 이름", "tool": "tool 이름",
    "call_key": "호출 키", "tool_version": "tool 버전", "purpose": "목적",
    "approved_by": "승인자 ID", "edited": "사용자 수정 여부", "operation_id": "executor 작업 ID",
    "step_id": "executor 단계 ID", "file_deleted_at": "파일 삭제 시각", "mime_type": "형식",
    "width": "가로 크기", "height": "세로 크기", "item_id": "메모리 주제 ID", "action": "변경 종류",
    "before": "변경 전 내용", "after": "변경 후 내용", "actor_type": "변경 주체 종류",
    "actor_id": "변경 주체 ID", "processed_until_at": "처리 완료 메시지 시각",
    "processed_until_id": "처리 완료 메시지 ID", "dirty": "처리 대기 여부",
    "last_activity_at": "마지막 대화 시각", "pending_turns": "미처리 턴 수",
    "last_error": "마지막 오류", "user_request": "원래 요청", "document": "워크플로우 문서",
    "user_queries": "질문 예시", "tags": "태그", "lifecycle": "단계", "author_id": "작성자 ID",
    "source_run_id": "출처 실행 ID", "source_workflow_id": "원본 워크플로우 ID",
    "revision": "수정 번호", "index_state": "색인 상태", "workflow_id": "워크플로우 ID",
    "query": "질문 문장", "embedding": "임베딩", "active": "검색 대상 여부",
    "idempotency_key": "중복 방지 키", "owner_id": "소유자 ID", "batch_id": "배치 ID",
    "batch_run_id": "배치 실행 ID", "execution": "실행 정보", "state": "상태",
    "failed_stage": "실패 단계", "markdown": "리포트 본문", "summary": "요약",
    "artifact_id": "Artifact ID", "collecting_since": "노트북 대기 시작 시각", "job_id": "작업 ID",
    "tenant": "tenant", "key_prefix": "키 앞부분", "key_sha256": "키 해시",
    "revoked_at": "폐기 시각", "last_used_at": "마지막 사용 시각",
    "gaia_session_id": "gaia 세션 ID",
}

# (table, column) -> (Korean name or None, description or None)
OVR = {
    ("users", "id"): ("사용자 ID", None),
    ("users", "name"): ("이름", "SSO에서 받은 이름"),
    ("users", "role"): ("권한", None),
    ("projects", "id"): ("프로젝트 ID", None),
    ("projects", "name"): ("프로젝트 이름", None),
    ("projects", "code_level"): ("기본 코드 생성 수준", None),
    ("projects", "created_by"): ("생성자 ID", "프로젝트를 만든 사용자. FK → users.id"),
    ("project_members", "role"): ("구성원 역할", None),
    ("sessions", "id"): ("세션 ID", None),
    ("messages", "id"): ("메시지 ID", None),
    ("messages", "role"): ("작성 주체", None),
    ("runs", "id"): ("실행 ID", None),
    ("runs", "status"): ("실행 상태", None),
    ("runs", "model"): ("모델 별칭", None),
    ("runs", "error"): ("실패 사유", None),
    ("runs", "attempts"): ("가져간 횟수", None),
    ("run_events", "id"): ("이벤트 번호", None),
    ("run_events", "type"): ("이벤트 종류", None),
    ("run_events", "data"): ("이벤트 내용", None),
    ("code_sources", "id"): ("코드 파일 ID", None),
    ("code_sources", "kind"): ("코드 종류", None),
    ("code_sources", "skill"): (None, "사용한 skill 이름. tool 코드가 아니면 비어 있음"),
    ("code_sources", "tool"): (None, "사용한 tool 이름. tool 코드가 아니면 비어 있음"),
    ("code_sources", "operation_id"): (None, "executor 쪽 작업(operation) id"),
    ("code_sources", "step_id"): (None, "executor 쪽 단계(step) id"),
    ("images", "id"): ("이미지 ID", None),
    ("images", "name"): ("파일 이름", None),
    ("images", "size_bytes"): (None, "파일 크기(바이트)"),
    ("images", "width"): (None, "이미지 가로 크기(픽셀)"),
    ("images", "height"): (None, "이미지 세로 크기(픽셀)"),
    ("images", "path"): ("저장 경로", None),
    ("memory_history", "id"): ("이력 번호", None),
    ("memory_history", "before"): (None, "변경 전 주제 내용. 새로 만든 경우 비어 있음"),
    ("memory_history", "after"): (None, "변경 후 주제 내용. 지운 경우 비어 있음"),
    ("memory_history", "session_id"): (None, "Agent가 바꾼 경우 그 대화. 사용자가 바꾸면 비어 있음"),
    ("memory_history", "run_id"): (None, "Agent가 바꾼 경우 그 run. 사용자가 바꾸면 비어 있음"),
    ("workflows", "id"): ("워크플로우 ID", None),
    ("workflows", "name"): ("워크플로우 이름", None),
    ("workflows", "session_id"): (None, "이 워크플로우를 만든 대화"),
    ("workflows", "run_id"): (None, "이 워크플로우를 만든 run"),
    ("workflows", "revision"): (None, "수정할 때마다 1씩 늘어나는 번호"),
    ("workflow_query_vectors", "id"): ("벡터 번호", None),
    ("workflow_query_vectors", "model"): ("임베딩 모델", None),
    ("workflow_query_vectors", "revision"): (None, "어느 수정 번호의 워크플로우에서 만든 벡터인지"),
    ("batch_report_jobs", "id"): ("리포트 작업 ID", None),
    ("batch_report_jobs", "state"): ("작업 상태", None),
    ("batch_report_jobs", "title"): ("리포트 제목", None),
    ("batch_report_jobs", "error"): ("실패 사유", None),
    ("batch_report_jobs", "attempts"): ("시도 횟수", None),
    ("batch_report_events", "id"): ("이벤트 번호", None),
    ("batch_report_events", "type"): ("이벤트 종류", None),
    ("batch_report_events", "data"): ("이벤트 내용", None),
    ("api_clients", "id"): ("클라이언트 ID", None),
    ("api_clients", "name"): ("클라이언트 이름", None),
    ("api_clients", "status"): ("키 상태", None),
    ("api_clients", "kind"): ("키 종류", None),
    ("api_clients", "description"): ("용도", None),
    ("api_clients", "created_by"): ("발급자 ID", None),
    ("gaia_sessions", "session_id"): ("우리 세션 ID", None),
    ("images", "user_id"): (None, "이미지를 보낸 사용자 (users.id 값, FK 제약 없음)"),
    ("images", "project_id"): (None, "이미지가 속한 프로젝트 (projects.id 값, FK 제약 없음)"),
    ("images", "session_id"): (None, "이미지를 보낸 대화 (sessions.id 값, FK 제약 없음)"),
    ("images", "run_id"): (None, "이미지를 처음 쓴 run"),
    ("code_sources", "user_id"): (None, "코드를 만든 사용자 (users.id 값, FK 제약 없음)"),
    ("code_sources", "project_id"): (None, "코드가 속한 프로젝트 (projects.id 값, FK 제약 없음)"),
    ("code_sources", "session_id"): (None, "이 코드를 만든 대화 (sessions.id 값)"),
    ("code_sources", "run_id"): (None, "이 코드를 만든 run (runs.id 값)"),
    ("code_sources", "execution_id"): (None, "이 코드를 실행한 executor 실행 id"),
    ("code_sources", "size_bytes"): (None, "파일 크기(바이트)"),
    ("memory_history", "project_id"): (None, "메모리가 속한 프로젝트 (projects.id 값, FK 제약 없음)"),
    ("memory_history", "actor_id"): (None, "바꾼 주체. 사용자면 users.id, Agent면 run id"),
    ("runs", "project_id"): (None, "대화의 프로젝트. 조회용 사본 (projects.id 값, FK 제약 없음)"),
    ("runs", "user_id"): (None, "요청한 사용자. 조회용 사본 (users.id 값, FK 제약 없음)"),
    ("run_events", "session_id"): (None, "이벤트가 속한 대화 (sessions.id 값)"),
    ("run_events", "run_id"): (None, "이벤트를 낸 run (runs.id 값)"),
}

TS_DESC = {"created_at": "행을 만든 시각", "updated_at": "행을 마지막으로 바꾼 시각"}


def ko(table, col):
    o = OVR.get((table, col))
    return (o and o[0]) or KO[col]


def desc(table, col, d):
    o = OVR.get((table, col))
    if o and o[1]:
        d2 = o[1]
        # keep the key notes of the source description
        for k in ("PK, FK → ", "FK → ", "UNIQUE"):
            if k in d and k not in d2:
                d2 += ". " + d[d.index(k):].split(".")[0]
        return d2
    if not d.strip() and col in TS_DESC:
        return TS_DESC[col]
    if d.strip() in ("PK",):
        return "기본키"
    return d


def col(name, typ, null, default, d, key="", fk=""):
    return dict(name=name, type=typ, null=null, default=default, desc=d, key=key, fk=fk)


# tables in the same database that the app models do not define
EXTRA_ORDER = ["alembic_version", "checkpoint_migrations", "checkpoints", "checkpoint_blobs",
               "checkpoint_writes", "store_migrations", "store"]
EXTRA = {
    "alembic_version": dict(
        ko="마이그레이션 버전", area="마이그레이션", pk="version_num", growth="1행",
        cleanup="Alembic 관리", owner="Alembic",
        about="지금 적용된 마이그레이션 번호 하나를 담습니다. 인스턴스가 기동할 때 이 값을 보고 남은 마이그레이션을 실행합니다.",
        cols=[col("version_num", "varchar(32)", "N", "", "적용된 마이그레이션 번호 (예: 0008)", "PK")],
        kos={"version_num": "마이그레이션 번호"}),
    "checkpoint_migrations": dict(
        ko="체크포인트 스키마 버전", area="LangGraph 체크포인트", pk="v", growth="적용한 마이그레이션 수",
        cleanup="LangGraph 관리", owner="LangGraph",
        about="LangGraph 체크포인트 테이블의 스키마 버전 기록입니다. 기동 때 checkpointer.setup()이 남은 단계를 적용합니다.",
        cols=[col("v", "integer", "N", "", "적용한 LangGraph 체크포인트 마이그레이션 번호", "PK")],
        kos={"v": "버전 번호"}),
    "checkpoints": dict(
        ko="대화 상태 체크포인트", area="LangGraph 체크포인트", pk="(thread_id, checkpoint_ns, checkpoint_id)",
        growth="턴의 그래프 단계마다", cleanup="쉬는 세션은 최신 1개만 남김", owner="LangGraph",
        about="Agent 그래프의 단계별 상태입니다. thread_id가 우리 sessions.id이고, run이 멈췄다 이어 갈 때 가장 최근 체크포인트를 읽습니다.",
        cols=[
            col("thread_id", "text", "N", "", "대화 스레드. 우리 sessions.id 값 (FK 제약 없음)", "PK", ""),
            col("checkpoint_ns", "text", "N", "''", "하위 그래프 구분. 최상위 그래프는 빈 문자열", "PK"),
            col("checkpoint_id", "text", "N", "", "체크포인트 id. 시간 순서로 정렬되는 값", "PK"),
            col("parent_checkpoint_id", "text", "Y", "", "바로 앞 체크포인트 id"),
            col("type", "text", "Y", "", "직렬화 형식 (현재 쓰지 않음)"),
            col("checkpoint", "jsonb", "N", "", "그래프 상태. 채널별 버전과 값이 작은 채널의 값"),
            col("metadata", "jsonb", "N", "'{}'", "단계 정보 (source, step, writes 등)"),
        ],
        kos={"thread_id": "스레드 ID", "checkpoint_ns": "체크포인트 이름공간", "checkpoint_id": "체크포인트 ID",
             "parent_checkpoint_id": "이전 체크포인트 ID", "type": "직렬화 형식", "checkpoint": "그래프 상태",
             "metadata": "메타데이터"}),
    "checkpoint_blobs": dict(
        ko="체크포인트 채널 값", area="LangGraph 체크포인트", pk="(thread_id, checkpoint_ns, channel, version)",
        growth="채널 값이 바뀔 때마다", cleanup="쉬는 세션은 최신 체크포인트가 쓰는 것만 남김", owner="LangGraph",
        about="큰 채널 값(메시지 이력 등)을 체크포인트와 따로 저장합니다. 같은 버전은 한 번만 저장하고 여러 체크포인트가 함께 참조합니다.",
        cols=[
            col("thread_id", "text", "N", "", "대화 스레드. 우리 sessions.id 값", "PK"),
            col("checkpoint_ns", "text", "N", "''", "하위 그래프 구분", "PK"),
            col("channel", "text", "N", "", "채널 이름 (messages 등)", "PK"),
            col("version", "text", "N", "", "채널 값의 버전", "PK"),
            col("type", "text", "N", "", "직렬화 형식 (msgpack 등). 값이 없으면 empty"),
            col("blob", "bytea", "Y", "", "직렬화한 채널 값"),
        ],
        kos={"thread_id": "스레드 ID", "checkpoint_ns": "체크포인트 이름공간", "channel": "채널",
             "version": "채널 버전", "type": "직렬화 형식", "blob": "채널 값"}),
    "checkpoint_writes": dict(
        ko="체크포인트 대기 쓰기", area="LangGraph 체크포인트",
        pk="(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)", growth="단계 안의 노드 실행마다",
        cleanup="쉬는 세션은 최신 체크포인트 것만 남김", owner="LangGraph",
        about="한 단계 안에서 노드가 낸 값 중 아직 다음 체크포인트에 합쳐지지 않은 것입니다. 단계 중간에 멈춰도 끝난 노드를 다시 돌리지 않게 해 줍니다.",
        cols=[
            col("thread_id", "text", "N", "", "대화 스레드. 우리 sessions.id 값", "PK"),
            col("checkpoint_ns", "text", "N", "''", "하위 그래프 구분", "PK"),
            col("checkpoint_id", "text", "N", "", "이 쓰기가 속한 체크포인트", "PK"),
            col("task_id", "text", "N", "", "값을 낸 노드 실행(task) id", "PK"),
            col("idx", "integer", "N", "", "task 안에서의 순번", "PK"),
            col("channel", "text", "N", "", "값을 쓸 채널"),
            col("type", "text", "Y", "", "직렬화 형식"),
            col("blob", "bytea", "N", "", "직렬화한 값"),
            col("task_path", "text", "N", "''", "task의 그래프 안 경로. 정렬에 사용"),
        ],
        kos={"thread_id": "스레드 ID", "checkpoint_ns": "체크포인트 이름공간", "checkpoint_id": "체크포인트 ID",
             "task_id": "task ID", "idx": "순번", "channel": "채널", "type": "직렬화 형식", "blob": "값",
             "task_path": "task 경로"}),
    "store_migrations": dict(
        ko="store 스키마 버전", area="LangGraph store", pk="v", growth="적용한 마이그레이션 수",
        cleanup="LangGraph 관리", owner="LangGraph",
        about="LangGraph store 테이블의 스키마 버전 기록입니다. 기동 때 store.setup()이 남은 단계를 적용합니다.",
        cols=[col("v", "integer", "N", "", "적용한 LangGraph store 마이그레이션 번호", "PK")],
        kos={"v": "버전 번호"}),
    "store": dict(
        ko="LangGraph store", area="LangGraph store", pk="(prefix, key)",
        growth="메모리 주제 수 + 도구 실행 수 + 배치 실행 수", cleanup="없음 (TTL 쓰지 않음)", owner="LangGraph",
        about="이름공간(prefix)별 키-값 저장소입니다. 이 서비스는 세 가지 이름공간을 씁니다. project_memory.{project_id}는 프로젝트 메모리 주제 본문, tool_effects.{run_id}는 도구가 executor에 한 번만 요청하도록 남긴 결과, batch_memory.{batch_id}는 배치 리포트가 다음 실행에 넘기는 요약입니다. 벡터 색인은 쓰지 않으므로 store_vectors 테이블은 없습니다.",
        cols=[
            col("prefix", "text", "N", "", "이름공간을 점(.)으로 이은 값. 예: project_memory.{project_id}", "PK"),
            col("key", "text", "N", "", "이름공간 안의 키. 예: 메모리 주제 id, {tool_call_id}:{도구 이름}", "PK"),
            col("value", "jsonb", "N", "", "저장한 값"),
            col("created_at", "timestamptz", "Y", "CURRENT_TIMESTAMP", "행을 만든 시각"),
            col("updated_at", "timestamptz", "Y", "CURRENT_TIMESTAMP", "행을 마지막으로 바꾼 시각"),
            col("expires_at", "timestamptz", "Y", "", "만료 시각. 이 서비스는 TTL을 쓰지 않아 비어 있음"),
            col("ttl_minutes", "integer", "Y", "", "TTL(분). 이 서비스는 쓰지 않음"),
        ],
        kos={"prefix": "이름공간", "key": "키", "value": "값", "created_at": "생성 시각",
             "updated_at": "수정 시각", "expires_at": "만료 시각", "ttl_minutes": "TTL(분)"}),
}

EXTRA_INDEXES = [
    dict(table="checkpoints", name="checkpoints_thread_id_idx", cols="thread_id", use="세션별 체크포인트 조회"),
    dict(table="checkpoint_blobs", name="checkpoint_blobs_thread_id_idx", cols="thread_id", use="세션별 채널 값 조회"),
    dict(table="checkpoint_writes", name="checkpoint_writes_thread_id_idx", cols="thread_id", use="세션별 대기 쓰기 조회"),
    dict(table="store", name="store_prefix_idx", cols="prefix text_pattern_ops", use="이름공간 앞부분으로 찾기"),
    dict(table="store", name="idx_store_expires_at", cols="expires_at (expires_at IS NOT NULL)", use="TTL 정리 (이 서비스는 쓰지 않음)"),
]


def full_schema(path):
    """App tables from the handover doc, Korean names filled in, plus EXTRA."""
    from schema import load
    S = load(path)
    for n in S["order"]:
        t = S["tables"][n]
        t["group"] = "app"
        for c in t["cols"]:
            c["ko"] = ko(n, c["name"])
            c["desc"] = desc(n, c["name"], c["desc"])
    for n in EXTRA_ORDER:
        e = EXTRA[n]
        cols = []
        for c in e["cols"]:
            c = dict(c, ko=e["kos"][c["name"]])
            cols.append(c)
        S["tables"][n] = dict(name=n, ko=e["ko"], area=e["area"], pk=e["pk"], growth=e["growth"],
                              cleanup=e["cleanup"], cols=cols, group="extra", about=e["about"],
                              owner=e["owner"], no="-")
    S["extra_order"] = EXTRA_ORDER
    S["extra_indexes"] = EXTRA_INDEXES
    return _rename(S)


def _rename(v):
    """Use the current service names in every text taken from the handover doc."""
    if isinstance(v, str):
        return v.replace("pr-batch", "batch").replace("pr-agentic-service", "gaia-api-service")
    if isinstance(v, dict):
        return {k: _rename(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_rename(x) for x in v]
    return v
