import sys
from dg import Page, write

OUT = sys.argv[1]

# =============== S/W 구성도 (계층)
s = Page("SW 구성도", 1500, 800, "S/W 구성도")
def layer(i, title, y, h, kind="group2"):
    s.group("L%d" % i, title, 40, y, 1420, h, kind=kind)

layer(1, "사용자 계층", 60, 110)
for i, (t, sub) in enumerate([("웹 브라우저", "웹 화면 (HTML, JavaScript)\nSSO 쿠키 로그인"),
                              ("gaia 채팅 화면", "사내 채팅 플랫폼\nworkflow dtest.analyst"),
                              ("다른 서비스, 에이전트", "X-Api-Key, X-User-Id\n게이트웨이 API 호출")]):
    s.node("c%d" % i, t, 300 + i * 390, 86, 340, 70, "caller", sub=sub, size=12)

layer(2, "Application 계층: gaia-api-service (컨테이너, 인스턴스 N개)", 190, 300, kind="group")
s.node("a_rt", "실행 환경", 70, 230, 250, 240, "note",
       sub="Python 3.11\nuvicorn (worker 1개)\ngaia 템플릿 app.py\nHCP 라이브러리\n\n포트 5000\nUID/GID 1000", size=12)
apps = [("웹·API", "FastAPI (0.137 미만)\nSSE 실시간 이벤트\nPydantic Settings\nhttpx"),
        ("Agent", "LangGraph 1.2\nLangChain 1.4\nlangchain-openai\nskill, tool, 프롬프트 파일"),
        ("데이터 접근", "SQLAlchemy 2.1 (async)\npsycopg 3\nAlembic\nlanggraph-checkpoint-postgres 3.1.3\npgvector, redis-py 7"),
        ("관측", "로그: logger.yml (gaia, HCP)\n추적: Phoenix (선택)\n헬스체크: /api/v1/healthz")]
for i, (t, sub) in enumerate(apps):
    s.node("a%d" % i, t, 350 + i * 275, 230, 255, 240, "ours", sub=sub, size=12)

layer(3, "데이터 계층", 510, 120)
for i, (t, sub) in enumerate([("PostgreSQL", "pgvector 확장\n앱 테이블, 체크포인트, 벡터"),
                              ("Redis", "6.2 이상\nstandalone 또는 Sentinel"),
                              ("공유 저장소 (PV)", "/mnt/data\nexecutor와 함께 사용")]):
    s.node("d%d" % i, t, 300 + i * 390, 536, 340, 76, "store", shape="cyl", sub=sub, size=12)

layer(4, "연관 시스템과 기반", 650, 110)
rel = [("executor", "분석 코드 실행\nJupyter 런타임", "related"), ("batch", "배치 일정 실행", "related"),
       ("LLM 게이트웨이", "OpenAI 호환 API", "infra"), ("임베딩 게이트웨이", "워크플로우 검색", "infra"),
       ("SSO (IdP)", "로그인 확인", "infra"), ("키바나, Phoenix", "로그 조회, 실행 추적", "infra")]
for i, (t, sub, k) in enumerate(rel):
    s.node("r%d" % i, t, 70 + i * 232, 680, 212, 62, k, sub=sub, size=12)
s.text("n", "컨테이너 배치, 자동 확장, 앞단 라우팅은 사내 플랫폼이 맡습니다. 버전은 pyproject.toml 기준입니다.", 40, 772, 1200, 20)

# =============== 인터페이스 흐름도
f = Page("인터페이스 흐름도", 1500, 910, "인터페이스 흐름도")
f.node("br", "웹 브라우저", 40, 130, 200, 60, "caller")
f.node("ext", "다른 서비스, 에이전트", 40, 220, 200, 60, "caller")
f.node("gaia", "gaia 채팅 화면", 40, 310, 200, 60, "caller")
f.group("svc", "gaia-api-service", 420, 80, 400, 620, kind="group")
f.node("api", "api_service", 450, 130, 340, 150, "ours", sub="채팅 API, SSE, 인증\nexecutor·배치 게이트웨이", size=12)
f.node("gb", "gaia_bridge", 450, 310, 340, 60, "ours", sub="gaia 메시지를 run으로 실행", size=12)
f.node("wk", "worker", 450, 400, 340, 90, "ours", sub="run 스케줄러, executor 이벤트 수신\n배치 리포트, 메모리, 정리", size=12)
f.node("ag", "agent", 450, 520, 340, 70, "ours", sub="LangGraph Agent, tool, skill", size=12)
f.node("core", "core", 450, 620, 340, 56, "ours", sub="DB, Redis, executor·임베딩 클라이언트", size=12)
R = 1040
ys = [("sso", "SSO (IdP)", "infra", 110, "IF-05 HTTP"), ("llm", "LLM 게이트웨이", "infra", 200, "IF-06 HTTP"),
      ("emb", "임베딩 게이트웨이", "infra", 290, "IF-07 HTTP"), ("exe", "executor", "related", 380, "IF-08 REST"),
      ("bat", "batch", "related", 470, "IF-09 REST"), ("phx", "Phoenix", "infra", 560, "IF-10 추적")]
for nid, t, k, y, lab in ys:
    f.node(nid, t, R, y, 220, 54, k)
    f.edge("svc", nid, lab, ex=("r", (y + 27 - 80) / 620), en=("l", .5))
f.node("pg", "PostgreSQL", 420, 770, 160, 70, "store", shape="cyl")
f.node("rd", "Redis", 600, 770, 160, 70, "store", shape="cyl")
f.node("pv", "공유 저장소 (PV)", 1040, 770, 220, 70, "store", shape="cyl")
f.edge("br", "api", "IF-01 REST, IF-02 SSE", ex=("r", .5), en=("l", .2), both=True)
f.edge("ext", "api", "IF-04 REST (API 키)", ex=("r", .5), en=("l", .8))
f.edge("gaia", "gb", "IF-03 workflow", ex=("r", .5), en=("l", .5))
f.edge("svc", "pg", "IF-11 SQL", ex=("b", .2), en=("t", .5), both=True)
f.edge("svc", "rd", "IF-12", ex=("b", .65), en=("t", .5), both=True)
f.edge("svc", "pv", "IF-14 파일", ex=("b", .925), en=("l", .5), via=[(790, 805)], both=True, t=.6)
f.edge("exe", "pv", "", ex=("r", .75), en=("r", .5), via=[(1330, 420.5), (1330, 805)], both=True)
f.edge("exe", "rd", "IF-13 실행 이벤트 (Redis 스트림)", ex=("r", .3), en=("b", .5),
       via=[(1390, 396.2), (1390, 870), (680, 870)], dashed=True, t=.75)
f.text("n", "실선은 요청 방향입니다. 양쪽 화살표는 읽기와 쓰기를 모두 합니다. 점선은 executor가 쓰고 우리가 읽는 이벤트입니다.", 40, 885, 1300, 20)

write([s, f], "09-ops-sw-interface", OUT)
