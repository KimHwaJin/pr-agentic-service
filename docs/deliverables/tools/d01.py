import sys
from dg import Page, write

# ---------------- page 1: 논리 구성도
p = Page("논리 구성도", 1560, 980, "pr-agentic-service 전체 시스템 구성도 (논리 구성)")

p.node("browser", "브라우저", 300, 80, 150, 60, "caller", sub="웹 화면 사용자")
p.node("svc", "다른 서비스·에이전트", 470, 80, 170, 60, "caller", sub="API 키 호출자")
p.node("gaia", "gaia 채팅 화면", 660, 80, 150, 60, "caller", sub="사내 채팅 플랫폼")

p.group("inst", "pr-agentic-service 인스턴스 (프로세스 1개, 수평 확장)",
        280, 230, 920, 230, align="right")
p.node("api", "api_service", 320, 300, 260, 120, "ours",
       sub="FastAPI 라우터, 인증\n채팅 API, SSE 이벤트\nexecutor·배치 게이트웨이")
p.node("bridge", "gaia_bridge", 660, 300, 150, 120, "ours",
       sub="gaia workflow\ndtest.analyst")
p.node("worker", "worker", 860, 300, 140, 120, "ours",
       sub="RunScheduler\nexecutor 이벤트 수신\n메모리, 배치 리포트")
p.node("agent", "agent", 1050, 300, 130, 120, "ours",
       sub="LangGraph 그래프\nmiddleware, 도구\nskill")
p.node("sso", "SSO (IdP)", 40, 305, 170, 50, "infra")
p.node("batch", "pr-batch", 40, 385, 170, 50, "related", sub="배치 등록·스케줄")

p.node("llm", "LLM 게이트웨이", 1300, 250, 200, 56, "infra", sub="OpenAI 호환")
p.node("emb", "임베딩 게이트웨이", 1300, 332, 200, 56, "infra", sub="워크플로우 검색")
p.node("phx", "Phoenix", 1300, 414, 200, 56, "infra", sub="실행 추적 (선택)")

p.node("pg", "PostgreSQL", 400, 690, 220, 120, "store", shape="cyl",
       sub="앱 테이블, run 큐\npgvector (워크플로우 검색)\nLangGraph 체크포인트·store")
p.node("redis", "Redis", 700, 690, 200, 120, "store", shape="cyl",
       sub="로그인 세션\n이벤트 발행/구독\nexecutor 이벤트 스트림")
p.node("pv", "공유 저장소 (PV)", 1020, 690, 170, 120, "store", shape="cyl",
       sub="분석 코드 파일\n실행 결과 파일")
p.node("exec", "executor", 1300, 705, 200, 90, "related",
       sub="분석 코드 실행(커널)\n노트북, 결과물 보관")

# callers
p.edge("browser", "api", "HTTPS, SSE\n(SSO 쿠키)", en=("t", 55 / 260), t=0.4)
p.edge("svc", "api", "X-Api-Key", en=("t", 235 / 260), t=0.4)
p.edge("gaia", "bridge", "workflow 호출", t=0.4)
# inside
p.edge("bridge", "api", "run 생성", ex=("l", 0.5), en=("r", 0.5))
p.edge("worker", "agent", "턴 실행", ex=("r", 0.5), en=("l", 0.5))
# left
p.edge("api", "sso", "로그인 확인", ex=("l", 0.25), en=("r", 0.5))
p.edge("api", "batch", "배치 중계", ex=("l", 110 / 120), en=("r", 0.5))
# right
p.edge("agent", "llm", "모델 호출", ex=("r", 0.2), en=("l", 0.5), mid=1240, t=0.8)
p.edge("agent", "emb", "", ex=("r", 0.5), en=("l", 0.5))
p.edge("agent", "phx", "", ex=("r", 0.8), en=("l", 0.5), mid=1240, dashed=True)
# stores
p.edge("api", "pg", "앱 데이터\nrun 등록", ex=("b", 190 / 260), en=("t", 0.5), both=True, t=0.35)
p.edge("api", "redis", "세션, 이벤트 구독", ex=("b", 240 / 260), en=("t", 0.2), mid=560,
       both=True, t=0.42)
p.edge("worker", "pg", "run 가져가기 (lease)", ex=("b", 20 / 140), en=("t", 190 / 220), mid=640,
       both=True, t=0.55)
p.edge("worker", "redis", "이벤트 발행\n스트림 수신", ex=("b", 30 / 140), en=("t", 190 / 200),
       both=True, t=0.42)
p.edge("agent", "pv", "코드·결과 파일", ex=("b", 55 / 130), en=("t", 0.5), both=True, t=0.6)
p.edge("agent", "exec", "분석 코드 실행 제출", ex=("b", 110 / 130), en=("t", 0.5), mid=600, t=0.55)
p.edge("exec", "pv", "", ex=("l", 0.5), en=("r", 0.5), both=True)
p.edge("exec", "redis", "완료 이벤트 스트림", ex=("b", 0.3), en=("b", 0.5),
       via=[(1360, 850), (800, 850)], t=0.5)
p.edge("api", "exec", "게이트웨이 중계, 결과물·커널 조회", ex=("b", 20 / 260), en=("b", 0.7),
       via=[(340, 890), (1440, 890)], t=0.5)
p.edge("batch", "exec", "배치 실행 제출", ex=("b", 0.5), en=("b", 0.9),
       via=[(125, 930), (1480, 930)], t=0.5)

# legend
p.text("lg", "범례", 1300, 70, 60, 20, bold=True)
for i, (k, name) in enumerate([("caller", "호출자"), ("ours", "우리 시스템"),
                               ("related", "연관 시스템"), ("infra", "외부 기반"),
                               ("store", "저장소")]):
    col, row = i % 2, i // 2
    p.node(f"lg{i}", name, 1300 + col * 105, 96 + row * 34, 95, 26, k, size=11)

# ---------------- page 2: 환경·배포 구성
q = Page("환경·배포 구성도", 1640, 900, "pr-agentic-service 환경·배포 구성도 (내부망)")


def env(prefix, name, x, cfg):
    y = 80
    q.group(prefix, f"{name} 환경", x, y, 640, 440)
    q.node(prefix + "rt", "앞단 라우팅 (사내 플랫폼)", x + 30, y + 44, 580, 40, "infra")
    q.node(prefix + "inst", "pr-agentic-service 인스턴스 × N", x + 30, y + 130, 260, 110, "ours",
           sub=f"APP_ENV={cfg} · config.yml + config.{cfg}.yml\n포트 8080 · UID/GID 1000\n"
               "RUN_MODE=all (API + worker)")
    q.node(prefix + "ex", "executor", x + 350, y + 130, 250, 46, "related")
    q.node(prefix + "bt", "pr-batch", x + 350, y + 194, 250, 46, "related")
    q.node(prefix + "rd", f"Redis ({name})", x + 30, y + 300, 260, 110, "store", shape="cyl",
           sub="standalone 또는 Sentinel (REDIS_MODE)\nexecutor와 같은 서버, 같은 DB 번호")
    q.node(prefix + "pv", "공유 저장소", x + 350, y + 300, 250, 110, "store", shape="cyl",
           sub="/mnt/data 로 마운트\nexecutor와 함께 사용")
    q.edge(prefix + "rt", prefix + "inst", "", ex=("b", 130 / 580), en=("t", 0.5))
    q.edge(prefix + "inst", prefix + "ex", "", ex=("r", 23 / 110), en=("l", 0.5))
    q.edge(prefix + "inst", prefix + "bt", "", ex=("r", 87 / 110), en=("l", 0.5))
    q.edge(prefix + "inst", prefix + "rd", "", ex=("b", 0.4), en=("t", 0.4), both=True)
    q.edge(prefix + "inst", prefix + "pv", "", ex=("b", 0.85), en=("t", 0.3), mid=y + 268,
           both=True)
    q.edge(prefix + "ex", prefix + "pv", "", ex=("r", 0.5), en=("r", 0.5),
           via=[(x + 620, y + 153), (x + 620, y + 355)], both=True)


env("d", "dev", 40, "dev")
env("p", "prd", 720, "prd")

q.group("pgsrv", "PostgreSQL 서버 (dev·prd 공용)", 40, 590, 1320, 250, kind="group2")
q.text("pgn", "사내 서비스형 DB, pgvector 확장 · dev와 prd가 같은 서버를 쓰고 데이터베이스 이름으로 나뉨 · "
       "연결 한도 150을 함께 사용 · prd 서버 분리 예정", 70, 800, 1260, 24)
for prefix, x, names in (("d", 40, ("dtest", "executor", "batch")),
                         ("p", 720, ("dtestprd", "executorprd", "batchprd"))):
    q.group(prefix + "dbs", "데이터베이스", x + 30, 640, 580, 150, kind="group2")
    for i, nm in enumerate(names):
        q.node(f"{prefix}db{i}", nm, x + 55 + i * 185, 676, 160, 90,
               "store" if i == 0 else "related", shape="cyl",
               sub=("pr-agentic-service" if i == 0 else ("executor" if i == 1 else "pr-batch")))
    q.edge(prefix, prefix + "dbs", "DATABASE_URL (데이터베이스 이름으로 환경 구분)",
           ex=("b", 0.5), en=("t", 0.5), t=0.3)

q.group("common", "공통 기반", 1400, 80, 200, 440, kind="group2")
for i, (nm, sub) in enumerate([("SSO (IdP)", "로그인 확인"), ("LLM 게이트웨이", "모델 호출"),
                               ("임베딩 게이트웨이", "워크플로우 검색"),
                               ("키바나", "로그 조회"), ("Phoenix", "실행 추적 (선택)")]):
    q.node(f"c{i}", nm, 1420, 124 + i * 76, 160, 56, "infra", sub=sub)
q.text("cn", "환경별 주소와 키는\nconfig.{env}.yml 에 있음", 1420, 610, 180, 40)
q.text("stg", "stg 환경도 같은 형태입니다 (APP_ENV=stg, config.stg.yml).", 40, 856, 800, 24)

write([p, q], "01-system-architecture", sys.argv[1])
