import sys
from dg import Page, write
from d0203 import path  # noqa: F401  (d0203 writes its own files on import; harmless)

OUT = sys.argv[1]

# =============== 08: 장애 대응 순서
o = Page("장애 대응 순서", 1480, 700, "장애 대응: 먼저 보는 순서")
o.node("start", "이상 신고 또는 알림", 40, 80, 220, 50, "caller", shape="round")
steps = [
    ("s1", "1. 인스턴스 상태", "떠 있는가, 재시작을 반복하는가"),
    ("s2", "2. GET /api/v1/healthz", "status 가 ok 인가"),
    ("s3", "3. 앱 로그", "오류 ID, X-Request-ID,\n로그 키워드로 검색"),
    ("s4", "4. DB", "run 상태 분포, 연결 수"),
    ("s5", "5. 연결된 서비스", "executor, batch,\nLLM 게이트웨이, Redis"),
]
acts = [
    ("a1", "기동 로그 확인", "ValueError, dtest_startup_failed\n설정 검사, 마이그레이션, DB·Redis 접속\n(운영자 메뉴얼 2.4, 4.4절)", "warn"),
    ("a2", "죽은 루프 확인", "응답의 stopped 에 루프 이름\n실행 환경이 인스턴스를 재시작함\n반복되면 직전 예외 로그 (9.3절)", "warn"),
    ("a3", "증상별 대응표로 이동", "로그 키워드 사전 (6.11절)\n증상별 대응표 (6.3절)", "ours"),
    ("a4", "run, DB 대응", "queued 적체, failed 증가 (6.5절)\n연결 한도 (6.8절), 자주 쓰는 SQL (6.9절)", "ours"),
    ("a5", "상대 서비스 확인", "502 는 upstream_unreachable path 로 구분\n분석이 안 끝나면 executor 대기 (6.6절)\n시스템 화면의 런타임, 이벤트 스트림 (10장)", "related"),
]
Y0, DY = 170, 100
for i, (sid, t, sub) in enumerate(steps):
    y = Y0 + i * DY
    o.node(sid, t, 40, y, 220, 70, "ours", sub=sub, size=12)
    aid, at_, asub, kind = acts[i]
    o.node(aid, at_, 420, y - 4, 330, 78, kind, sub=asub, size=12)
    o.edge(sid, aid, "이상 있음" if i < 2 else "", ex=("r", .5), en=("l", .5))
o.edge("start", "s1")
for i in range(4):
    o.edge(steps[i][0], steps[i + 1][0], "정상" if i < 2 else "")

o.group("g", "화면에서 바로 할 수 있는 조치 (시스템 탭, 관리자)", 830, 80, 610, 560, kind="group2")
tools = [
    ("t1", "런타임", "런타임별 CPU, 메모리, 실행 슬롯\n점검, 비우기, 활성화, 사용 중지"),
    ("t2", "런타임 커널", "커널별 메모리와 그 커널을 쓰는 실행\n실행 취소, 남겨진 커널 삭제"),
    ("t3", "점검", "새 실행 접수 중지와 재개\n진행 중 실행 멈추기"),
    ("t4", "이벤트 스트림", "tenant별 Redis 스트림 항목 수,\nconsumer group 의 lag, pending"),
    ("t5", "사용자, API 키", "사용자 비활성화, 역할 변경\n키 발급, 재발급, 폐기"),
]
for i, (tid, t, sub) in enumerate(tools):
    o.node(tid, t, 860, 130 + i * 100, 550, 76, "note", sub=sub, size=12)
path(o, "a5", "t1", [(750, Y0 + 4 * DY + 20), (790, Y0 + 4 * DY + 20), (790, 168), (860, 168)], dashed=True)
o.text("n", "절 번호는 운영자 메뉴얼의 절입니다. 이상 신호의 기준값은 7.2절에 있습니다.", 40, 660, 760, 20)

write([o], "08-ops-flow", OUT)

# =============== 07: 사용자 흐름
u = Page("사용 흐름", 1500, 640, "사용자 메뉴얼: 분석 한 건의 흐름")
row = [
    ("login", "로그인", "사내 SSO", "caller"),
    ("proj", "프로젝트 선택", "없으면 새 프로젝트\n(지침, 기본 코드 레벨)", "ours"),
    ("new", "새 대화", "모델, 코드 레벨 선택", "ours"),
    ("ask", "분석 요청 입력", "이미지 첨부 가능\nEnter 전송", "ours"),
]
X0, DX, W = 40, 240, 200
for i, (nid, t, sub, kind) in enumerate(row):
    u.node(nid, t, X0 + i * DX, 90, W, 70, kind, sub=sub, size=12)
for i in range(3):
    u.edge(row[i][0], row[i + 1][0], ex=("r", .5), en=("l", .5))

u.node("agent", "Agent 가 처리", 1000, 90, 220, 70, "state", sub="진행 상황이 실시간으로 보임", size=12)
u.edge("ask", "agent", ex=("r", .5), en=("l", .5))

u.group("hg", "확인 필요 카드 (Agent 가 물어볼 때만)", 760, 230, 700, 150, kind="group2")
cards = [
    ("c1", "질문", "답변을 입력"),
    ("c2", "계획 확인", "승인하고 실행\n또는 수정 요청"),
    ("c3", "코드 실행 승인", "실행 또는 거절\n코드를 직접 고칠 수 있음"),
]
for i, (cid, t, sub) in enumerate(cards):
    u.node(cid, t, 790 + i * 220, 280, 190, 76, "caller", sub=sub, size=12)
path(u, "agent", "c2", [(1110, 160), (1110, 210), (1105, 210), (1105, 280)], "확인이 필요하면")
path(u, "c3", "agent", [(1420, 318), (1440, 318), (1440, 125), (1220, 125)], "답하면 이어서 진행", t=0.8)

u.node("res", "결과 확인", 40, 470, 220, 76, "related", sub="답변, 표와 그림,\n노트북 보기, JupyterLab에서 열기", size=12)
path(u, "agent", "res", [(1060, 160), (1060, 200), (150, 200), (150, 470)], "분석 끝", t=0.75)
u.group("ag", "결과를 본 뒤 필요에 따라", 340, 430, 720, 150, kind="group2")
after = [
    ("a1", "이어서 질문", "같은 대화에서 계속"),
    ("a2", "워크플로우로 저장", "다음에 같은 분석을 추천받음"),
    ("a3", "배치로 등록", "노트북을 일정에 따라 반복 실행\n끝나면 리포트 생성"),
]
for i, (aid, t, sub) in enumerate(after):
    u.node(aid, t, 365 + i * 230, 478, 210, 72, "ours", sub=sub, size=12)
u.edge("res", "ag", ex=("r", .5), en=("l", .52))
u.text("un", "실행 기록은 왼쪽 메뉴의 실행 이력에서 다시 볼 수 있습니다.", 40, 600, 1000, 20)

write([u], "07-user-flow", OUT)
