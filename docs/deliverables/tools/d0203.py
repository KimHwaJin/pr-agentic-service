import sys
from dg import Page, write

OUT = sys.argv[1]


def at(p, n, pt):
    """(side, fraction) of absolute point pt on node n's border."""
    n = p.nodes[n]
    x, y = pt
    if abs(x - n["x"]) < 1:
        return ("l", (y - n["y"]) / n["h"])
    if abs(x - n["x"] - n["w"]) < 1:
        return ("r", (y - n["y"]) / n["h"])
    if abs(y - n["y"]) < 1:
        return ("t", (x - n["x"]) / n["w"])
    assert abs(y - n["y"] - n["h"]) < 1, (n["id"], pt)
    return ("b", (x - n["x"]) / n["w"])


def path(p, a, b, pts, label="", **kw):
    p.edge(a, b, label, ex=at(p, a, pts[0]), en=at(p, b, pts[-1]), via=pts[1:-1], **kw)


# =============== 02: workflow 전체 지도
m = Page("Agent workflow 지도", 1480, 800, "Agent workflow 전체 지도")
for x, t in ((40, "계기"), (300, "실행 주체"), (560, "Agent workflow")):
    m.text("h%d" % x, t, x, 56, 200, 20, size=12, bold=True)
m.node("t_gaia", "gaia 채팅 메시지", 40, 90, 200, 50, "caller")
m.node("t_chat", "채팅 메시지", 40, 215, 200, 50, "caller", sub="POST /sessions/{id}/runs")
m.node("t_title", "턴의 첫 답변 완료", 40, 450, 200, 50, "caller")
m.node("t_mem", "대화가 잠잠해짐", 40, 550, 200, 50, "caller", sub="180초 조용 또는 5턴 누적")
m.node("t_batch", "배치 실행 성공 이벤트", 40, 650, 200, 50, "caller", sub="executor, trigger BATCH")

m.node("aw09", "AW-09 gaia 연동 workflow", 300, 90, 200, 50, "ours", sub="gaia_bridge (dtest.analyst)")
m.node("sched", "RunScheduler", 300, 215, 200, 50, "ours", sub="run 큐에서 가져가 실행")
m.node("sched2", "RunScheduler", 300, 450, 200, 50, "ours", sub="턴 종료 처리")
m.node("memw", "MemoryWorker", 300, 550, 200, 50, "ours")
m.node("brw", "BatchReportWorker", 300, 650, 200, 50, "ours")

m.group("chat", "채팅 Agent Graph (create_agent 그래프 1개, 담당자는 상태값)", 540, 170, 560, 230)
m.node("aw01", "AW-01 대화", 560, 215, 220, 50, "state", sub="담당자 main")
m.node("aw02", "AW-02 데이터 분석", 860, 215, 220, 50, "state", sub="담당자 analyst")
m.node("aw07", "AW-07 대화 요약", 560, 320, 220, 50, "state", sub="middleware, 3만 토큰 넘으면")
m.node("aw08", "AW-08 워크플로우 추천 검색", 860, 320, 220, 50, "state", sub="임베딩 검색 또는 모델 선택")
m.node("aw03", "AW-03 분석 리포트 작성", 1180, 215, 240, 50, "state", sub="리포트 Agent (reporter)")
m.node("aw06", "AW-06 세션 제목 생성", 560, 450, 220, 50, "state", sub="LLM 1회 호출")
m.node("aw05", "AW-05 프로젝트 메모리 추출", 560, 550, 220, 50, "state", sub="LLM 1회 호출 + 코드 검증")
m.node("aw04", "AW-04 배치 리포트 작성", 560, 650, 220, 50, "state", sub="리포트 Agent (batch_analyst)")

m.edge("t_gaia", "aw09", ex=("r", .5), en=("l", .5))
m.edge("aw09", "sched", "run 생성", ex=("b", .5), en=("t", .5))
m.edge("t_chat", "sched", ex=("r", .5), en=("l", .5))
m.edge("sched", "aw01", "run_turn", ex=("r", .5), en=("l", .5))
m.edge("aw01", "aw02", "start_analysis", ex=("r", .3), en=("l", .3))
m.edge("aw02", "aw01", "finish_analysis", ex=("l", .75), en=("r", .75))
m.edge("aw02", "aw03", "write_report", ex=("r", .5), en=("l", .5))
m.edge("aw02", "aw08", "search_workflows", ex=("b", .5), en=("t", .5))
m.edge("aw01", "aw07", "", ex=("b", .5), en=("t", .5), dashed=True)
m.edge("t_title", "sched2", ex=("r", .5), en=("l", .5))
m.edge("sched2", "aw06", ex=("r", .5), en=("l", .5))
m.edge("t_mem", "memw", ex=("r", .5), en=("l", .5))
m.edge("memw", "aw05", ex=("r", .5), en=("l", .5))
m.edge("t_batch", "brw", ex=("r", .5), en=("l", .5))
m.edge("brw", "aw04", ex=("r", .5), en=("l", .5))
m.text("n1", "보라색 상자가 프로그램 목록의 workflow입니다. AW-03과 AW-04는 같은 리포트 Agent 그래프를 프롬프트만 바꿔 씁니다.\n"
       "사용자 확인(계획·코드 승인, 질문)과 executor 대기는 채팅 Agent Graph 안에서 interrupt로 멈췄다가 이어 갑니다.",
       560, 730, 880, 40)
write([m], "02-agent-workflow", OUT)

# =============== 03 page 1: Agent Graph 한 바퀴
g = Page("Agent Graph", 1400, 1010, "채팅 Agent Graph 한 바퀴 (middleware 훅 순서)")
CX, WD = 470, 460
g.node("start", "턴 시작", CX, 70, WD, 44, "caller", shape="round",
       sub="사용자 메시지 추가, 또는 멈춘 지점에서 재개 (Command resume)")
g.node("ba", "before_agent", CX, 150, WD, 60, "ours",
       sub="Persona: 프로젝트 메모리 불러오기, nudges·notice 초기화\nTurnModelCallLimit: 새 턴이면 호출 수 초기화")
g.node("bm", "before_model", CX, 250, WD, 60, "ours",
       sub="TurnModelCallLimit: 한 턴 모델 호출 40회 넘었는지 확인\nSummarization: 3만 토큰(어림) 넘으면 앞부분 요약")
g.node("wm", "wrap_model_call", CX, 350, WD, 110, "ours",
       sub="Persona: 담당자(active_agent)의 프롬프트 렌더\n+ 프로젝트 지침 + 프로젝트 메모리\n담당자의 도구만 남김, 다른 담당자가 읽은 자료는 가림\n이미지 참조를 실제 이미지로 바꿈\nToolCallDedup: 응답 안의 중복 도구 호출 정리")
g.node("model", "model 노드", CX, 500, WD, 44, "state", sub="LLM 게이트웨이 호출 (토큰은 50ms 묶음으로 SSE 전달)")
g.node("am", "after_model", CX, 584, WD, 44, "ours",
       sub="Persona: 분석 담당이 도구 없이 글만 냈는지 확인")
g.node("q", "도구 호출이\n있는가", CX + 150, 668, 160, 90, "note", shape="diamond", size=12)
g.node("aa", "after_agent", CX, 810, WD, 44, "ours", sub="Persona: active_agent를 main으로 되돌림")
g.node("end", "턴 끝", CX, 900, WD, 44, "caller", shape="round", sub="마지막 AI 메시지가 답 (message_final)")
g.node("tools", "tools 노드", 1010, 500, 340, 130, "state",
       sub="JsonArguments: 문자열로 온 JSON 인자 복구\nToolFailureLimit: 같은 오류 연속 3회면 실행 중단\n도구 실행\nToolError: 예외를 오류 메시지로 모델에 전달\nCompaction: finish_analysis 때 끝난 분석 결과 정리")
g.node("pause", "그래프 멈춤", 1010, 700, 340, 60, "warn", shape="round",
       sub="interrupt: 승인 요청, 질문, executor 대기\n상태를 체크포인트에 저장, run은 waiting_*")
g.node("nudge", "분석 담당이 글만 냄", 60, 668, 330, 90, "note",
       sub="버리고 다시 시킴 (최대 2번)\n그래도 멈추면 대화 담당이 넘겨받아\n상황을 설명")

for a, b in (("start", "ba"), ("ba", "bm"), ("bm", "wm"), ("wm", "model"), ("model", "am")):
    g.edge(a, b)
path(g, "am", "q", [(CX + 230, 628), (CX + 230, 668)])
path(g, "q", "aa", [(CX + 230, 758), (CX + 230, 810)], "없음 (대화 담당의 답)")
g.edge("aa", "end")
path(g, "q", "tools", [(CX + 310, 713), (970, 713), (970, 600), (1010, 600)], "있음", t=0.25)
path(g, "tools", "bm", [(1180, 500), (1180, 280), (CX + WD, 280)], "도구 결과를 가지고 다시 모델로", t=0.6)
path(g, "tools", "pause", [(1180, 630), (1180, 700)], "interrupt", dashed=True)
path(g, "q", "nudge", [(CX + 150, 713), (390, 713)], "분석 담당이 글만 냄", t=0.5)
path(g, "nudge", "bm", [(225, 668), (225, 280), (CX, 280)], "다시 모델로", t=0.8)
path(g, "pause", "start", [(1350, 730), (1375, 730), (1375, 92), (CX + WD, 92)],
     "답이나 결과가 오면 재개", dashed=True, t=0.85)
g.text("gn", "파랑: middleware 훅 / 보라: 그래프 노드 / 담당자(main, analyst)는 별도 그래프가 아니라 상태값 active_agent입니다.",
       60, 970, 1200, 20)

# =============== 03 page 2: 담당자 전환
s = Page("담당자 전환", 1100, 420, "담당자(persona) 전환")
s.node("st", "턴 시작", 60, 180, 110, 44, "caller", shape="round")
s.node("main", "대화 담당 main", 280, 150, 260, 104, "state",
       sub="prompts/main.md\nask_user, read_knowledge,\nsave_memory, delete_memory,\nstart_analysis")
s.node("an", "분석 담당 analyst", 760, 120, 290, 164, "state",
       sub="prompts/analyst.md\nask_user, read_knowledge, read_skill,\nread_tool, search_tools, search_workflows,\npropose_plans, revise_call, run_plan,\nrun_custom_code, write_report,\nsave_workflow, finish_analysis")
s.node("en", "턴 끝", 60, 320, 110, 44, "caller", shape="round")
s.edge("st", "main", ex=("r", .5), en=("l", .5))
path(s, "main", "an", [(540, 175), (760, 175)], "start_analysis(task, context)")
path(s, "an", "main", [(760, 232), (540, 232)], "finish_analysis(summary)")
path(s, "an", "main", [(905, 284), (905, 350), (410, 350), (410, 254)],
     "글만 내고 멈추면(2번 재시도 뒤) 대화 담당이 넘겨받음", dashed=True)
path(s, "main", "en", [(280, 240), (220, 240), (220, 342), (170, 342)], "도구 없이 답하면 끝", t=0.35)
s.text("sn", "두 담당자는 같은 메시지 기록을 봅니다. 상대가 읽은 분석 skill, tool 설명, 워크플로우 검색 결과는 가려집니다.",
       60, 385, 1000, 20)

# =============== 03 page 3: 분석 한 턴 시퀀스
q = Page("분석 한 턴", 1500, 1020, "분석 한 턴의 흐름 (시퀀스)")
LX = {"U": 110, "A": 330, "S": 560, "G": 860, "L": 1160, "E": 1390}
NAME = {"U": "사용자 (화면)", "A": "api_service", "S": "RunScheduler", "G": "Agent Graph",
        "L": "LLM", "E": "executor"}
TOP, STEP = 120, 35
MSG = [("U", "A", "메시지 전송 (POST /runs)", 0), ("A", "S", "run 등록 (queued)", 0),
       ("S", "G", "run_turn", 0), ("G", "L", "대화 담당(main) 판단", 0),
       ("L", "G", "start_analysis", 1), ("G", "L", "analyst: read_skill, search_workflows", 0),
       ("L", "G", "propose_plans (계획 후보)", 1),
       ("G", "S", "interrupt: plan_approval", 1), ("S", "U", "계획 카드 (run: waiting_input)", 1),
       ("U", "A", "승인 (resume)", 0), ("A", "S", "run (queued)", 0),
       ("S", "G", "Command(resume)", 0), ("L", "G", "run_plan", 1),
       ("G", "E", "코드 파일 쓰기, 실행 제출", 0),
       ("G", "S", "interrupt: executor_wait", 1),
       ("E", "S", "완료 이벤트 (Redis 스트림, run: queued)", 1),
       ("S", "G", "Command(resume=이벤트)", 0), ("G", "L", "관측값 전달, 조건부 단계 판단", 0),
       ("L", "G", "write_report", 1), ("G", "E", "노트북 확정, 리포트 Artifact 저장", 0),
       ("L", "G", "finish_analysis(summary)", 1), ("G", "L", "main이 요약을 받아 답변 작성", 0),
       ("G", "S", "턴 끝", 1), ("S", "U", "message_final (run: succeeded)", 1)]
H = TOP + STEP * (len(MSG) + 1)
for k, x in LX.items():
    q.node("h" + k, NAME[k], x - 75, 64, 150, 36, "related" if k == "E" else ("infra" if k == "L" else ("caller" if k == "U" else "ours")), size=12)
    q.node("l" + k, "", x - 3, 100, 6, H - 100, "infra")
for i, (a, b, lab, dash) in enumerate(MSG):
    y = TOP + STEP * (i + 1)
    xa, xb = LX[a], LX[b]
    sa = (xa + 3, y) if xb > xa else (xa - 3, y)
    sb = (xb - 3, y) if xb > xa else (xb + 3, y)
    path(q, "l" + a, "l" + b, [sa, sb], f"{i + 1}. {lab}", dashed=bool(dash))
q.text("qn", "실선: 요청 / 점선: 응답과 멈춤(interrupt) / 기다리는 동안(waiting_input, waiting_executor)에는 인스턴스 자원을 잡지 않습니다.",
       40, H + 16, 1200, 20)
q.h = H + 50

# =============== 03 page 4: run 상태 전이
r = Page("run 상태 전이", 1160, 700, "run 상태 전이")
r.node("s0", "메시지 전송", 245, 90, 120, 36, "caller", shape="round", size=11)
for k, x, y, kind in (("queued", 260, 200, "state"), ("running", 560, 200, "state"),
                      ("waiting_input", 860, 80, "state"), ("waiting_executor", 860, 320, "state"),
                      ("succeeded", 360, 480, "related"), ("failed", 560, 480, "warn"),
                      ("cancelled", 760, 480, "infra")):
    r.node(k, k, x, y, 150, 50, kind, shape="round")
path(r, "s0", "queued", [(305, 126), (305, 200)])
path(r, "queued", "running", [(410, 215), (560, 215)], "worker가 lease 획득")
path(r, "running", "queued", [(560, 238), (410, 238)], "lease 만료, 인스턴스 종료", t=0.42)
path(r, "running", "waiting_input", [(710, 212), (785, 212), (785, 105), (860, 105)], "사용자 확인 요청", t=0.55)
path(r, "running", "waiting_executor", [(710, 238), (785, 238), (785, 345), (860, 345)], "executor에 코드 제출", t=0.55)
path(r, "waiting_input", "queued", [(935, 80), (935, 45), (365, 45), (365, 200)], "사용자가 답함", t=0.4)
path(r, "waiting_executor", "queued", [(960, 370), (960, 630), (230, 630), (230, 225), (260, 225)],
     "executor 이벤트 도착", t=0.45)
path(r, "running", "succeeded", [(590, 250), (590, 430), (435, 430), (435, 480)], "그래프 끝", t=0.7)
path(r, "running", "failed", [(635, 250), (635, 480)], "예외", t=0.5)
path(r, "running", "cancelled", [(680, 250), (680, 430), (835, 430), (835, 480)], "취소", t=0.7)
path(r, "waiting_executor", "cancelled", [(890, 370), (890, 480)], "취소")
path(r, "waiting_input", "cancelled", [(1010, 105), (1060, 105), (1060, 505), (910, 505)], "취소", t=0.5)
path(r, "queued", "cancelled", [(335, 250), (335, 570), (835, 570), (835, 530)], "취소", t=0.5)
r.text("rn", "queued, waiting_input, waiting_executor 상태에서는 인스턴스 자원을 쓰지 않습니다. running은 실행 슬롯 1개를 씁니다.",
       60, 664, 1000, 20)

# =============== 03 page 5: 배치 리포트
b = Page("배치 리포트", 1500, 480, "배치 리포트 작성 흐름 (AW-04)")
b.node("ev", "배치 실행 성공 이벤트", 40, 90, 200, 56, "related", sub="executor가 Redis 스트림에 씀")
b.node("enq", "작업 등록", 40, 200, 200, 56, "ours", sub="ExecutorEventConsumer\n키 batch-report:{execution_id}")
b.node("rec", "누락 복구", 40, 320, 200, 56, "ours", sub="BatchReportRecovery\n(10분마다, 최근 14일)")
X0 = 300
st = [("QUEUED", "대기", "state"), ("COLLECTING", "executor에서 실행 결과와\n노트북을 모음.\n준비될 때까지 대기", "state"),
      ("GENERATING", "리포트 Agent 실행\nprompts/batch_analyst.md\nread_step, submit_report\n이전 실행 요약 참고", "state"),
      ("MATERIALIZING", "리포트를 executor\nArtifact로 저장.\n이번 실행 요약을 기억", "state"),
      ("SUCCEEDED", "끝", "related")]
for i, (nm, sub, kind) in enumerate(st):
    b.node(nm, nm, X0 + i * 235, 178, 195, 100, kind, sub=sub, size=12)
b.node("FAILED", "FAILED", X0 + 2 * 235, 350, 195, 50, "warn", sub="failed_stage에 실패한 단계", size=12)
b.edge("ev", "enq")
path(b, "enq", "QUEUED", [(240, 228), (300, 228)])
path(b, "rec", "QUEUED", [(240, 348), (270, 348), (270, 258), (300, 258)])
for i in range(4):
    b.edge(st[i][0], st[i + 1][0], ex=("r", .5), en=("l", .5))
for nm in ("COLLECTING", "GENERATING", "MATERIALIZING"):
    n = b.nodes[nm]
    cx = n["x"] + n["w"] / 2
    if nm == "GENERATING":
        path(b, nm, "FAILED", [(cx, 278), (cx, 350)], "실패")
    elif nm == "COLLECTING":
        path(b, nm, "FAILED", [(cx, 278), (cx, 375), (X0 + 470, 375)], "", )
    else:
        path(b, nm, "FAILED", [(cx, 278), (cx, 375), (X0 + 470 + 195, 375)], "")
b.text("bn", "채팅 run 큐를 거치지 않습니다. 세션, 프로젝트, 체크포인트가 없고 재시도하면 Agent를 처음부터 다시 실행합니다. "
       "진행 이벤트는 채팅과 같은 형식으로 작업별 스트림에 보냅니다.", 40, 430, 1400, 20)

# =============== 03 page 6: 메모리 추출
e = Page("메모리 추출", 1500, 420, "프로젝트 메모리 추출 흐름 (AW-05)")
steps = [("턴 종료", "RunScheduler가 프로젝트를\ndirty로 표시, pending_turns 증가", "ours"),
         ("대기", "대화가 180초 조용하거나\n5턴이 쌓일 때까지", "note"),
         ("작업 잡기", "MemoryWorker가 lease 획득\n(FOR UPDATE SKIP LOCKED)", "ours"),
         ("메시지 읽기", "커서 뒤의 user, assistant\n메시지 (최대 8,000 토큰)", "ours"),
         ("LLM 1회 호출", "prompts/memory_worker.md\n주제별 줄 편집을 제안", "state"),
         ("코드 검증", "인용이 사용자 메시지에 있는지,\nURL·경로·제목이 없는지, id 존재", "ours"),
         ("반영", "store에 쓰고 memory_history 기록\n커서 전진, memory_updated 이벤트", "store")]
for i, (nm, sub, kind) in enumerate(steps):
    row, col = divmod(i, 4)
    e.node("m%d" % i, nm, 40 + col * 360, 90 + row * 150, 300, 80, kind, sub=sub, size=12)
for i in range(len(steps) - 1):
    if i == 3:
        path(e, "m3", "m4", [(1270, 170), (1270, 205), (190, 205), (190, 240)])
    else:
        e.edge("m%d" % i, "m%d" % (i + 1), ex=("r", .5), en=("l", .5))
e.text("en", "사용자가 직접 말한 오래 갈 사실, 선호, 관심사, 일정만 남깁니다. 검증에 실패한 편집은 버리고 나머지는 반영합니다. "
       "계속 실패하는 구간은 건너뜁니다.", 40, 380, 1400, 20)

write([g, s, q, r, b, e], "03-agent-graph", OUT)
