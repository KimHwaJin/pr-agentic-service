"""Parse docs/handover/03-db-physical.md into a schema dict."""
import re, json, sys

KO = {"users": "사용자", "projects": "프로젝트", "project_members": "프로젝트 구성원",
      "sessions": "채팅 세션", "messages": "메시지", "images": "이미지", "runs": "실행",
      "run_requests": "실행 요청 키", "run_events": "실행 이벤트",
      "executor_inbox": "executor 이벤트 보관함", "code_sources": "코드 파일 기록",
      "memory_history": "메모리 변경 이력", "memory_extraction_state": "메모리 정리 상태",
      "workflows": "워크플로우", "workflow_query_vectors": "워크플로우 검색 벡터",
      "batch_report_jobs": "배치 리포트 작업", "batch_report_events": "배치 리포트 이벤트",
      "api_clients": "API 클라이언트", "gaia_sessions": "gaia 세션 대응"}
AREA = {}
for area, names in {
    "사용자와 프로젝트": "users projects project_members", "대화": "sessions messages images",
    "실행": "runs run_requests run_events", "executor 연동": "executor_inbox code_sources",
    "프로젝트 메모리": "memory_history memory_extraction_state",
    "워크플로우": "workflows workflow_query_vectors",
    "배치 리포트": "batch_report_jobs batch_report_events", "서비스 간 인증": "api_clients",
    "gaia 연동": "gaia_sessions"}.items():
    for n in names.split():
        AREA[n] = area


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def load(path):
    text = open(path, encoding="utf-8").read()
    tables, order = {}, []
    # table list
    sec2 = text.split("## 2. 테이블 목록")[1].split("## 3.")[0]
    meta = {}
    for ln in sec2.splitlines():
        c = cells(ln) if ln.startswith("|") else []
        if len(c) == 5 and c[0].isdigit():
            meta[c[1]] = dict(no=int(c[0]), pk=c[2], growth=c[3], cleanup=c[4])
    sec3 = text.split("## 3. 테이블 명세")[1].split("## 4. 인덱스")[0]
    for block in re.split(r"\n### 3\.\d+ ", sec3)[1:]:
        name = block.splitlines()[0].strip()
        cols = []
        for ln in block.splitlines():
            if not ln.startswith("|"):
                continue
            c = cells(ln)
            if len(c) != 5 or c[0] in ("컬럼",) or set(c[0]) <= set("- "):
                continue
            names, typ, null, default, desc = c
            for nm in [x.strip() for x in names.split(",")]:
                d = desc.replace("`", "")
                key = []
                if re.match(r"PK\b", d):
                    key.append("PK")
                m = re.search(r"FK → ([a-z_]+)\.([a-z_]+)", d)
                if m:
                    key.append("FK")
                if "UNIQUE" in d:
                    key.append("UK")
                cols.append(dict(name=nm, type=typ, null=null, default=default.replace("`", ""),
                                 desc=d, key=",".join(key), fk=(m.group(1) + "." + m.group(2)) if m else ""))
        tables[name] = dict(name=name, ko=KO[name], area=AREA[name], cols=cols, **meta[name])
        order.append(name)
    sec4 = text.split("## 4. 인덱스")[1].split("### 4.1")[0]
    idx = []
    for ln in sec4.splitlines():
        c = cells(ln) if ln.startswith("|") else []
        if len(c) == 4 and c[0] not in ("테이블",) and not set(c[0]) <= set("- "):
            idx.append(dict(table=c[0], name=c[1], cols=c[2].replace("`", ""), use=c[3]))
    return dict(tables=tables, order=order, indexes=idx)


if __name__ == "__main__":
    s = load(sys.argv[1])
    for n in s["order"]:
        t = s["tables"][n]
        print(t["no"], n, len(t["cols"]), [c["name"] + ":" + c["key"] for c in t["cols"] if c["key"]])
    print(len(s["indexes"]))
