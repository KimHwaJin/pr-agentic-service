import os, re, sys
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from schema import load

H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "handover") + os.sep
S = load(H + "03-db-physical.md")
T = S["tables"]
logical = open(H + "02-db-logical.md", encoding="utf-8").read()
DESC = {}
for m in re.finditer(r"\*\*([a-z_]+) \(([^)]+)\)\*\*\n(.+)", logical):
    DESC[m.group(1)] = m.group(3).replace("`", "").strip()

FONT = "맑은 고딕"
thin = Side(style="thin", color="999999")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD = PatternFill("solid", fgColor="DAE8FC")
LABEL = PatternFill("solid", fgColor="F2F2F2")


def cell(ws, r, c, v, bold=False, fill=None, wrap=True, align="left", size=10):
    x = ws.cell(row=r, column=c, value=v)
    x.font = Font(name=FONT, size=size, bold=bold)
    x.alignment = Alignment(wrap_text=wrap, vertical="center", horizontal=align)
    x.border = BORDER
    if fill:
        x.fill = fill
    return x


def header(ws, r, names):
    for i, n in enumerate(names, 1):
        cell(ws, r, i, n, bold=True, fill=HEAD, align="center")


def widths(ws, ws_):
    for i, w in enumerate(ws_, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def title(ws, text, span):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    c = ws.cell(row=1, column=1, value=text)
    c.font = Font(name=FONT, size=14, bold=True)
    c.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 28


wb = Workbook()
# ---- 표지
ws = wb.active
ws.title = "표지"
title(ws, "Table 정의서", 2)
info = [("시스템", "pr-agentic-service (사내 데이터 분석 Agent 서비스)"),
        ("문서", "Table 정의서 (RDB 테이블, Vector 저장소)"),
        ("기준", "마이그레이션 0008"),
        ("DBMS", "PostgreSQL, vector 확장(pgvector) 필요. 스키마 public"),
        ("데이터베이스", "dev: dtest / prd: dtestprd (DATABASE_URL의 마지막 부분)"),
        ("모델 정의", "src/dtest/core/models.py, src/dtest/gaia_bridge/models.py"),
        ("마이그레이션", "src/dtest/migrations/versions/ (Alembic, 0001~0008)"),
        ("관련 문서", "04 논리 ERD, 05 물리 ERD")]
for i, (k, v) in enumerate(info, 3):
    cell(ws, i, 1, k, bold=True, fill=LABEL)
    cell(ws, i, 2, v)
r = len(info) + 5
cell(ws, r, 1, "표기 규칙", bold=True, fill=HEAD)
cell(ws, r, 2, "", fill=HEAD)
rules = [("타입", "varchar(36)은 UUID 문자열입니다. 시각 컬럼은 모두 timestamptz이고 UTC로 저장합니다."),
         ("NULL", "N이면 NOT NULL입니다."),
         ("키", "PK 기본키, FK 외래키 제약, UK UNIQUE 제약."),
         ("기본값", "(앱)은 DB 기본값이 아니라 애플리케이션이 넣는 값입니다. DB에 직접 INSERT할 때는 직접 넣어야 합니다."),
         ("참조", "FK 제약은 핵심 계층(사용자, 프로젝트, 세션, 메시지, run, 워크플로우)에만 있습니다. 나머지는 값으로만 참조합니다."),
         ("삭제", "프로젝트, 세션, 워크플로우는 지우지 않고 deleted_at에 시각을 적습니다(논리 삭제).")]
for i, (k, v) in enumerate(rules, r + 1):
    cell(ws, i, 1, k, bold=True, fill=LABEL)
    cell(ws, i, 2, v)
widths(ws, [18, 100])

# ---- 개정 이력
ws = wb.create_sheet("개정 이력")
title(ws, "개정 이력", 4)
header(ws, 3, ["버전", "일자", "내용", "작성"])
for i, v in enumerate(["0.1", "2026-11-25", "초안 작성 (마이그레이션 0008 기준)", ""], 1):
    cell(ws, 4, i, v)
widths(ws, [10, 14, 60, 16])

# ---- 테이블 목록
ws = wb.create_sheet("테이블 목록")
title(ws, "테이블 목록", 8)
header(ws, 3, ["No", "테이블명", "한글명", "영역", "기본키", "컬럼 수", "행 증가", "자동 정리"])
for i, n in enumerate(S["order"]):
    t = T[n]
    r = 4 + i
    vals = [t["no"], n, t["ko"], t["area"], t["pk"], len(t["cols"]), t["growth"], t["cleanup"]]
    for c, v in enumerate(vals, 1):
        x = cell(ws, r, c, v, align="center" if c in (1, 6) else "left")
    ws.cell(row=r, column=2).hyperlink = f"#'{n}'!A1"
    ws.cell(row=r, column=2).font = Font(name=FONT, size=10, color="0563C1", underline="single")
r = 4 + len(S["order"]) + 1
cell(ws, r, 1, "앱 테이블 밖의 테이블 (같은 데이터베이스)", bold=True, fill=HEAD)
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
others = [("alembic_version", "Alembic 버전", "마이그레이션", "version_num", "1행", "Alembic이 관리"),
          ("checkpoints, checkpoint_writes, checkpoint_blobs, checkpoint_migrations", "LangGraph 체크포인트",
           "Agent 대화 상태", "LangGraph 정의", "턴의 그래프 단계마다", "쉬는 세션은 최신 1개만 남김"),
          ("store, store_migrations", "LangGraph store", "프로젝트 메모리 본문", "LangGraph 정의",
           "프로젝트 메모리 주제 수", "없음")]
for i, (n, ko, area, pk, g, cl) in enumerate(others, r + 1):
    for c, v in enumerate(["-", n, ko, area, pk, "", g, cl], 1):
        cell(ws, i, c, v, align="center" if c in (1, 6) else "left")
widths(ws, [6, 30, 24, 18, 26, 9, 34, 28])
ws.freeze_panes = "A4"

# ---- 테이블별 시트
for n in S["order"]:
    t = T[n]
    ws = wb.create_sheet(n)
    title(ws, f"{n} ({t['ko']})", 7)
    meta = [("테이블명", n), ("한글명", t["ko"]), ("영역", t["area"]), ("기본키", t["pk"]),
            ("설명", DESC.get(n, "")), ("행 증가", t["growth"]), ("자동 정리", t["cleanup"])]
    for i, (k, v) in enumerate(meta, 3):
        cell(ws, i, 1, k, bold=True, fill=LABEL)
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=7)
        cell(ws, i, 2, v)
        for c in range(3, 8):
            ws.cell(row=i, column=c).border = BORDER
        if k == "설명":
            ws.row_dimensions[i].height = max(18, 15 * (len(v) // 60 + 1))
    r0 = 3 + len(meta) + 1
    header(ws, r0, ["No", "컬럼명", "데이터 타입", "NULL", "키", "기본값", "설명"])
    for i, c in enumerate(t["cols"], 1):
        vals = [i, c["name"], c["type"], c["null"], c["key"], c["default"], c["desc"]]
        for j, v in enumerate(vals, 1):
            cell(ws, r0 + i, j, v, align="center" if j in (1, 4, 5) else "left")
    r = r0 + len(t["cols"]) + 2
    idx = [x for x in S["indexes"] if x["table"] == n]
    cell(ws, r, 1, "인덱스 (기본키와 UNIQUE 제약의 인덱스는 생략)", bold=True, fill=HEAD)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    if idx:
        for j, hname in enumerate(["No", "인덱스명", "컬럼", "", "", "", "받치는 조회"], 1):
            cell(ws, r + 1, j, hname, bold=True, fill=LABEL, align="center")
        ws.merge_cells(start_row=r + 1, start_column=3, end_row=r + 1, end_column=6)
        for i, x in enumerate(idx, 1):
            rr = r + 1 + i
            cell(ws, rr, 1, i, align="center"); cell(ws, rr, 2, x["name"]); cell(ws, rr, 3, x["cols"])
            for c in (4, 5, 6):
                cell(ws, rr, c, "")
            ws.merge_cells(start_row=rr, start_column=3, end_row=rr, end_column=6)
            cell(ws, rr, 7, x["use"])
    else:
        cell(ws, r + 1, 1, "없음")
        ws.merge_cells(start_row=r + 1, start_column=1, end_row=r + 1, end_column=7)
    back = ws.cell(row=1, column=8, value="← 테이블 목록")
    back.hyperlink = "#'테이블 목록'!A1"
    back.font = Font(name=FONT, size=10, color="0563C1", underline="single")
    widths(ws, [8, 26, 16, 7, 8, 18, 70, 14])

# ---- 인덱스
ws = wb.create_sheet("인덱스")
title(ws, "인덱스 목록", 5)
header(ws, 3, ["No", "테이블", "인덱스명", "컬럼", "받치는 조회"])
for i, x in enumerate(S["indexes"], 1):
    for j, v in enumerate([i, x["table"], x["name"], x["cols"], x["use"]], 1):
        cell(ws, 3 + i, j, v, align="center" if j == 1 else "left")
widths(ws, [6, 26, 56, 56, 46])
ws.freeze_panes = "A4"

# ---- Vector 저장소
ws = wb.create_sheet("Vector 저장소")
title(ws, "Vector 저장소", 2)
vec = [("저장 방식", "별도 Vector DB 제품을 쓰지 않습니다. PostgreSQL의 vector 확장(pgvector)으로 앱 데이터와 같은 데이터베이스에 저장합니다."),
       ("대상 테이블", "workflow_query_vectors (워크플로우 검색 벡터). 벡터를 담는 테이블은 이것 하나입니다."),
       ("용도", "사용자 요청과 비슷한 워크플로우 템플릿을 찾아 추천합니다. 프로젝트 메모리에는 벡터 색인이 없습니다."),
       ("벡터 컬럼", "embedding (vector). 컬럼에 차원을 고정하지 않고 인덱스와 검색식에서 vector(차원)으로 변환합니다."),
       ("색인 단위", "workflows.user_queries의 질문 한 개가 한 행입니다. 컬럼 정의는 workflow_query_vectors 시트를 참조합니다."),
       ("임베딩 모델", "EMBEDDING_PROVIDER(none, openai, mock), EMBEDDING_MODEL, EMBEDDING_BASE_URL로 정합니다. openai는 OpenAI 호환 임베딩 게이트웨이입니다."),
       ("차원", "EMBEDDING_DIMS (기본 1024). 임베딩 모델의 실제 출력 차원과 같아야 합니다. HNSW 인덱스는 2,000차원 이하만 됩니다."),
       ("모델 구분", "model 컬럼에 '임베딩모델:차원' 값을 넣습니다. 모델이나 차원이 바뀌면 다른 벡터 공간으로 보고 검색에서 섞지 않습니다."),
       ("인덱스", "ix_wqv_hnsw_{차원}. HNSW, 코사인 거리(vector_cosine_ops), 조건 active. Alembic이 아니라 기동 시 WorkflowService.ensure_index()가 CREATE INDEX IF NOT EXISTS로 만듭니다."),
       ("검색식", "코사인 유사도 = 1 - (embedding <=> 질의 벡터). active이고 model이 현재 설정과 같고 revision이 워크플로우의 현재 revision인 행만 봅니다. 워크플로우마다 가장 가까운 질문 하나를 씁니다."),
       ("검색 기준값", "WORKFLOW_SIMILARITY (기본 0.70) 이상이면 추천 후보. WORKFLOW_AUTO_RUN_SIMILARITY (기본 0.77) 이상이면 조건에 따라 승인 카드 없이 실행."),
       ("active 규칙", "삭제되지 않은 template 워크플로우의 현재 revision 벡터만 active입니다. 워크플로우를 고치면 이전 벡터의 active를 끄고 새 revision의 벡터를 만듭니다."),
       ("임베딩을 끄면", "EMBEDDING_PROVIDER가 none이면 인덱스를 만들지 않고, 벡터 검색 대신 모델이 템플릿을 읽고 고릅니다."),
       ("모델·차원 변경 시", "새 차원의 인덱스가 하나 더 생기고 예전 벡터는 검색에서 빠집니다. 기존 워크플로우를 다시 색인해야 하고 예전 인덱스는 직접 지웁니다."),
       ("필요 권한", "CREATE EXTENSION IF NOT EXISTS vector 실행 권한. 줄 수 없으면 DBA가 확장을 먼저 만들어 둡니다.")]
header(ws, 3, ["항목", "내용"])
for i, (k, v) in enumerate(vec, 4):
    cell(ws, i, 1, k, bold=True, fill=LABEL)
    cell(ws, i, 2, v)
    ws.row_dimensions[i].height = 32
widths(ws, [20, 120])

# ---- 부록
ws = wb.create_sheet("부록 (LangGraph, Redis)")
title(ws, "부록: 앱 테이블 밖의 데이터", 4)
header(ws, 3, ["데이터", "테이블", "키", "내용"])
lg = [("대화 상태", "checkpoints, checkpoint_writes, checkpoint_blobs", "thread_id = 세션 id",
       "Agent가 보는 메시지 이력, 분석 계획, 진행 위치. run이 멈췄다 이어 갈 때 읽음"),
      ("프로젝트 메모리", "store", "namespace에 프로젝트 id", "주제 목록과 주제별 본문")]
for i, row in enumerate(lg, 4):
    for j, v in enumerate(row, 1):
        cell(ws, i, j, v)
cell(ws, 6, 1, "LangGraph 라이브러리가 만들고 관리하는 테이블입니다. 구조를 직접 바꾸지 않습니다.")
ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=4)
header(ws, 8, ["Redis 용도", "키 또는 채널", "방식", "비고"])
rd = [("로그인 세션, 로그인 진행 상태", "{REDIS_NAMESPACE}:{종류}:{해시}", "문자열 키, 만료 시간 있음", "지워지면 다시 로그인"),
      ("세션 이벤트 전달", "{REDIS_NAMESPACE}:session:{세션 id}", "발행/구독", "저장되지 않음. 저장분은 run_events"),
      ("배치 리포트 이벤트 전달", "{REDIS_NAMESPACE}:batch-report:{작업 id}", "발행/구독", ""),
      ("run 깨우기", "{REDIS_NAMESPACE}:runs:wake", "발행/구독", "놓쳐도 5초 폴링이 처리"),
      ("executor 이벤트", "{EXECUTOR_EVENT_STREAM}.{tenant}", "스트림, 소비자 그룹",
       "executor가 쓰고 우리가 읽음. 같은 Redis, 같은 DB 번호여야 함")]
for i, row in enumerate(rd, 9):
    for j, v in enumerate(row, 1):
        cell(ws, i, j, v)
widths(ws, [30, 50, 28, 60])

wb.save(sys.argv[1])
print("sheets", len(wb.sheetnames), [n for n in S["order"] if n not in DESC])
