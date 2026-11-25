import sys
from dg import Page, write
from schema import load

S = load(sys.argv[1])
T = S["tables"]
W = 250
X = [60, 390, 720, 1050]
NOTE = "실선: 외래키(FK) 제약이 있는 관계  /  점선: 제약 없이 값으로만 참조하는 관계  /  두 줄 표시 쪽이 부모(1), 까치발 쪽이 자식(0..N)"


def rows(name, types, only=None):
    out = []
    for c in T[name]["cols"]:
        if only and c["name"] not in only:
            continue
        out.append((c["key"], c["name"], c["type"] if types else ""))
    return out


def tbl(p, name, col, y, types, only=None, kind="ours"):
    r = rows(name, types, only)
    if only:
        r.append(("", "… (1페이지 참조)", ""))
    return p.table(name, name, r, X[col], y, W, sub=T[name]["ko"], kind=kind)


def link(p, a, b, pts, dashed=False, er="many"):
    """pts: absolute points; first lies on a's border, last on b's border."""
    def side(n, pt):
        n = p.nodes[n]
        x, y = pt
        if abs(x - n["x"]) < 1:
            return ("l", (y - n["y"]) / n["h"])
        if abs(x - n["x"] - n["w"]) < 1:
            return ("r", (y - n["y"]) / n["h"])
        if abs(y - n["y"]) < 1:
            return ("t", (x - n["x"]) / n["w"])
        assert abs(y - n["y"] - n["h"]) < 1, (a, b, pt, n)
        return ("b", (x - n["x"]) / n["w"])
    p.edge(a, b, ex=side(a, pts[0]), en=side(b, pts[-1]), via=pts[1:-1], dashed=dashed, er=er)


def page_a(types, title):
    p = Page("사용자·대화·실행", 1380, 1010, title)
    y = tbl(p, "users", 0, 80, types); y = tbl(p, "project_members", 0, y + 44, types)
    tbl(p, "gaia_sessions", 0, y + 50, types)
    y = tbl(p, "projects", 1, 80, types); y = tbl(p, "sessions", 1, y + 52, types)
    tbl(p, "images", 1, y + 52, types)
    y = tbl(p, "messages", 2, 80, types); y = tbl(p, "runs", 2, y + 46, types)
    tbl(p, "run_requests", 2, y + 48, types)
    y = tbl(p, "run_events", 3, 80, types); y = tbl(p, "executor_inbox", 3, y + 54, types)
    tbl(p, "code_sources", 3, y + 54, types)
    n = p.nodes
    B = lambda k: n[k]["y"] + n[k]["h"]
    Y = lambda k: n[k]["y"]
    R = lambda c: X[c] + W
    link(p, "projects", "users", [(X[1], 190), (R(0), 190)])
    link(p, "project_members", "users", [(185, Y("project_members")), (185, B("users"))])
    yp = Y("project_members") + 60
    link(p, "project_members", "projects", [(R(0), yp), (335, yp), (335, 280), (X[1], 280)])
    link(p, "sessions", "projects", [(515, Y("sessions")), (515, B("projects"))])
    ys = Y("sessions") + 50
    link(p, "sessions", "users", [(X[1], ys), (360, ys), (360, 305), (R(0), 305)])
    yg = Y("gaia_sessions") + 70
    link(p, "gaia_sessions", "users", [(X[0], yg), (30, yg), (30, 200), (X[0], 200)])
    link(p, "gaia_sessions", "sessions", [(R(0), yg + 20), (350, yg + 20), (350, B("sessions") - 40),
                                          (X[1], B("sessions") - 40)])
    link(p, "images", "sessions", [(515, Y("images")), (515, B("sessions"))], dashed=True)
    link(p, "messages", "sessions", [(X[2], 170), (665, 170), (665, ys), (R(1), ys)])
    yr = Y("runs") + 90
    link(p, "runs", "sessions", [(X[2], yr), (R(1), yr)])
    yq = Y("run_requests") + 80
    link(p, "run_requests", "sessions", [(X[2], yq), (690, yq), (690, B("sessions") - 30),
                                         (R(1), B("sessions") - 30)], dashed=True)
    link(p, "messages", "runs", [(845, B("messages")), (845, Y("runs"))], dashed=True)
    link(p, "run_events", "runs", [(X[3], 160), (1010, 160), (1010, Y("runs") + 40),
                                   (R(2), Y("runs") + 40)], dashed=True)
    ye = Y("executor_inbox") + 80
    link(p, "executor_inbox", "runs", [(X[3], ye), (R(2), ye)], dashed=True)
    yc = Y("code_sources") + 80
    link(p, "code_sources", "runs", [(X[3], yc), (R(2), yc)], dashed=True)
    p.text("note", NOTE, 60, p.h - 34, 1200, 20)
    return p


def page_b(types, title):
    p = Page("워크플로우·배치·메모리·인증", 1400, 880, title)
    y = tbl(p, "users", 0, 90, types, only=("id", "employee_id"), kind="infra")
    tbl(p, "api_clients", 0, y + 60, types)
    y = tbl(p, "workflows", 1, 90, types); tbl(p, "workflow_query_vectors", 1, y + 52, types)
    y = tbl(p, "batch_report_jobs", 2, 90, types); tbl(p, "batch_report_events", 2, y + 52, types)
    y = tbl(p, "projects", 3, 90, types, only=("id", "name"), kind="infra")
    y = tbl(p, "memory_history", 3, y + 56, types)
    tbl(p, "memory_extraction_state", 3, y + 54, types)
    n = p.nodes
    B = lambda k: n[k]["y"] + n[k]["h"]
    Y = lambda k: n[k]["y"]
    R = lambda c: X[c] + W
    link(p, "workflows", "users", [(X[1], 135), (R(0), 135)])
    link(p, "workflow_query_vectors", "workflows",
         [(515, Y("workflow_query_vectors")), (515, B("workflows"))])
    link(p, "batch_report_jobs", "users", [(845, 90), (845, 62), (185, 62), (185, 90)], dashed=True)
    link(p, "batch_report_events", "batch_report_jobs",
         [(845, Y("batch_report_events")), (845, B("batch_report_jobs"))], dashed=True)
    link(p, "api_clients", "users", [(185, Y("api_clients")), (185, B("users"))], dashed=True)
    link(p, "memory_history", "projects", [(1175, Y("memory_history")), (1175, B("projects"))],
         dashed=True)
    ym = Y("memory_extraction_state") + 100
    link(p, "memory_extraction_state", "projects", [(R(3), ym), (1340, ym), (1340, 135), (R(3), 135)],
         dashed=True, er="one")
    p.text("note", NOTE + "   회색: 다른 페이지의 테이블", 60, p.h - 34, 1300, 20)
    return p


def overview():
    p = Page("전체", 1500, 800, "논리 ERD (전체)")
    pos = {"workflow_query_vectors": (60, 90), "workflows": (300, 90), "users": (540, 90),
           "batch_report_jobs": (780, 90), "batch_report_events": (1020, 90),
           "api_clients": (1260, 90),
           "memory_history": (60, 230), "projects": (300, 230), "project_members": (540, 230),
           "memory_extraction_state": (60, 330),
           "images": (60, 400), "sessions": (300, 400), "gaia_sessions": (540, 400),
           "messages": (60, 540), "runs": (300, 540), "run_requests": (540, 540),
           "run_events": (60, 680), "code_sources": (300, 680), "executor_inbox": (540, 680)}
    for k, (x, y) in pos.items():
        p.node(k, k, x, y, 190, 50, "ours", sub=T[k]["ko"], size=12)
    L = lambda a, b, pts, d=False, er="many": link(p, a, b, pts, d, er)
    L("workflow_query_vectors", "workflows", [(250, 115), (300, 115)])
    L("workflows", "users", [(490, 115), (540, 115)])
    L("batch_report_jobs", "users", [(780, 115), (730, 115)], True)
    L("batch_report_events", "batch_report_jobs", [(1020, 115), (970, 115)], True)
    L("api_clients", "users", [(1355, 90), (1355, 62), (635, 62), (635, 90)], True)
    L("projects", "users", [(395, 230), (395, 185), (578, 185), (578, 140)])
    L("project_members", "users", [(635, 230), (635, 140)])
    L("project_members", "projects", [(540, 255), (490, 255)])
    L("memory_history", "projects", [(250, 245), (300, 245)], True)
    L("memory_extraction_state", "projects", [(250, 355), (275, 355), (275, 268), (300, 268)], True, "one")
    L("sessions", "projects", [(395, 400), (395, 280)])
    L("sessions", "users", [(490, 412), (515, 412), (515, 200), (606, 200), (606, 140)])
    L("gaia_sessions", "sessions", [(540, 436), (490, 436)])
    L("gaia_sessions", "users", [(730, 425), (750, 425), (750, 170), (692, 170), (692, 140)])
    L("images", "sessions", [(250, 415), (300, 415)], True)
    L("messages", "sessions", [(155, 540), (155, 495), (275, 495), (275, 438), (300, 438)])
    L("runs", "sessions", [(395, 540), (395, 450)])
    L("run_requests", "sessions", [(635, 540), (635, 495), (440, 495), (440, 450)], True)
    L("messages", "runs", [(250, 555), (300, 555)], True)
    L("run_events", "runs", [(250, 705), (275, 705), (275, 578), (300, 578)], True)
    L("code_sources", "runs", [(395, 680), (395, 590)], True)
    L("executor_inbox", "runs", [(540, 705), (515, 705), (515, 565), (490, 565)], True)
    p.text("note", NOTE, 60, p.h - 34, 1200, 20)
    p.text("areas", "영역\n사용자와 프로젝트: users, projects, project_members\n대화: sessions, messages, images\n"
           "실행: runs, run_requests, run_events\nexecutor 연동: executor_inbox, code_sources\n"
           "프로젝트 메모리: memory_history, memory_extraction_state\n"
           "워크플로우: workflows, workflow_query_vectors\n"
           "배치 리포트: batch_report_jobs, batch_report_events\n서비스 간 인증: api_clients\n"
           "gaia 연동: gaia_sessions", 820, 260, 620, 200)
    return p


out = sys.argv[2]
write([overview(), page_a(False, "논리 ERD (사용자, 대화, 실행, executor 연동, gaia 연동)"),
       page_b(False, "논리 ERD (워크플로우, 배치 리포트, 프로젝트 메모리, 서비스 간 인증)")],
      "04-erd-logical", out)
write([page_a(True, "물리 ERD (사용자, 대화, 실행, executor 연동, gaia 연동)"),
       page_b(True, "물리 ERD (워크플로우, 배치 리포트, 프로젝트 메모리, 서비스 간 인증)")],
      "05-erd-physical", out)
