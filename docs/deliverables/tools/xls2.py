import sys
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "맑은 고딕"
thin = Side(style="thin", color="999999")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD = PatternFill("solid", fgColor="DAE8FC")
LABEL = PatternFill("solid", fgColor="F2F2F2")


def cell(ws, r, c, v, bold=False, fill=None, align="left"):
    x = ws.cell(row=r, column=c, value=v)
    x.font = Font(name=FONT, size=10, bold=bold)
    x.alignment = Alignment(wrap_text=True, vertical="center", horizontal=align)
    x.border = BORDER
    if fill:
        x.fill = fill


def sheet(wb, name, ttl, heads, rows, widths, first=False):
    ws = wb.active if first else wb.create_sheet(name)
    ws.title = name
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(heads))
    c = ws.cell(row=1, column=1, value=ttl)
    c.font = Font(name=FONT, size=14, bold=True)
    ws.row_dimensions[1].height = 28
    for i, h in enumerate(heads, 1):
        cell(ws, 3, i, h, bold=True, fill=HEAD, align="center")
    for r, row in enumerate(rows, 4):
        for i, v in enumerate(row, 1):
            cell(ws, r, i, v, fill=LABEL if (first and i == 1) else None, bold=(first and i == 1))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A4"
    return ws


A = "src/dtest/agent/"
wb = Workbook()
sheet(wb, "표지", "프로그램 목록 (Agent workflow)", ["항목", "내용"], [
    ("시스템", "pr-agentic-service (사내 데이터 분석 Agent 서비스)"),
    ("문서", "프로그램 목록 (Agent workflow)"),
    ("기준", "master 브랜치, 2026-11-27"),
    ("목록 단위", "Agent workflow: LLM을 호출해 한 가지 일을 끝내는 처리 단위. ID는 AW-01부터 부여"),
    ("구성 요소", "workflow가 쓰는 그래프, middleware, Agent 도구, 프롬프트, skill·tool 자산, worker 루프를 시트별로 정리"),
    ("관련 문서", "03 프로그램 명세서 (Agent Graph), 그림 diagrams/02-agent-workflow.drawio"),
    ("구현 기반", "LangGraph, LangChain create_agent. deepagents처럼 middleware로 행동을 조립하고 skill 체계를 사용"),
], [18, 110], first=True)

sheet(wb, "Agent workflow 목록", "Agent workflow 목록",
      ["ID", "workflow", "유형", "시작 조건", "입력", "출력", "실행 주체", "그래프·프롬프트", "주요 소스", "사용자 확인"], [
    ("AW-01", "대화", "Agent 그래프 (채팅 Agent Graph, 담당자 main)", "사용자가 세션에 메시지를 보냄",
     "사용자 메시지(이미지 포함 가능), 대화 이력(체크포인트), 프로젝트 지침, 프로젝트 메모리",
     "답변 메시지(message_final), 메모리 변경, 분석 넘기기",
     "RunScheduler (run 큐)", "G-01 / prompts/main.md",
     A + "graph.py, middleware/persona.py, tools/main.py, tools/common.py", "질문(question)"),
    ("AW-02", "데이터 분석", "Agent 그래프 (채팅 Agent Graph, 담당자 analyst)", "AW-01이 start_analysis를 호출",
     "분석 과제(task, context), skill·tool 카탈로그, 저장된 워크플로우, 코드 생성 레벨",
     "승인된 계획(Workflow 1.0), executor 실행 결과와 노트북, 리포트, 워크플로우 후보, 요약",
     "RunScheduler (run 큐)", "G-01 / prompts/analyst.md, analyst_continue.md",
     A + "tools/analysis.py, plan_format.py, codegen.py", "계획 승인(plan_approval), 코드 승인(code_approval), 워크플로우 저장(workflow_save), 질문"),
    ("AW-03", "분석 리포트 작성", "Agent 그래프 (리포트 Agent)", "AW-02가 write_report를 호출",
     "끝난 실행의 단계별 코드, 관측값, 출력(근거), 리포트 초점(focus)",
     "리포트 Markdown (executor Artifact로 저장)", "AW-02의 도구 안에서 실행",
     "G-02 / prompts/reporter.md", A + "report_agent.py, reporter.py, tools/batch.py", "없음"),
    ("AW-04", "배치 리포트 작성", "Agent 그래프 (리포트 Agent)", "pr-batch가 시작한 배치 실행이 성공(executor 이벤트)",
     "배치 실행의 단계별 근거, 같은 배치의 이전 실행 요약(최대 5건)",
     "리포트 Markdown, 다음 실행이 읽을 요약 (batch_report_jobs, executor Artifact)",
     "BatchReportWorker (batch_report_jobs 큐)", "G-02 / prompts/batch_analyst.md",
     A + "batch.py, report_agent.py, src/dtest/worker/batch_reports.py", "없음"),
    ("AW-05", "프로젝트 메모리 추출", "LLM 단일 호출 + 코드 검증", "프로젝트의 대화가 180초 조용하거나 5턴 누적",
     "마지막 처리 위치 뒤의 user·assistant 메시지(최대 8,000 토큰), 메모리 주제 목록",
     "프로젝트 메모리 줄 편집(store), memory_history, memory_updated 이벤트",
     "MemoryWorker", "그래프 없음 / prompts/memory_worker.md",
     "src/dtest/worker/memory.py, src/dtest/core/memory/service.py", "없음 (화면에서 되돌리기 가능)"),
    ("AW-06", "세션 제목 생성", "LLM 단일 호출", "세션의 첫 답변이 끝남",
     "첫 질문(1,000자까지), 첫 답변(1,500자까지)", "세션 제목(25자 이내), session_titled 이벤트",
     "RunScheduler (턴 종료 처리)", "그래프 없음 / titles.py 안의 시스템 문구", A + "titles.py", "없음"),
    ("AW-07", "대화 요약", "middleware (LLM 호출)", "대화 이력이 3만 토큰(어림)을 넘음",
     "요약 대상 메시지 전체", "요약 메시지(최대 6,000자)로 앞부분 교체, context_summarized 이벤트",
     "채팅 Agent Graph의 before_model 훅", "G-01 / prompts/summary.md", A + "middleware/summarization.py", "없음"),
    ("AW-08", "워크플로우 추천 검색", "임베딩 검색 또는 LLM 단일 호출", "AW-02가 search_workflows를 호출",
     "사용자 요청 문장, 승격된 템플릿(template)의 질문 예시",
     "추천 워크플로우와 유사도. 0.70 이상이면 후보, 0.77 이상이면 조건에 따라 바로 실행",
     "AW-02의 도구 안에서 실행", "그래프 없음 / 임베딩이 꺼져 있으면 pick.py의 시스템 문구로 모델이 고름",
     "src/dtest/core/workflows/service.py, pick.py, src/dtest/core/embeddings.py", "없음"),
    ("AW-09", "gaia 연동 workflow (dtest.analyst)", "LangGraph StateGraph (노드 1개)", "gaia 채팅 화면에서 메시지를 보냄",
     "query, user_id(사번), gaia session_id", "answer, urls(리포트·노트북 링크). 내부에서 AW-01 run을 만들어 실행",
     "gaia 플랫폼이 graph를 호출", "G-03 / 프롬프트 없음",
     "src/workflows/dtest/analyst.py, src/dtest/gaia_bridge/", "gaia HITL 미사용. 계획은 첫 후보 자동 승인, 코드는 승인, 메모리·워크플로우 저장 제안은 거절"),
], [8, 22, 26, 30, 40, 40, 24, 30, 44, 36])

sheet(wb, "그래프 목록", "그래프 목록", ["ID", "그래프", "만드는 곳", "구성", "상태(state)", "체크포인트", "쓰는 workflow"], [
    ("G-01", "채팅 Agent Graph", A + "graph.py AgentGraphs.get()",
     "LangChain create_agent. model 노드와 tools 노드의 반복. 모델 이름마다 하나씩 만들어 캐시. middleware 8개, 도구 16개",
     "AnalysisState: messages, active_agent, plan, execution, nudges, notice, recommend",
     "있음 (PostgreSQL, thread_id = 세션 id). store도 사용", "AW-01, AW-02, AW-07"),
    ("G-02", "리포트 Agent Graph", A + "report_agent.py ReportAgent",
     "LangChain create_agent. 도구 read_step, submit_report. middleware: 모델 호출 한도, JSON 인자 복구, 도구 실패 한도, 도구 오류 전달",
     "ReportState: messages, report", "없음 (재시도하면 처음부터)", "AW-03, AW-04"),
    ("G-03", "gaia 연동 graph", "src/dtest/gaia_bridge/graph.py", "LangGraph StateGraph. START → answer → END",
     "BridgeState: query, user_id, session_id, answer, docs, urls, usage", "gaia 쪽 관리", "AW-09"),
], [8, 22, 34, 60, 46, 34, 22])

sheet(wb, "middleware 목록", "채팅 Agent Graph의 middleware (붙는 순서)", ["순서", "middleware", "파일", "훅", "역할", "관련 설정"], [
    (1, "PersonaMiddleware", A + "middleware/persona.py", "before_agent, wrap_model_call, after_model, after_agent",
     "담당자 전환, 담당자별 프롬프트와 도구 고르기, 프로젝트 지침·메모리·이미지 주입, 분석 담당이 도구 없이 글만 내고 멈추는 것 방지(최대 2번 다시 시킴)",
     "DEFAULT_CODE_LEVEL, PLAN_CANDIDATES, PLAN_RECOMMEND_MODE"),
    (2, "JsonArgumentsMiddleware", A + "middleware/json_arguments.py", "wrap_tool_call", "문자열로 온 JSON 인자를 검증 전에 복구", ""),
    (3, "ToolCallDedupMiddleware", A + "middleware/tool_call_dedup.py", "wrap_model_call",
     "한 응답 안의 같은 도구 호출은 한 번만 실행. 여러 propose_plans 호출은 하나로 합침", ""),
    (4, "ToolFailureLimitMiddleware", A + "middleware/tool_failures.py", "wrap_tool_call",
     "한 턴에서 같은 도구가 같은 오류로 연속 실패하면 더 실행하지 않고 사용자에게 설명하게 함",
     "AGENT_TOOL_FAILURE_LIMIT (3), AGENT_TOOL_FAILURE_ANY_LIMIT (5)"),
    (5, "ToolErrorMiddleware", "LangChain 제공. 오류 문구는 " + A + "tool_errors.py", "wrap_tool_call",
     "도구 예외를 모델에게 메시지로 돌려줌", ""),
    (6, "TurnModelCallLimitMiddleware", A + "middleware/turn_limit.py", "before_agent, before_model, after_model",
     "한 턴의 모델 호출 수를 제한. 멈췄다 이어져도 누적해서 셈", "AGENT_MODEL_CALL_LIMIT (40)"),
    (7, "ToolResultCompactionMiddleware (끝난 분석 정리)", A + "middleware/compaction.py, compaction_rules.py", "wrap_tool_call",
     "분석이 끝나면(finish_analysis) 그 분석의 긴 도구 결과를 규칙대로 줄임", "AGENT_COMPACT_FINISHED_ANALYSIS (true)"),
    (8, "ReportingSummarizationMiddleware", A + "middleware/summarization.py", "before_model",
     "대화가 길어지면 앞부분을 요약하고 진행 이벤트를 보냄 (AW-07)", "AGENT_SUMMARY_TRIGGER_TOKENS (30000), AGENT_SUMMARY_MAX_CHARS (6000)"),
], [7, 32, 44, 34, 70, 44])

T = A + "tools/"
sheet(wb, "Agent 도구 목록", "Agent 도구 목록", ["No", "도구", "쓰는 쪽", "파일", "하는 일", "멈춤(interrupt)"], [
    (1, "ask_user", "main, analyst", T + "common.py", "모호하거나 빠진 정보를 사용자에게 물음", "question"),
    (2, "read_knowledge", "main, analyst", T + "main.py", "도메인 지식 skill의 본문을 읽음", ""),
    (3, "save_memory", "main", T + "main.py", "사용자가 요청하면 프로젝트 메모리 주제에 한 줄을 더하거나 바꿈", ""),
    (4, "delete_memory", "main", T + "main.py", "사용자가 요청하면 프로젝트 메모리의 한 줄을 지움", ""),
    (5, "start_analysis", "main", T + "main.py", "분석 담당에게 대화를 넘김 (active_agent = analyst)", ""),
    (6, "read_skill", "analyst", T + "analysis.py", "분석 skill을 읽음: 용도, 포함된 tool, tool별 실행 조건(항상, 조건부)", ""),
    (7, "read_tool", "analyst", T + "analysis.py", "tool의 시그니처, 출력, docstring을 읽음 (여러 개 한 번에)", ""),
    (8, "search_tools", "analyst", T + "analysis.py", "이름이나 docstring에 검색어가 있는 tool을 찾음", ""),
    (9, "search_workflows", "analyst", T + "analysis.py", "사용자 요청과 비슷한 워크플로우 템플릿을 검색 (AW-08)", ""),
    (10, "propose_plans", "analyst", T + "analysis.py", "계획 후보를 Workflow 1.0 문서로 바꿔 검증하고 사용자에게 보여 승인을 기다림. 조건이 맞는 템플릿은 카드 없이 승인", "plan_approval"),
    (11, "revise_call", "analyst", T + "analysis.py", "승인된 계획에서 실패했거나 아직 안 한 호출의 인자를 고침", ""),
    (12, "run_plan", "analyst", T + "analysis.py", "승인된 계획의 다음 호출들을 조건부 호출 앞까지 묶어 executor에 제출하고 결과를 기다림", "executor_wait"),
    (13, "run_custom_code", "analyst (코드 레벨 2 이상)", T + "analysis.py", "Agent가 쓴 코드를 승인받아 executor에서 실행", "code_approval, executor_wait"),
    (14, "write_report", "analyst", T + "analysis.py", "노트북을 확정하고 리포트 Agent로 리포트를 써서 executor에 저장 (AW-03)", ""),
    (15, "save_workflow", "analyst", T + "analysis.py", "승인된 계획을 워크플로우 후보로 저장하자고 제안", "workflow_save"),
    (16, "finish_analysis", "analyst", T + "analysis.py", "요약과 함께 대화 담당에게 돌려줌 (active_agent = main)", ""),
    (17, "read_step", "리포트 Agent", T + "batch.py", "근거에서 줄였거나 뺀 단계를 전체로 읽음 (한 번에 6개까지)", ""),
    (18, "submit_report", "리포트 Agent (배치)", T + "batch.py", "완성한 리포트(title, markdown, summary)를 제출", ""),
], [6, 22, 26, 40, 80, 26])

P = A + "prompts/"
sheet(wb, "프롬프트 목록", "프롬프트 목록", ["No", "파일", "쓰는 곳", "용도"], [
    (1, P + "main.md", "AW-01", "대화 담당의 시스템 프롬프트"),
    (2, P + "main_fallback.md", "AW-01", "분석 담당이 멈췄을 때 대화 담당이 넘겨받아 상황을 설명하는 지시"),
    (3, P + "analyst.md", "AW-02", "분석 담당의 시스템 프롬프트 (skill 목록, 코드 레벨, 계획 상태, 후보 수가 채워짐)"),
    (4, P + "analyst_continue.md", "AW-02", "분석 담당이 도구 없이 글만 냈을 때 다시 시키는 알림"),
    (5, P + "reporter.md", "AW-03", "분석 리포트 작성 지시"),
    (6, P + "batch_analyst.md", "AW-04", "배치 리포트 작성 지시"),
    (7, P + "memory_worker.md", "AW-05", "대화에서 프로젝트 메모리 줄 편집을 뽑는 지시"),
    (8, P + "summary.md", "AW-07", "대화 요약의 틀"),
], [6, 50, 12, 80])

sheet(wb, "skill·tool 자산", "skill, tool, knowledge 자산", ["종류", "위치", "형식", "쓰는 곳", "기본 제공 내용"], [
    ("skill", "src/dtest/assets/skills/<분류>/<이름>.md", "Markdown", "분석 담당이 읽고 계획을 세움",
     "data_io/data_load, eda/eda_analysis, preprocessing/dataset_preparation (3개)"),
    ("tool", "src/dtest/assets/tools/<분류>/<이름>.py", "Python (파일 이름과 같은 함수 하나)", "executor에서 실행되는 분석 함수",
     "data_io: extract_data, transform_nce, transform_wt / eda: boxplot_eda, compute_statistics, correlation_analysis, histogram_eda / preprocessing: merge_data, sample_data (9개)"),
    ("knowledge", "src/dtest/assets/knowledge/<이름>.md", "Markdown", "두 담당자가 읽는 도메인 지식", "semiconductor_test_data (1개)"),
    ("확장 카탈로그", "src/dtest/catalogs/analysis_test/", "위와 같은 구조", "CATALOG_EXTENSIONS로 붙이는 테스트용 분석 카탈로그",
     "skill 14개, tool 48개, knowledge 5개"),
    ("참고", "", "", "", "위치는 SKILLS_ROOT, TOOLS_ROOT, KNOWLEDGE_ROOT로 바꿀 수 있음. 파일이 바뀌면 다음 run부터 반영. 기본 자산은 예시 수준이고 실제 분석 tool은 별도 담당이 관리"),
], [14, 46, 30, 40, 80])

W = "src/dtest/worker/"
sheet(wb, "worker 루프", "백그라운드 worker 루프", ["No", "루프 이름", "클래스 (파일)", "역할", "관련 workflow"], [
    (1, "run-scheduler", "RunScheduler (" + W + "scheduler.py)", "run을 가져와 Agent 실행. lease 갱신, interrupt 처리, 완료 기록, 취소, 세션 제목", "AW-01, AW-02, AW-06"),
    (2, "executor-events", "ExecutorEventConsumer (" + W + "executor_events.py)", "executor 이벤트 스트림 소비, inbox 저장, 기다리는 run 깨우기, 배치 완료 시 리포트 작업 등록", "AW-02, AW-04"),
    (3, "missed-executor-events", "MissedEventRecovery (" + W + "executor_events.py)", "스트림으로 못 받은 이벤트를 executor에 직접 물어 복구", "AW-02"),
    (4, "batch-reports-N", "BatchReportWorker (" + W + "batch_reports.py)", "배치 리포트 작성. BATCH_REPORT_CONCURRENCY만큼 띄움", "AW-04"),
    (5, "batch-report-recovery", "BatchReportRecovery (" + W + "batch_reports.py)", "리포트 작업이 빠진 배치 실행을 찾아 등록", "AW-04"),
    (6, "retention", "Retention (" + W + "maintenance.py)", "보존 기간 지난 이벤트, 이미지, 코드 파일, 체크포인트 정리", ""),
    (7, "batch-disable-retry", "BatchDisableRetry (" + W + "user_deactivation.py)", "비활성 사용자와 폐기된 tenant의 배치 끄기 재시도", ""),
    (8, "executor-cancel-retry", "ExecutionCancelRetry (src/dtest/core/executor/cancels.py)", "executor 실행 취소 재시도", ""),
    (9, "memory-worker", "MemoryWorker (" + W + "memory.py)", "대화가 잠잠해지면 프로젝트 메모리 정리", "AW-05"),
], [6, 26, 60, 70, 22])
wb.save(sys.argv[1])
