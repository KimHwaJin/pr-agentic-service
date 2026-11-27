const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/mnt/skills/public/pptx/scripts/apply_theme.js");
const D = "../";
const DG = "../diagrams/export/";
const OUT = process.argv[2] || "08-operator-manual.pptx";

const THEME = {
  name: "OpsManual",
  headFontFace: "맑은 고딕",
  bodyFontFace: "맑은 고딕",
  colors: {
    dk1: "1F2933", lt1: "FFFFFF", dk2: "12343B", lt2: "F3F6F7",
    accent1: "0F766E", accent2: "B45309", accent3: "475569",
    accent4: "B91C1C", accent5: "D9E8E6", accent6: "CBD5E1",
    hlink: "0F766E", folHlink: "475569",
  },
};
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "gaia-api-service 운영자 메뉴얼";
const C = pres.SchemeColor;
const W = 13.33, MX = 0.5, CW = W - 2 * MX;
const FOOT = "gaia-api-service 운영자 메뉴얼";

pres.defineSlideMaster({
  title: "COVER", background: { color: THEME.colors.dk2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.9, y: 2.3, w: 11.5, h: 1.3, fontSize: 40, bold: true, color: THEME.colors.lt1, align: "left", valign: "bottom" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.9, y: 3.8, w: 11.5, h: 1.6, fontSize: 16, color: THEME.colors.accent5, align: "left", valign: "top" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SECTION", background: { color: THEME.colors.dk2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.9, y: 2.6, w: 11.5, h: 1.1, fontSize: 36, bold: true, color: THEME.colors.lt1, align: "left", valign: "bottom" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.9, y: 3.85, w: 11.5, h: 2.2, fontSize: 16, color: THEME.colors.accent5, align: "left", valign: "top" }, text: "" } },
  ],
  slideNumber: { x: 12.2, y: 6.95, w: 0.7, h: 0.3, fontSize: 10, color: THEME.colors.accent5, align: "right" },
});
pres.defineSlideMaster({
  title: "CONTENT", background: { color: THEME.colors.lt1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: CW, h: 0.7, fontSize: 24, bold: true, color: THEME.colors.dk2, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { text: { text: FOOT, options: { x: MX, y: 6.98, w: 6, h: 0.3, fontSize: 10, color: THEME.colors.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.13, y: 6.98, w: 0.7, h: 0.3, fontSize: 10, color: THEME.colors.accent3, align: "right" },
});

let SEC = "";
let n = 0;
const Y0 = 1.25; // content top
const H0 = 5.55; // content height (to 6.8)

function section(title, lines) {
  SEC = title;
  pres.addSection({ title });
  const s = pres.addSlide({ masterName: "SECTION", sectionTitle: SEC });
  s.addText(title, { placeholder: "title" });
  s.addText(lines.map((t, i) => ({ text: t, options: { breakLine: i < lines.length - 1 } })), { placeholder: "body" });
}
function slide(title) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: SEC });
  s.addText(title, { placeholder: "title" });
  n++;
  return s;
}
function lead(s, text, y = Y0, h = 0.5) {
  s.addText(text, { x: MX, y, w: CW, h, fontSize: 14, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: "lead" });
}
function table(s, head, rows, colW, o = {}) {
  const fs = o.fontSize || 13;
  const cell = (t, opt) => ({ text: String(t), options: Object.assign({ fontSize: fs, color: C.text1, valign: "middle", margin: [3, 6, 3, 6] }, opt) });
  const data = [head.map(h => cell(h, { bold: true, color: C.background1, fill: { color: C.text2 } }))];
  rows.forEach((r, i) => data.push(r.map((t, j) => cell(t, {
    fill: { color: i % 2 ? C.background2 : C.background1 },
    bold: j === 0 && o.boldFirst !== false,
    fontFace: (o.mono || []).includes(j) ? "Courier New" : undefined,
  }))));
  const total = colW.reduce((a, b) => a + b, 0);
  s.addTable(data, {
    x: o.x ?? MX, y: o.y ?? Y0, w: total, colW,
    border: { type: "solid", pt: 0.75, color: THEME.colors.accent6 },
    objectName: o.name || "table",
  });
}
function bullets(s, items, o = {}) {
  s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })), {
    x: o.x ?? MX, y: o.y ?? Y0, w: o.w ?? CW, h: o.h ?? 2, fontSize: o.fontSize || 14, color: C.text1,
    paraSpaceAfter: 6, valign: "top", margin: 0, isTextBox: true, objectName: o.name || "bullets",
  });
}
function image(s, path, pxW, pxH, o = {}) {
  const bx = o.x ?? MX, by = o.y ?? Y0, bw = o.w ?? CW, bh = o.h ?? H0;
  const r = Math.min(bw / pxW, bh / pxH);
  const w = pxW * r, h = pxH * r;
  s.addImage({ path, x: bx + (o.left ? 0 : (bw - w) / 2), y: by, w, h, altText: o.alt || "그림", objectName: o.name || "picture" });
}
function card(s, x, y, w, h, title, body, o = {}) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: o.fill || C.background2 }, line: { color: THEME.colors.accent6, width: 0.75 }, objectName: "card" });
  s.addText(title, { x: x + 0.2, y: y + 0.15, w: w - 0.4, h: 0.4, fontSize: 14, bold: true, color: o.titleColor || C.accent1, margin: 0, isTextBox: true, objectName: "card title" });
  s.addText(body, { x: x + 0.2, y: y + 0.6, w: w - 0.4, h: h - 0.75, fontSize: o.fontSize || 12, color: C.text1, margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 4, objectName: "card body" });
}
function steps(s, items, o = {}) {
  // numbered step chips in a row
  const y = o.y ?? Y0, h = o.h ?? 1.5, gap = 0.2;
  const w = (CW - gap * (items.length - 1)) / items.length;
  items.forEach(([t, d], i) => {
    const x = MX + i * (w + gap);
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: THEME.colors.accent6, width: 0.75 }, objectName: "step" });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.15, y: y + 0.15, w: 0.42, h: 0.42, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: "step no bg" });
    s.addText(String(i + 1), { x: x + 0.15, y: y + 0.15, w: 0.42, h: 0.42, fontSize: 13, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "step no" });
    s.addText(t, { x: x + 0.65, y: y + 0.13, w: w - 0.75, h: 0.46, fontSize: 13, bold: true, color: C.text2, margin: 0, valign: "middle", isTextBox: true, objectName: "step title" });
    s.addText(d, { x: x + 0.15, y: y + 0.68, w: w - 0.3, h: h - 0.78, fontSize: o.fontSize || 12, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: "step body" });
  });
}
function code(s, text, o = {}) {
  s.addShape(pres.ShapeType.rect, { x: o.x ?? MX, y: o.y ?? Y0, w: o.w ?? CW, h: o.h ?? 2, fill: { color: C.background2 }, line: { color: THEME.colors.accent6, width: 0.75 }, objectName: "code bg" });
  s.addText(text, { x: (o.x ?? MX) + 0.15, y: (o.y ?? Y0) + 0.1, w: (o.w ?? CW) - 0.3, h: (o.h ?? 2) - 0.2, fontFace: "Courier New", fontSize: o.fontSize || 11, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: "code" });
}
function note(s, text, y = 6.35) {
  s.addText(text, { x: MX, y, w: CW, h: 0.45, fontSize: 11, color: C.accent3, margin: 0, valign: "top", isTextBox: true, objectName: "note" });
}

// ================= 표지, 개정 이력, 목차
{
  pres.addSection({ title: "표지" });
  SEC = "표지";
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: SEC });
  s.addText("gaia-api-service 운영자 메뉴얼", { placeholder: "title" });
  s.addText([
    { text: "사내 데이터 분석 Agent 서비스", options: { breakLine: true } },
    { text: "초안 v0.2", options: {} },
  ], { placeholder: "body" });

  let t = slide("개정 이력");
  table(t, ["버전", "일자", "내용", "작성", "검토"], [
    ["0.1", "2026-11-26", "초안 작성", "", ""],
    ["0.2", "2026-11-27", "브랜치 기준을 master, stg, prd로 변경. 5.2 패치방법과 마이그레이션 설명 갱신", "", ""],
    ["", "", "", "", ""],
  ], [1.2, 1.8, 6.33, 1.5, 1.5], { boldFirst: false });
  bullets(t, [
    "주소, 계정, 키 같은 환경별 실제 값은 적지 않고 서비스 이름과 설정 키 이름으로 가리킵니다. 실제 값은 config.{dev,stg,prd}.yml에 있습니다.",
    "소스 경로는 src/dtest/ 아래입니다. 기준 브랜치는 master(dev 배포), stg, prd입니다.",
    "4.3 담당자 연락처, 3.5와 3.8의 사내 플랫폼 관련 칸은 비워 두었습니다.",
  ], { y: 3.4, h: 2 });

  t = slide("목차");
  const toc = [
    ["1. 개요", ["1.1 문서 개요", "1.2 서비스 개요"]],
    ["2. 시스템 구성 정보", ["2.1 S/W 구성도", "2.2 Application 구성도"]],
    ["3. 서비스 관리", ["3.1 인터페이스 흐름도", "3.2 서버 디렉토리 구조", "3.3 서비스 목록", "3.4 서비스 환경설정값 정보", "3.5 서비스 시작/종료 방법", "3.6 서비스 정상 여부 점검", "3.7 로그 확인", "3.8 관제 정보", "3.9 운영 업무", "3.10 관리자 화면"]],
    ["4. 장애처리", ["4.1 장애처리 절차", "4.2 장애 유형별 조치", "4.3 담당자 연락처", "4.4 운영 시 주의사항"]],
    ["5. 유지보수 가이드", ["5.1 개발 환경 setting 정보", "5.2 패치방법 (App Server)", "부록 A. 자주 쓰는 SQL", "부록 B. 운영 스크립트"]],
  ];
  const cw = (CW - 0.2 * 4) / 5;
  toc.forEach(([h, items], i) => {
    const x = MX + i * (cw + 0.2);
    t.addShape(pres.ShapeType.roundRect, { x, y: Y0, w: cw, h: 5.3, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: THEME.colors.accent6, width: 0.75 }, objectName: "toc card" });
    t.addText(h, { x: x + 0.18, y: Y0 + 0.15, w: cw - 0.36, h: 0.5, fontSize: 15, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "toc head" });
    t.addText(items.map((it, k) => ({ text: it, options: { breakLine: k < items.length - 1 } })), { x: x + 0.18, y: Y0 + 0.75, w: cw - 0.36, h: 4.4, fontSize: 12, color: C.text1, margin: 0, valign: "top", paraSpaceAfter: 7, isTextBox: true, objectName: "toc items" });
  });
}

// ================= 1. 개요
section("1. 개요", ["1.1 문서 개요", "1.2 서비스 개요"]);
{
  let s = slide("1.1 문서 개요");
  const w = (CW - 0.3 * 2) / 3;
  card(s, MX, Y0, w, 2.4, "목적", "gaia-api-service를 운영하는 담당자가 서비스 구성, 일상 점검, 장애 대응, 패치 방법을 이 문서만으로 수행할 수 있게 합니다.");
  card(s, MX + w + 0.3, Y0, w, 2.4, "대상", "서비스 운영 담당자, 장애 1차 대응자, 유지보수 개발자.\n웹 화면 사용법은 사용자 메뉴얼을 봅니다.");
  card(s, MX + 2 * (w + 0.3), Y0, w, 2.4, "범위", "gaia-api-service 자체의 운영.\n컨테이너 배치, 자동 확장, 앞단 라우팅 같은 실행 인프라는 사내 플랫폼이 맡으므로 서비스가 기대하는 조건만 적습니다.");
  table(s, ["용어", "뜻"], [
    ["인스턴스", "서비스 프로세스 하나(uvicorn worker 1개). 그 안에서 API와 백그라운드 작업(worker)이 함께 동작"],
    ["run", "사용자 메시지 하나를 Agent가 처리하는 작업 단위. queued, running, waiting_input, waiting_executor, succeeded, failed, cancelled"],
    ["executor", "분석 코드를 Jupyter 런타임에서 실행하는 연관 서비스"],
    ["tenant", "executor와 batch가 호출자를 구분하는 단위. 우리 서비스는 EXECUTOR_TENANT_ID"],
    ["lease", "인스턴스가 run을 실행할 권한. 60초이고 20초마다 갱신"],
  ], [2.0, 10.33], { y: 3.95 });

  s = slide("1.2 서비스 개요");
  lead(s, "gaia-api-service는 사내 데이터 분석 Agent의 채팅 API이자 Agent 실행 서비스입니다. 사용자가 보낸 메시지를 Agent가 처리하고, 분석 코드는 직접 실행하지 않고 executor에 보내 실행합니다.", Y0, 0.8);
  table(s, ["환경", "APP_ENV", "설정 파일", "SSO"], [
    ["로컬", "비움", "config.yml + 환경변수", "dev 어댑터(가짜 로그인) 가능"],
    ["dev", "dev", "config.yml + config.dev.yml", "idp"],
    ["stg", "stg", "config.yml + config.stg.yml", "idp"],
    ["prd", "prd", "config.yml + config.prd.yml", "idp"],
  ], [1.4, 1.4, 3.3, 3.0], { y: 2.2, x: MX });
  table(s, ["자원", "현황 (2026-11-22 기준)"], [
    ["PostgreSQL", "사내 서비스형 DB. 연결 한도 150. dev와 prd가 같은 서버를 쓰고 데이터베이스 이름으로 나뉨. 서버 분리 예정"],
    ["Redis", "dev와 prd 분리. 환경에 따라 standalone 또는 Sentinel"],
    ["로그", "키바나에서 조회. 보관 기간은 사내 정책"],
    ["지표 대시보드", "없음. 헬스체크, 로그, DB 조회로 확인"],
    ["설정과 키", "config.{env}.yml에 적어 깃랩에 올리고 배포"],
  ], [2.0, 10.33], { y: 4.3 });
}

// ================= 2. 시스템 구성 정보
section("2. 시스템 구성 정보", ["2.1 S/W 구성도", "2.2 Application 구성도"]);
{
  let s = slide("2.1 S/W 구성도");
  image(s, DG + "09-ops-sw-interface-1.png", 2250, 1200, { alt: "S/W 구성도: 사용자, Application, 데이터, 연관 시스템 계층" });

  s = slide("2.1 S/W 구성도: 소프트웨어 목록");
  table(s, ["구분", "소프트웨어", "버전", "용도"], [
    ["언어, 실행", "Python, uv", "3.11 (3.12 미만)", "내부망 표준 이미지. 3.12 전용 문법 사용 금지"],
    ["웹 서버", "uvicorn, gaia 템플릿, HCP", "uvicorn 0.54 이상", "python app.py 로 기동. worker 1개"],
    ["웹 프레임워크", "FastAPI", "0.115 이상 0.137 미만", "API, SSE. 0.137부터 gaia 계측기와 충돌"],
    ["Agent", "LangGraph, LangChain, langchain-openai", "1.2, 1.4, 1.7 이상", "Agent 그래프와 모델 호출"],
    ["체크포인트", "langgraph-checkpoint-postgres", "3.1.3 고정", "대화 상태 저장. 버전을 올리기 전 테스트 확인"],
    ["DB 접근", "SQLAlchemy(async), psycopg, Alembic", "2.1, 3.3, 1.20 이상", "앱 테이블과 마이그레이션"],
    ["DB", "PostgreSQL + pgvector", "사내 서비스형 DB", "앱 데이터, 체크포인트, 워크플로우 벡터"],
    ["캐시, 메시지", "Redis (redis-py 7)", "6.2 이상", "로그인 세션, 실시간 이벤트, executor 이벤트 스트림"],
    ["추적 (선택)", "Phoenix", "", "Agent 실행 추적"],
  ], [1.8, 3.9, 2.4, 4.23]);
  note(s, "버전은 pyproject.toml과 uv.lock 기준입니다. 의존성을 바꾸면 uv lock으로 uv.lock을 갱신합니다.");

  s = slide("2.2 Application 구성도");
  image(s, D + "diagrams/export/01-system-architecture-1.png", 2340, 1470, { alt: "Application 논리 구성도" });

  s = slide("2.2 Application 구성도: 구성 요소");
  table(s, ["구성 요소", "위치", "역할"], [
    ["api_service", "src/dtest/api_service", "FastAPI 라우터, 인증(SSO, API 키), 채팅 API, SSE 이벤트, executor·배치 게이트웨이, 웹 화면 제공"],
    ["worker", "src/dtest/worker", "run 스케줄러, executor 이벤트 수신, 배치 리포트, 프로젝트 메모리 추출, 보존 정리"],
    ["agent", "src/dtest/agent", "LangGraph Agent 그래프, middleware, tool, 프롬프트"],
    ["gaia_bridge", "src/dtest/gaia_bridge", "gaia workflow dtest.analyst. gaia 메시지 하나를 우리 run 하나로 실행"],
    ["core", "src/dtest/core", "설정, DB, Redis, executor·임베딩 클라이언트, 모델 정의, 워크플로우 검색"],
    ["assets, catalogs", "src/dtest/assets, catalogs", "skill(.md), tool(.py), knowledge(.md). 코드와 함께 배포"],
    ["web", "src/dtest/web", "웹 화면 정적 파일"],
  ], [1.9, 2.9, 7.53], { mono: [1] });
  bullets(s, [
    "인스턴스 하나에서 API와 worker가 함께 돕니다(RUN_MODE=all). 같은 인스턴스를 여러 개 띄워 부하를 나눕니다.",
    "run은 PostgreSQL의 큐로 인스턴스 사이에 나뉘고, 인스턴스가 죽으면 다른 인스턴스가 체크포인트에서 이어 갑니다.",
  ], { y: 5.35, h: 1.2, fontSize: 13 });

  s = slide("2.2 Application 구성도: 환경과 배포");
  image(s, D + "diagrams/export/01-system-architecture-2.png", 2460, 1350, { alt: "환경·배포 구성도" });
}

// ================= 3. 서비스 관리
section("3. 서비스 관리", ["3.1 인터페이스 흐름도 · 3.2 서버 디렉토리 구조 · 3.3 서비스 목록", "3.4 서비스 환경설정값 정보 · 3.5 서비스 시작/종료 방법", "3.6 서비스 정상 여부 점검 · 3.7 로그 확인 · 3.8 관제 정보", "3.9 운영 업무 · 3.10 관리자 화면"]);
{
  let s = slide("3.1 인터페이스 흐름도");
  image(s, DG + "09-ops-sw-interface-2.png", 2250, 1365, { alt: "인터페이스 흐름도" });

  s = slide("3.1 인터페이스 목록 (들어오는 호출)");
  table(s, ["ID", "보내는 쪽", "받는 쪽", "방식", "내용", "인증"], [
    ["IF-01", "웹 브라우저", "api_service", "HTTPS REST", "/api/v1/... 채팅, 프로젝트, 워크플로우, 배치, 관리", "SSO 로그인 쿠키, CSRF 토큰"],
    ["IF-02", "api_service", "웹 브라우저", "SSE", "GET /api/v1/sessions/{id}/events 실시간 이벤트. 15초마다 유지 신호", "SSO 로그인 쿠키"],
    ["IF-03", "gaia 채팅 화면", "gaia_bridge", "gaia workflow", "workflow dtest.analyst 호출", "gaia 접근 키"],
    ["IF-04", "다른 서비스, 에이전트", "api_service", "HTTPS REST", "/api/v1/executor/..., /api/v1/batch/... 게이트웨이", "X-Api-Key, X-User-Id"],
  ], [0.8, 1.9, 1.5, 1.4, 4.63, 2.1], { fontSize: 12 });
  bullets(s, [
    "모든 응답에 X-Request-ID 헤더가 붙습니다. 같은 값이 로그와 executor로 보내는 호출에 남습니다.",
    "요청 본문은 32MB(REQUEST_MAX_BYTES)까지 받습니다. 넘으면 413으로 답합니다.",
    "executor와 batch는 우리 서비스를 거쳐서만 부를 수 있습니다.",
  ], { y: 4.6, h: 1.8, fontSize: 13 });

  s = slide("3.1 인터페이스 목록 (나가는 호출)");
  table(s, ["ID", "대상", "방식", "용도", "끊기면"], [
    ["IF-05", "SSO (IdP)", "HTTP", "로그인 확인, 사용자 정보", "새 로그인 불가. 이미 로그인한 사용자는 계속 사용"],
    ["IF-06", "LLM 게이트웨이", "HTTP (OpenAI 호환)", "모델 호출", "run이 failed로 끝남. 그 외 화면은 정상"],
    ["IF-07", "임베딩 게이트웨이", "HTTP", "워크플로우 검색", "워크플로우 추천만 안 됨"],
    ["IF-08", "executor", "REST (EXECUTOR_API_KEY)", "분석 코드 실행, 노트북, 결과물", "분석 요청 실패, 결과물 조회 502. 일반 대화는 정상"],
    ["IF-09", "batch", "REST (BATCH_API_KEY)", "배치 등록과 조회 중계", "배치 화면만 502"],
    ["IF-10", "Phoenix", "추적 전송 (선택)", "Agent 실행 추적", "영향 없음"],
    ["IF-11", "PostgreSQL", "SQL", "앱 데이터, run 큐, 체크포인트, 벡터", "모든 요청 실패. run 실행 중단"],
    ["IF-12", "Redis", "명령, pub/sub", "로그인 세션, 실시간 이벤트 전달", "로그인 확인 실패로 모든 요청 실패"],
    ["IF-13", "Redis 스트림", "XREADGROUP", "executor가 쓴 실행 이벤트 수신 (executor.events.{tenant})", "복구 절차가 대신 가져옴. 단계마다 2분 이상 지연"],
    ["IF-14", "공유 저장소 (PV)", "파일", "executor와 코드·결과 파일 주고받기", "분석 코드 제출과 결과 읽기 실패"],
  ], [0.8, 2.0, 2.4, 3.5, 3.63], { fontSize: 12 });

  s = slide("3.1 요청 처리 흐름: 분석 한 턴");
  image(s, D + "diagrams/export/03-agent-graph-3.png", 2250, 1568, { w: 7.9, left: true, alt: "분석 한 턴의 시퀀스" });
  bullets(s, [
    "메시지는 run으로 등록되어 큐에 들어가고, 인스턴스의 스케줄러가 가져가 Agent를 실행합니다.",
    "사용자 확인이 필요하면 waiting_input으로 멈추고, 답이 오면 이어서 실행합니다.",
    "분석 코드는 executor에 제출하고 waiting_executor로 멈춥니다. 완료 이벤트가 Redis 스트림으로 오면 이어 갑니다.",
    "기다리는 동안에는 인스턴스 자원을 잡지 않습니다.",
    "진행 상황은 SSE로 화면에 전달됩니다.",
  ], { x: 8.7, w: 4.13, h: 5.3, fontSize: 13 });

  s = slide("3.2 서버 디렉토리 구조");
  code(s, [
    "/app                      컨테이너 작업 폴더 (UID 1000)",
    "├─ app.py                 gaia 템플릿 진입점",
    "├─ config.yml             공통 설정",
    "├─ config.{dev,stg,prd}.yml  환경별 설정",
    "├─ config.example.yml     설정 키 설명용",
    "├─ logger.yml             로그 설정",
    "├─ pyproject.toml, uv.lock",
    "├─ .venv/                 설치된 의존성",
    "└─ src/",
    "   └─ dtest/              이 서비스의 코드",
    "      ├─ api_service/     API, 인증, SSE",
    "      ├─ worker/          백그라운드 루프",
    "      ├─ agent/           그래프, prompts/, tools/",
    "      ├─ gaia_bridge/     gaia workflow",
    "      ├─ core/            설정, DB, Redis, 클라이언트",
    "      ├─ assets/          skills/, tools/, knowledge/",
    "      ├─ catalogs/        추가 카탈로그",
    "      ├─ migrations/      Alembic 마이그레이션",
    "      └─ web/             웹 화면 정적 파일",
    "",
    "/mnt/data                 공유 저장소 (executor와 공용)",
  ].join("\n"), { w: 6.6, h: 5.5, fontSize: 12 });
  table(s, ["경로", "설명"], [
    ["/app", "이미지에 들어 있는 코드와 설정. 실행 중에 바뀌지 않음"],
    ["config*.yml", "APP_ENV 값에 따라 읽을 파일이 정해짐 (3.4)"],
    ["src/dtest/assets", "skill, tool, knowledge. 바꾸려면 다시 배포"],
    ["/mnt/data", "STORAGE_ROOT가 이 아래를 가리킴. 분석 코드를 쓰고 결과를 읽음"],
    ["로그 파일", "컨테이너 표준 출력으로 내보내고 키바나에서 조회 (3.7)"],
  ], [1.9, 3.63], { x: 7.3, fontSize: 12 });
  s.addText("scripts/ 폴더(migrate.py, set_user_role.py 등)는 이미지에 들어가지 않습니다. 운영 스크립트는 배포할 버전의 레포에서 같은 설정으로 실행합니다.", { x: 7.3, y: 5.4, w: 5.53, h: 1.2, fontSize: 12, color: C.accent2, margin: 0, valign: "top", isTextBox: true, objectName: "caution" });

  s = slide("3.3 서비스 목록: 프로세스와 주요 경로");
  table(s, ["항목", "내용"], [
    ["서비스 이름", "gaia-api-service (컨테이너 이미지 하나, 인스턴스 N개)"],
    ["실행 명령", "python app.py. gaia 템플릿이 uvicorn worker 1개를 띄움"],
    ["포트", "5000. 사내 정책상 앱서버는 모두 5000번으로 뜸 (PORT 설정)"],
    ["실행 방식", "RUN_MODE=all (API + worker). api, worker로 나눠 띄울 수도 있음"],
    ["실행 계정", "UID 1000, GID 1000. executor와 같아야 공유 저장소를 같이 읽고 씀"],
    ["자원", "인스턴스 하나가 CPU 약 1코어 사용. 배포 예시의 메모리 한도 2Gi"],
  ], [2.2, 10.13]);
  table(s, ["경로", "용도"], [
    ["/api/v1/...", "채팅, 프로젝트, 워크플로우, 관리 API"],
    ["/api/v1/executor/..., /api/v1/batch/...", "executor·배치 게이트웨이"],
    ["/api/v1/healthz", "생존 확인. 백그라운드 루프가 죽으면 503"],
    ["/api/admin/appReady", "준비 확인 (gaia 제공)"],
    ["/dev/", "웹 화면"],
  ], [4.6, 7.73], { y: 4.25, mono: [0] });

  s = slide("3.3 서비스 목록: 백그라운드 루프");
  lead(s, "인스턴스 안에서 도는 작업입니다. /healthz의 stopped와 로그에 아래 이름으로 나옵니다. 하나라도 죽으면 /healthz가 503이 되고 인스턴스가 재시작됩니다.", Y0, 0.75);
  table(s, ["이름", "하는 일", "주기"], [
    ["run-scheduler", "run을 가져와 Agent 실행", "Redis 신호 즉시, 5초 폴링 보조"],
    ["executor-events", "executor 이벤트 스트림 소비", "상시"],
    ["missed-executor-events", "놓친 executor 이벤트 복구", "60초"],
    ["batch-reports-0 ~ 3", "배치 리포트 작성", "상시"],
    ["batch-report-recovery", "리포트 작업이 빠진 배치 실행 찾기", "10분"],
    ["retention", "보존 기간 지난 데이터 정리", "1시간"],
    ["batch-disable-retry", "비활성 사용자·폐기 tenant의 배치 끄기 재시도", "주기적"],
    ["executor-cancel-retry", "executor 실행 취소 재시도", "주기적"],
    ["memory-worker", "프로젝트 메모리 정리", "대화가 3분 조용하거나 5턴 쌓이면"],
  ], [3.2, 5.4, 3.73], { y: 2.1, mono: [0] });

  s = slide("3.4 서비스 환경설정값: 읽는 순서");
  steps(s, [
    ["환경변수", "가장 우선. 한 값만 바꿀 때 같은 이름으로 넣음"],
    [".env", "로컬 실행용"],
    ["config.{APP_ENV}.yml", "환경마다 다른 값. DB, Redis, 주소, 키, 모델 목록"],
    ["config.yml", "모든 환경 공통값. 모든 키가 기본값과 함께 있음"],
  ], { h: 1.6 });
  bullets(s, [
    "config.example.yml은 서비스가 읽지 않는 설명용 파일입니다. 모든 키의 의미와 예시가 있어 키의 뜻을 찾을 때 봅니다.",
    "설정 파일은 모두 빌드 결과물에 들어가고, 환경변수 APP_ENV 값이 어느 파일을 쓸지 정합니다.",
    "사내 폐쇄망 정책에 따라 키 값(EXECUTOR_API_KEY, BATCH_API_KEY, LLM_API_KEY, DB와 Redis 비밀번호)도 config.{APP_ENV}.yml에 적어 깃랩에 올리고 배포합니다.",
    "설정을 바꾸는 것은 곧 배포입니다. 실행 중인 인스턴스는 설정 파일을 다시 읽지 않습니다.",
    "설정에 <...> 모양의 자리 표시가 남아 있으면 기동을 거부합니다. 빠뜨린 키를 이 검사가 알려 줍니다.",
  ], { y: 3.15, h: 3.5, fontSize: 13 });

  const keys1 = [
    ["실행", "APP_ENV", "(없음)", "dev, stg, prd. 설정 파일 선택"],
    ["실행", "RUN_MODE", "all", "all, api, worker"],
    ["DB", "DATABASE_URL", "", "PostgreSQL 주소"],
    ["DB", "DB_POOL_SIZE", "3", "앱 풀 크기(같은 수만큼 overflow)"],
    ["DB", "CHECKPOINT_POOL_SIZE", "8", "그래프 풀 크기"],
    ["DB", "DB_KEEPALIVE_IDLE_SECONDS", "60", "TCP keepalive 시작 시간"],
    ["DB", "AUTO_MIGRATE", "true", "기동 시 마이그레이션 자동 실행"],
    ["Redis", "REDIS_MODE", "standalone", "standalone, sentinel"],
    ["Redis", "REDIS_URL / REDIS_SENTINEL_*", "", "접속 정보"],
    ["인증", "SSO_ADAPTER", "idp", "idp, dev(로컬 전용)"],
    ["인증", "PUBLIC_API_ORIGIN, FRONTEND_ORIGIN", "", "브라우저가 보는 API 주소, 프론트 주소"],
    ["인증", "SSO_ALLOWED_ORIGINS, CORS_ORIGINS", "", "SSO 로그인 origin 허용 목록, 다른 도메인 프론트"],
    ["인증", "COOKIE_SECURE", "", "https면 true (stg·prd 필수)"],
    ["인증", "SESSION_TTL_SECONDS / SESSION_MAX_SECONDS", "1800 / 43200", "무활동 로그아웃, 로그인 최대 유지"],
    ["인증", "ADMIN_EMPLOYEE_IDS", "", "첫 로그인 때 관리자가 될 사번"],
  ];
  const keys2 = [
    ["LLM", "LLM_BASE_URL, LLM_API_KEY", "", "LLM 게이트웨이"],
    ["LLM", "MODELS", "", "사용자에게 보일 모델 목록. default는 정확히 하나"],
    ["LLM", "LLM_TIMEOUT_SECONDS / AGENT_MODEL_CALL_LIMIT", "120 / 40", "호출 시간 제한, 턴당 모델 호출 상한"],
    ["executor", "EXECUTOR_BASE_URL, EXECUTOR_API_KEY", "", "executor 주소와 우리 키"],
    ["executor", "EXECUTOR_ADMIN_API_KEY", "", "시스템 화면용 운영 키. 비면 그 화면만 503"],
    ["executor", "EXECUTOR_TENANT_ID", "dtest-agent-service", "우리 tenant"],
    ["executor", "EXECUTOR_OPERATION_WAIT_SECONDS", "1800", "실행 단계 대기 한도"],
    ["executor", "STORAGE_ROOT, STORAGE_EXECUTOR_PATH, EXECUTOR_RESULT_ROOT", "", "공유 저장소 경로"],
    ["batch", "BATCH_BASE_URL, BATCH_API_KEY", "", "batch 주소와 우리 키"],
    ["부하", "RUN_CONCURRENCY / RUN_USER_CONCURRENCY", "16 / 4", "인스턴스당, 사용자당 동시 턴"],
    ["부하", "RUN_LEASE_SECONDS / RUN_MAX_ATTEMPTS", "60 / 5", "실행 권한 유지 시간, 반복 실행 상한"],
    ["부하", "BATCH_REPORT_CONCURRENCY", "4", "인스턴스당 동시 리포트"],
    ["요청", "REQUEST_MAX_BYTES", "33554432", "요청 본문 한도(32MB)"],
    ["보존", "RUN_EVENT_RETENTION_DAYS / EXECUTOR_INBOX_RETENTION_DAYS", "30 / 7", "이벤트 보존 기간"],
    ["기타", "DOCS_ENABLED, PHOENIX_ENDPOINT", "false, (없음)", "API 문서 노출, Phoenix 추적"],
  ];
  s = slide("3.4 서비스 환경설정값: 주요 키 (1/2)");
  table(s, ["분류", "키", "기본값", "뜻"], keys1, [1.1, 4.7, 1.9, 4.63], { fontSize: 12, mono: [1] });
  s = slide("3.4 서비스 환경설정값: 주요 키 (2/2)");
  table(s, ["분류", "키", "기본값", "뜻"], keys2, [1.1, 5.4, 1.9, 3.93], { fontSize: 12, mono: [1] });

  s = slide("3.4 서비스 환경설정값: Redis 접속 방식");
  lead(s, "접속 방식은 REDIS_MODE로 고르고 그 환경의 Redis 구성과 맞아야 합니다. 어느 방식이든 그 환경의 executor가 쓰는 Redis와 같은 서버, 같은 DB 번호여야 합니다.", Y0, 0.75);
  table(s, ["", "standalone", "Sentinel"], [
    ["REDIS_MODE", "standalone (기본값)", "sentinel"],
    ["읽는 설정", "REDIS_URL", "REDIS_SENTINEL_HOST, _PORT, _MASTER_NAME, _USERNAME, _AUTH"],
    ["접속 대상", "REDIS_URL의 주소. DB 번호는 URL 끝의 숫자", "Sentinel이 알려 주는 현재 마스터. DB 0번 고정"],
    ["비밀번호", "REDIS_URL 안에 적음", "REDIS_SENTINEL_AUTH에 AES로 암호화한 값. 사내 hcp 라이브러리로 복호화"],
    ["Redis가 죽으면", "살아날 때까지 모든 요청 실패", "레플리카가 마스터가 되면 5~31초 안에 자동 복구. 재시작 불필요"],
    ["기동 검사", "없음", "설정이 비어 있거나 hcp 라이브러리가 없으면 기동 실패"],
    ["접속 확인", "기동 로그, /api/v1/users/me 호출", "scripts/check_redis_sentinel.py"],
  ], [2.0, 4.8, 5.53], { y: 2.1 });
  s.addText("Sentinel 구성의 Redis에 standalone으로 붙지 않습니다. 직접 가리킨 노드가 마스터가 아니게 되는 순간 모든 명령이 READONLY 오류로 실패합니다.", { x: MX, y: 5.9, w: CW, h: 0.7, fontSize: 12, color: C.accent2, margin: 0, valign: "top", isTextBox: true, objectName: "caution" });

  s = slide("3.5 서비스 시작 방법");
  lead(s, "실제 기동과 중지는 사내 플랫폼에서 합니다. 서비스가 실행 환경에 기대하는 조건은 아래와 같습니다.", Y0, 0.45);
  table(s, ["항목", "내용"], [
    ["실행 명령", "python app.py (uvicorn worker 1개. worker 수를 늘리지 않음)"],
    ["환경변수", "APP_ENV = dev, stg, prd 중 하나. 서버 환경에서 비어 있으면 기동 거부"],
    ["준비 확인", "GET /api/admin/appReady. DB, Redis, worker 시작이 끝나야 응답"],
    ["생존 확인", "GET /api/v1/healthz. 503이면 인스턴스를 재시작해야 함"],
    ["공유 저장소", "executor와 같은 저장소를 /mnt/data에 마운트"],
    ["기동 시 동작", "AUTO_MIGRATE가 true이면 마이그레이션, 체크포인트 테이블, 벡터 인덱스를 한 인스턴스만 적용"],
    ["배포 예시", "deploy/kubernetes/deployment.yml (인스턴스 2개, CPU 60% 기준 자동 확장)"],
  ], [2.2, 10.13], { y: 1.8 });
  table(s, ["사내 플랫폼 조작 절차 (작성 필요)", "내용"], [
    ["시작, 재시작 방법", ""],
    ["인스턴스 수 변경 방법", ""],
  ], [4.0, 8.33], { y: 5.3, boldFirst: false });

  s = slide("3.5 서비스 시작: 기동을 거부하는 조건");
  lead(s, "설정이 잘못되면 인스턴스가 시작하지 않고 로그에 ValueError와 이유를 남깁니다. 일부러 넣은 검사입니다.", Y0, 0.45);
  table(s, ["조건", "메시지 요지"], [
    ["APP_ENV가 있는데 config.{APP_ENV}.yml이 없음", "APP_ENV=... needs ..."],
    ["서버 환경인데 APP_ENV가 비어 있음", "APP_ENV is not set for this pod"],
    ["dev·stg·prd에서 SSO_ADAPTER=dev", "SSO_ADAPTER=dev is only allowed locally"],
    ["stg·prd에서 COOKIE_SECURE가 false", "COOKIE_SECURE must be true"],
    ["dev·stg·prd에서 EXECUTOR_API_KEY나 BATCH_API_KEY가 비어 있음", "EXECUTOR_API_KEY and BATCH_API_KEY are required"],
    ["설정에 <...> 모양의 템플릿 값이 남아 있음", "config values still hold a template placeholder: 키 이름"],
    ["SSO_ADAPTER=idp인데 SSO_ALLOWED_ORIGINS가 비어 있음", "SSO_ALLOWED_ORIGINS is empty"],
    ["REDIS_MODE=sentinel인데 Sentinel 값이 비었거나 hcp 라이브러리가 없음", "REDIS_MODE=sentinel needs ... / 복호화 실패"],
    ["stg·prd에서 EXECUTOR_IO_MODE=api", "EXECUTOR_IO_MODE=api is for test environments"],
    ["MODELS에 default가 정확히 하나가 아님, 이름 중복", "models: ..."],
    ["EMBEDDING_PROVIDER=openai인데 주소나 모델이 비어 있음", "EMBEDDING_PROVIDER=openai needs ..."],
  ], [7.0, 5.33], { y: 1.8, fontSize: 12, boldFirst: false });

  s = slide("3.5 서비스 종료 방법");
  lead(s, "인스턴스는 종료 신호(SIGTERM)를 받으면 아래 순서로 정리합니다. 합계 최대 약 45초가 걸리므로 그 전에 강제 종료하지 않아야 합니다.", Y0, 0.75);
  steps(s, [
    ["연결 정리", "uvicorn이 열린 연결을 최대 20초 기다림. SSE 연결이 있으면 끝까지 기다림"],
    ["작업 마무리", "worker가 새 run을 받지 않고, 진행 중인 턴과 메모리 작업을 최대 20초 동안 마무리"],
    ["run 반납", "끝나지 않은 run은 lease를 반납해 queued로 돌림. 다른 인스턴스가 체크포인트에서 이어 감"],
  ], { y: 2.15, h: 1.7, fontSize: 12 });
  bullets(s, [
    "진행 중이던 턴은 잃지 않습니다. 이어 가는 인스턴스가 마지막 체크포인트 이후의 LLM 호출을 다시 하므로 그만큼 시간이 더 걸립니다.",
    "정리가 끝나기 전에 강제 종료되어도 lease가 60초 뒤 만료되어 같은 방식으로 이어 갑니다.",
    "배포 예시는 종료 대기 60초, 종료 전 5초 대기(앞단이 라우팅을 먼저 끊도록)로 되어 있습니다.",
    "executor까지 함께 내릴 때는 시스템 화면의 점검 탭에서 새 실행 접수를 먼저 중지합니다(3.10).",
  ], { y: 4.15, h: 2.4, fontSize: 13 });

  s = slide("3.6 서비스 정상 여부 점검: 배포 후 확인");
  steps(s, [
    ["준비 확인", "GET /api/admin/appReady 가 200"],
    ["생존 확인", "GET /api/v1/healthz 가 {\"status\": \"ok\"}"],
    ["기동 로그", "gaia_auth_skipped_on_own_paths 가 있는지. 없으면 브라우저 요청이 401로 막힘"],
    ["로그인", "브라우저로 로그인해 GET /api/v1/users/me 가 200"],
    ["실제 동작", "대화 한 턴과 분석 한 건을 실행해 답과 리포트가 오는지"],
  ], { h: 1.9, fontSize: 12 });
  table(s, ["확인할 것", "방법", "이상 신호"], [
    ["서비스가 살아 있는지", "GET /api/v1/healthz", "503 (stopped에 죽은 루프 이름)"],
    ["인스턴스가 재시작을 반복하는지", "키바나에서 기동 로그 반복 여부", "10분 안에 2회 이상"],
    ["요청이 밀리는지", "run 상태 분포 SQL (부록 A)", "queued가 5분 넘게 줄지 않음"],
    ["DB 연결이 한도에 가까운지", "pg_stat_activity", "서버 전체 130 이상"],
    ["executor 이벤트가 오는지", "키바나에서 executor_event_recovered", "시간당 여러 건"],
  ], [3.6, 4.6, 4.13], { y: 3.5 });
  note(s, "화면으로는 시스템 탭의 런타임, 이벤트 스트림에서 executor 쪽 상태를 볼 수 있습니다(3.10).", 6.45);

  s = slide("3.6 서비스 정상 여부 점검: 정기 점검");
  table(s, ["주기", "항목", "방법"], [
    ["매일", "오류 수준 로그, 인스턴스 재시작", "키바나"],
    ["매주", "run 실패 비율, queued 적체 여부", "부록 A의 SQL"],
    ["매주", "PostgreSQL 연결 수", "pg_stat_activity"],
    ["매월", "테이블 크기와 autovacuum", "인수인계 문서의 DB 물리 설계서 7장 SQL"],
    ["매월", "보존 정리 동작", "run_events, executor_inbox의 가장 오래된 행"],
    ["매월", "공유 저장소 사용량", "STORAGE_ROOT 아래 크기"],
    ["분기", "쓰지 않는 API 키 폐기, 마스터키 점검", "키 목록의 last_used_at"],
    ["분기", "관리자 목록", "scripts/set_user_role.py --list"],
    ["의존성 변경 시", "고정 버전 확인", "langgraph-checkpoint-postgres 3.1.3, FastAPI 0.137 미만"],
  ], [1.9, 5.0, 5.43]);

  s = slide("3.7 로그 확인");
  bullets(s, [
    "로그는 키바나에서 조회합니다. 보관 기간은 사내 정책을 따릅니다.",
    "내부망에서는 gaia와 HCP 라이브러리가 로깅을 맡고 logger.yml을 읽습니다. 로그 레벨도 그 파일에서 바꿉니다.",
    "각 줄에 요청 ID가 들어갑니다. 백그라운드 작업의 줄에는 run id나 작업 id가 키=값 형태로 들어갑니다.",
    "키와 X-Api-Key 값은 로그에서 ***로 가려집니다.",
  ], { h: 1.9, fontSize: 13 });
  table(s, ["찾는 것", "검색어"], [
    ["요청 하나의 전체 로그", "응답 헤더 X-Request-ID의 값"],
    ["사용자가 본 오류", "화면에 나온 8자리 오류 ID"],
    ["run 하나의 진행", "run_id=<run id>"],
    ["기동 실패", "dtest_startup_failed, ValueError"],
    ["백그라운드 루프 정지", "worker_loops_stopped"],
    ["executor나 batch 무응답", "upstream_unreachable"],
    ["로그인 문제", "sso_"],
    ["executor 이벤트 문제", "executor_event"],
    ["DB 연결 문제", "QueuePool limit, too many connections, run_claim_failed"],
  ], [4.2, 8.13], { y: 3.25, fontSize: 12 });

  s = slide("3.7 로그 확인: 오류 수준 키워드 (바로 볼 것)");
  table(s, ["키워드", "뜻"], [
    ["dtest_startup_failed", "기동 실패. 바로 위 예외가 원인"],
    ["worker_loops_stopped loops=...", "백그라운드 루프가 죽음. /healthz가 503이 되고 인스턴스가 재시작됨"],
    ["run_task_crashed", "턴 실행이 실패 기록도 못 남기고 끝남(대개 DB 장애). lease 만료 뒤 다시 시도됨"],
    ["run_lease_unrenewed", "lease를 40초 동안 갱신하지 못해 턴을 멈춤"],
    ["run_claim_failed", "run 가져오기 실패"],
    ["executor_event_consumer_error, executor_event_failed", "executor 이벤트 처리 실패"],
    ["missed_event_recovery_error", "놓친 이벤트 복구 루프 오류"],
    ["batch_report_worker_error, batch_report_recovery_error", "배치 리포트 처리 오류"],
    ["retention_sweep_failed", "보존 정리 실패. 다음 주기에 재시도"],
    ["memory_extract_failed, memory_claim_failed", "프로젝트 메모리 정리 실패"],
  ], [5.6, 6.73], { mono: [0] });

  s = slide("3.7 로그 확인: 경고 수준 키워드 (반복되면 볼 것)");
  table(s, ["키워드", "뜻"], [
    ["upstream_unreachable path=...", "executor 또는 batch가 응답하지 않아 502를 돌려줌"],
    ["executor_event_recovered", "이벤트를 스트림으로 못 받아 복구 절차로 받음. 자주 보이면 Redis 설정 문제"],
    ["executor_event_group_lost", "Redis 소비자 그룹이 사라져 다시 만듦"],
    ["executor_event_malformed", "형식이 틀린 이벤트를 버림"],
    ["missed_event_lookup_failed", "복구 절차의 executor 조회 실패"],
    ["run_heartbeat_failed, run_lease_lost", "lease 갱신 실패, 다른 인스턴스가 run을 가져감"],
    ["run_model_replaced", "목록에서 빠진 모델 대신 기본 모델로 이어 감"],
    ["batch_disable_failed", "batch에 배치 끄기 요청 실패. 재시도함"],
    ["tool_load_failed", "깨진 tool 파일을 건너뜀"],
    ["sso_...", "로그인 관련 (4.2)"],
    ["admin_employee_ids_empty", "관리자 사번 설정이 비어 있음"],
  ], [5.0, 7.33], { mono: [0], fontSize: 12 });
  note(s, "정상 확인용: gaia_auth_skipped_on_own_paths, phoenix_tracing_on, checkpoints_pruned, code_sources_purged", 6.5);

  s = slide("3.8 관제 정보");
  lead(s, "전용 지표 대시보드는 없습니다. 아래 신호로 관제하고, 기준값은 이 문서에서 제안한 값이므로 운영하면서 조정합니다.", Y0, 0.45);
  table(s, ["관제 항목", "수집 방법", "이상 기준", "조치"], [
    ["서비스 생존", "GET /api/v1/healthz 주기 호출", "503", "실행 환경이 재시작. 반복되면 4.2"],
    ["오류 로그", "키바나에서 오류 수준 키워드 (3.7)", "키워드가 반복해서 나옴", "키워드별 원인 확인"],
    ["인스턴스 재시작", "키바나에서 기동 로그", "10분 안에 2회 이상", "기동 로그의 ValueError 확인"],
    ["요청 적체", "run 상태 분포 SQL", "queued가 5분 넘게 줄지 않음", "인스턴스 수 또는 RUN_CONCURRENCY"],
    ["실패 증가", "최근 실패 run SQL", "평소보다 뚜렷이 많음", "원인 서비스 확인"],
    ["DB 연결", "pg_stat_activity", "서버 전체 130 이상", "연결 예산 재계산 (4.4)"],
    ["보존 정리", "run_events의 가장 오래된 행", "35일보다 오래된 행", "retention 루프 로그 확인"],
  ], [2.0, 3.9, 3.0, 3.43], { y: 1.8, fontSize: 12 });
  table(s, ["사내 관제 연동 (작성 필요)", "내용"], [
    ["관제 시스템 이름, 등록된 점검 항목", ""],
    ["알림 수신 경로와 수신자", ""],
  ], [4.0, 8.33], { y: 5.45, boldFirst: false });

  s = slide("3.8 관제 정보: 부하를 받는 지점과 조정");
  table(s, ["구간", "한계", "포화 신호", "조정"], [
    ["앱 프로세스 CPU", "인스턴스당 1코어", "CPU 100%, 응답 지연 증가", "인스턴스 수 증가"],
    ["LLM 동시 호출", "인스턴스 수 × (16 + 4)", "LLM 응답 지연, 429·5xx, run 실패", "RUN_CONCURRENCY, BATCH_REPORT_CONCURRENCY를 낮춤"],
    ["run 큐", "인스턴스당 동시 16턴", "queued run이 계속 쌓임", "RUN_CONCURRENCY 또는 인스턴스 수 증가"],
    ["executor 실행 제출", "초당 3~7건 (로컬 측정)", "분석 시작이 느려짐", "executor 쪽 조치 필요"],
    ["DB 앱 풀", "인스턴스당 6", "로그에 QueuePool limit", "DB_POOL_SIZE 증가"],
    ["DB 그래프 풀", "인스턴스당 8, 대기 30초", "턴이 풀 대기 시간 초과로 실패", "CHECKPOINT_POOL_SIZE 증가"],
    ["배치 리포트", "인스턴스당 동시 4건", "QUEUED 리포트 작업이 쌓임", "BATCH_REPORT_CONCURRENCY 증가"],
    ["이벤트 테이블", "턴당 수십 행", "run_events 크기 증가", "보존 기간 단축"],
  ], [2.3, 2.7, 3.5, 3.83], { fontSize: 12 });
  s.addText("인스턴스 수나 풀 크기를 올리기 전에 DB 연결 예산을 다시 계산합니다. 인스턴스 하나가 최대 14개 연결을 쓰고 서버 한도는 150입니다(4.4).", { x: MX, y: 5.75, w: CW, h: 0.7, fontSize: 12, color: C.accent2, margin: 0, valign: "top", isTextBox: true, objectName: "caution" });

  s = slide("3.8 관제 정보: Phoenix 추적");
  lead(s, "Agent의 모델 호출, 도구 호출, middleware 단계를 Phoenix로 보냅니다. \"왜 이런 답을 했나\"를 볼 때 씁니다.", Y0, 0.45);
  table(s, ["설정", "내용"], [
    ["PHOENIX_ENDPOINT", "Phoenix 주소. 비어 있으면 꺼짐(기본)"],
    ["PHOENIX_API_KEY", "Phoenix API 키"],
    ["SERVICE_ID", "Phoenix 프로젝트 이름. 기본 pr-agentic-service"],
  ], [3.0, 9.33], { y: 1.8, mono: [0] });
  bullets(s, [
    "켜지면 기동 로그에 phoenix_tracing_on이 나옵니다.",
    "추적의 session.id가 우리 세션 id라 Phoenix의 Sessions 화면에서 대화 단위로 묶여 보입니다.",
    "전송은 백그라운드 배치라 요청 처리 시간에 영향이 없습니다. Phoenix가 죽어도 서비스는 정상입니다.",
  ], { y: 3.7, h: 2, fontSize: 13 });

  s = slide("3.9 운영 업무: 관리자와 사용자");
  const w2 = (CW - 0.3) / 2;
  card(s, MX, Y0, w2, 2.6, "관리자 지정과 역할 변경", [
    { text: "첫 관리자는 ADMIN_EMPLOYEE_IDS에 사번을 넣어 둡니다. 그 사번이 처음 로그인할 때 admin이 됩니다.", options: { breakLine: true } },
    { text: "평소에는 시스템 화면의 사용자 탭에서 바꿉니다.", options: { breakLine: true } },
    { text: "관리자가 아무도 없으면 scripts/set_user_role.py를 씁니다. 마지막 활성 관리자는 강등하지 않습니다.", options: {} },
  ]);
  card(s, MX + w2 + 0.3, Y0, w2, 2.6, "사용자 비활성화", [
    { text: "비활성화하면 로그인과 API 호출이 막히고, 진행 중인 턴과 executor 커널이 바로 취소됩니다.", options: { breakLine: true } },
    { text: "그 사용자의 배치는 batch에서 꺼집니다. 다시 활성화해도 자동으로 켜지지 않습니다.", options: { breakLine: true } },
    { text: "batch가 응답하지 않으면 성공할 때까지 다시 시도합니다(batch_disable_failed 경고).", options: {} },
  ]);
  code(s, [
    "python scripts/set_user_role.py --env prd --list                  # 관리자 목록",
    "python scripts/set_user_role.py --env prd <사번> admin --dry-run   # 확인만",
    "python scripts/set_user_role.py --env prd <사번> admin             # 승격 (강등은 user)",
  ].join("\n"), { y: 4.15, h: 1.0, fontSize: 11 });
  table(s, ["변경", "요청을 받은 인스턴스", "다른 인스턴스"], [
    ["사용자 비활성화, 역할 변경", "즉시", "최대 30초"],
    ["API 키 폐기, 재발급", "즉시", "최대 60초 (API_CLIENT_CACHE_SECONDS)"],
  ], [4.4, 3.6, 4.33], { y: 5.4, fontSize: 12 });

  s = slide("3.9 운영 업무: API 키");
  lead(s, "다른 서비스와 에이전트는 우리가 발급한 X-Api-Key와 X-User-Id 헤더로 호출합니다. 발급과 폐기는 시스템 화면의 API 키 탭에서 합니다.", Y0, 0.75);
  table(s, ["구분", "값", "뜻"], [
    ["tenant", "우리 tenant", "우리 사용자로 executor·배치를 부름. 우리 팀이 운영하는 서버 간 연동에만 발급"],
    ["tenant", "다른 tenant 이름", "그 tenant 범위만 읽고 씀. 다른 팀 서비스용"],
    ["kind", "standard (기본)", "조회가 X-User-Id 사용자 것만"],
    ["kind", "master", "조회가 tenant 전체. 사실상 관리자 읽기 권한"],
  ], [1.4, 2.6, 8.33], { y: 2.1, fontSize: 12 });
  bullets(s, [
    "키 원문은 발급 응답에서 한 번만 보입니다. DB에는 SHA-256만 남으므로 잃어버리면 재발급합니다. 재발급하면 이전 키는 그 순간 끊깁니다.",
    "마스터키는 설명에 용도와 담당자를 적고, 분기마다 쓰지 않는 키를 폐기합니다.",
    "우리가 쓰는 EXECUTOR_API_KEY, BATCH_API_KEY를 교체할 때는 끊김이 없도록 상대 서비스에 새 키의 해시를 먼저 추가하고, 우리 설정을 바꿔 배포한 뒤, 상대 서비스에서 옛 해시를 지웁니다.",
    "EXECUTOR_ADMIN_API_KEY는 시스템 화면의 런타임, 점검, 이벤트 스트림에만 씁니다.",
  ], { y: 4.2, h: 2.4, fontSize: 12.5 });

  s = slide("3.10 관리자 화면: 시스템 탭");
  lead(s, "웹 화면 왼쪽 메뉴의 \"시스템\"은 역할이 admin인 사용자에게만 보입니다.", Y0, 0.45);
  table(s, ["탭", "보는 것", "할 수 있는 일"], [
    ["런타임", "executor 런타임별 상태, CPU, 메모리, 실행 슬롯", "런타임 추가와 수정, 점검, 비우기, 활성화, 사용 중지, 제거"],
    ["런타임 커널", "커널별 메모리, CPU 누적, 그 커널을 쓰는 실행", "실행 취소, 남겨진 커널 삭제"],
    ["점검", "새 실행 접수 상태, 진행 중 작업 수, 종료 가능 여부", "새 실행 접수 중지와 재개, 진행 중 실행 멈추기"],
    ["이벤트 스트림", "tenant별 Redis 스트림 항목 수, consumer group의 lag과 pending", "항목과 pending 조회"],
    ["사용자", "역할, 활성 상태, 사용자별 배치", "역할 변경, 비활성화와 활성화"],
    ["API 키", "발급한 키 목록과 마지막 사용 시각", "발급, 재발급, 폐기"],
    ["API 호출 시험", "준비된 게이트웨이 호출 항목", "키와 X-User-Id를 넣어 기대한 상태 코드가 나오는지 확인"],
  ], [2.0, 5.4, 4.93], { y: 1.8, fontSize: 12 });
  bullets(s, [
    "런타임, 점검, 이벤트 스트림은 executor의 운영 API를 중계하는 화면이라 EXECUTOR_ADMIN_API_KEY가 비어 있으면 503이 됩니다.",
    "왼쪽 메뉴의 실행 이력에서 관리자는 tenant와 사용자를 골라 모든 실행을 볼 수 있습니다.",
  ], { y: 5.6, h: 1.0, fontSize: 12.5 });

  s = slide("3.10 관리자 화면: 런타임 커널과 실행 취소");
  image(s, D + "images/08-runtime-kernels.png", 2000, 1084, { w: 7.6, h: 4.2, left: true, alt: "런타임 커널 목록 화면(예시 데이터)" });
  s.addText("예시 데이터로 찍은 화면입니다.", { x: MX, y: 5.5, w: 7.6, h: 0.3, fontSize: 10, color: C.accent3, margin: 0, isTextBox: true, objectName: "caption" });
  bullets(s, [
    "런타임 카드의 \"커널\"을 누르면 커널과 각 커널을 쓰는 실행, 자원 사용량이 나옵니다.",
    "자원을 너무 많이 쓰는 실행은 \"실행 취소\"로 소유자와 tenant에 관계없이 취소할 수 있습니다.",
    "취소하면 돌던 코드가 멈추고 커널의 변수가 모두 사라집니다. 되돌릴 수 없습니다.",
    "채팅 분석 실행이면 기다리던 대화 작업도 함께 중지됩니다.",
    "실행이 없는 \"남겨진 커널\"은 \"삭제\"로 지웁니다. 최근 15분 안에 활동이 있던 커널은 삭제가 거부됩니다.",
  ], { x: 8.4, w: 4.43, h: 5.3, fontSize: 12.5 });

  s = slide("3.10 관리자 화면: 이벤트 스트림");
  image(s, D + "images/08-event-streams.png", 1400, 900, { w: 6.6, h: 4.3, left: true, alt: "이벤트 스트림 탭 화면(예시 데이터)" });
  s.addText("예시 데이터로 찍은 화면입니다.", { x: MX, y: 5.6, w: 6.6, h: 0.3, fontSize: 10, color: C.accent3, margin: 0, isTextBox: true, objectName: "caption" });
  table(s, ["보이는 것", "뜻과 조치"], [
    ["우리 tenant의 lag이 계속 늘어남", "우리가 이벤트를 읽지 못함. /healthz와 executor_event_* 로그 확인"],
    ["pending이 줄지 않고 idle이 김", "읽고서 확인하지 않은 항목. 다른 인스턴스가 이어받는지 확인"],
    ["소비자 없음", "그 tenant의 이벤트를 아무도 읽지 않음. 다른 tenant이면 그 팀에 알림"],
    ["Stream 없음", "아직 이벤트가 한 번도 없음. 조치 없음"],
  ], [2.2, 3.33], { x: 7.3, fontSize: 12 });
}

// ================= 4. 장애처리
section("4. 장애처리", ["4.1 장애처리 절차", "4.2 장애 유형별 조치", "4.3 담당자 연락처", "4.4 운영 시 주의사항"]);
{
  let s = slide("4.1 장애처리 절차");
  steps(s, [
    ["인지", "사용자 신고, 관제 알림, 정기 점검"],
    ["1차 확인", "인스턴스 상태, /healthz, 오류 로그"],
    ["원인 구분", "우리 서비스인지 연결된 서비스인지"],
    ["조치", "유형별 조치 (4.2). 필요하면 담당자 연락 (4.3)"],
    ["복구 확인", "배포 후 확인 5단계 (3.6)"],
    ["기록", "원인, 조치, 재발 방지"],
  ], { h: 1.55, fontSize: 12 });
  bullets(s, [
    "모든 응답에 X-Request-ID 헤더가 붙습니다. 사용자가 헤더 값을 주면 그 값으로 우리 로그와 executor 로그를 함께 찾습니다.",
    "사용자 화면의 오류 메시지에는 8자리 오류 ID가 있습니다. 그 ID로 로그를 검색하면 같은 줄이 나옵니다.",
    "키 호출은 요청마다 감사 로그 한 줄(경로, 상태 코드, tenant)이 남습니다.",
    "Agent가 어떤 프롬프트로 어떤 도구를 불렀는지는 Phoenix에서 봅니다.",
    "문제를 다른 사람에게 전달할 때 쿠키 값, 로그인 URL 전체, 사번은 보내지 않습니다. 상태 코드, 경로, 로그 줄이면 충분합니다.",
  ], { y: 3.1, h: 3.4, fontSize: 13 });

  s = slide("4.1 장애처리 절차: 먼저 보는 순서");
  image(s, D + "diagrams/export/08-ops-flow-1.png", 2220, 1050, { h: 5.0, alt: "장애 대응 순서 그림" });
  note(s, "그림 안의 절 번호는 Markdown 운영자 메뉴얼 기준입니다. 이 문서에서는 증상별 조치가 4.2, 로그 키워드가 3.7, 관리자 화면이 3.10입니다.", 6.45);

  const sym = [
    ["인스턴스가 뜨지 않고 재시작을 반복", "기동 로그의 ValueError, dtest_startup_failed", "설정 검사 실패(3.5), 마이그레이션 실패, DB·Redis 접속 불가, Sentinel 복호화 실패", "메시지에 나온 설정 키를 고침. 마이그레이션이면 이전 이미지로 되돌리고 원인 확인"],
    ["모든 요청이 401 Access key is required", "기동 로그에 gaia_auth_skipped_on_own_paths가 있는지", "gaia 접근 키 검사가 우리 경로에 걸림", "gaia 템플릿 버전과 attach 호출 위치 확인"],
    ["로그인이 안 됨", "sso_ 로 시작하는 로그", "SSO 주소, 허용 origin, 쿠키 도메인, Redis", "로그인(SSO) 문제 표"],
    ["로그인은 되는데 곧 풀림", "Redis 상태, 세션 설정", "Redis 재시작·장애 전환, 30분 무활동, 12시간 경과", "Redis 확인. 정상 만료면 조치 없음"],
    ["메시지를 보냈는데 답이 시작되지 않음", "run 상태 SQL, run_claim_failed, /healthz", "슬롯 부족(queued 적체), 스케줄러 루프 죽음, DB 오류", "run이 멈출 때 표"],
    ["답이 중간에 멈춤", "그 run의 status, error. run_lease_lost, run_heartbeat_failed", "인스턴스 재시작(다른 인스턴스가 이어 감), LLM 지연, DB 일시 장애", "run이 멈출 때 표"],
    ["run이 failed", "runs.error, 화면의 오류 ID로 로그 검색", "LLM 장애·한도·컨텍스트 초과, executor 장애, 재시도 5회 초과", "원인 서비스 확인. 사용자는 다시 보내면 됨"],
    ["분석이 끝나지 않음", "run이 waiting_executor인지, executor_event_* 로그", "executor 이벤트 미수신(Redis 불일치), 실제로 오래 걸림, executor 장애", "분석이 끝나지 않을 때 표"],
    ["화면이 실시간으로 갱신되지 않음", "앞단 설정, event_fanout_reconnect 로그", "앞단 버퍼링·시간 제한, Redis 구독 끊김", "앞단 설정 확인. Redis 구독은 자동으로 다시 붙음"],
    ["413", "요청 크기", "32MB 초과, 또는 앞단이 먼저 끊음", "응답 형식이 우리 것이 아니면 앞단 본문 크기 제한 확인"],
    ["429", "로그인 경로인지", "SSO 로그인 요청이 분당 30회 초과", "반복 로그인 원인 확인. Retry-After 뒤 재시도"],
    ["502 bad_gateway", "로그의 upstream_unreachable path=...", "executor 또는 batch가 응답하지 않음", "경로로 어느 서비스인지 보고 그 서비스 확인"],
    ["503 (시스템 화면)", "EXECUTOR_ADMIN_API_KEY 설정", "운영 키가 비어 있음", "키 설정"],
    ["키 호출이 401·403", "감사 로그, 키 상태", "키 폐기·재발급, X-User-Id 누락(400), 일반키로 다른 사용자 조회(403)", "키 목록에서 상태 확인"],
    ["DB 연결 오류", "QueuePool limit, too many connections", "연결 예산 초과, 풀 부족, 중간 장비가 연결을 끊음", "DB 문제 표"],
    ["배치 리포트가 안 만들어짐", "batch_report_jobs의 state, failed_stage, error", "노트북 대기 시간 초과(30분), LLM 장애, 배치 소유자 없음", "10분마다 복구 작업이 최근 14일분을 다시 확인"],
    ["워크플로우 추천이 안 나옴", "workflows.index_state", "임베딩 게이트웨이 장애, 임베딩 미설정, 모델·차원 변경", "원인 해소 후 다시 색인 (4.4)"],
    ["/healthz가 503", "응답의 stopped, worker_loops_stopped 로그", "백그라운드 루프가 예외로 끝남", "실행 환경이 재시작함. 반복되면 그 루프의 직전 예외 로그 확인"],
    ["프로젝트 메모리가 정리되지 않음", "memory_extraction_state의 last_error", "LLM 장애, MEMORY_WORKER_ENABLED: false", "원인 해소 후 자동 재시도"],
  ];
  const parts = [sym.slice(0, 7), sym.slice(7, 13), sym.slice(13)];
  parts.forEach((p, i) => {
    s = slide(`4.2 장애 유형별 조치: 증상별 대응표 (${i + 1}/3)`);
    table(s, ["증상", "먼저 볼 곳", "흔한 원인", "조치"], p, [2.6, 3.2, 3.5, 3.03], { fontSize: 12 });
  });

  s = slide("4.2 장애 유형별 조치: 로그인(SSO) 문제");
  lead(s, "브라우저로 {PUBLIC_API_ORIGIN}/api/v1/auth/login/sso?return_to=/ 를 열어 단계별로 봅니다. 로그 이름은 src.dtest.api_service.auth입니다.", Y0, 0.45);
  table(s, ["증상", "뜻", "먼저 볼 것"], [
    ["sso_userinfo result=http_404", "userinfo 주소가 틀림", "로그인된 브라우저에서 그 주소를 직접 열어 JSON이 나오는지"],
    ["sso_userinfo bad_fields 또는 no_employee", "응답 JSON의 키 이름이 idp_login.py의 FIELDS와 다름", "로그의 keys=[...]에 나온 이름으로 FIELDS를 고침"],
    ["502 invalid login URL", "로그인 주소의 origin이 허용 목록에 없음", "sso_login_url_rejected origin=...의 값을 SSO_ALLOWED_ORIGINS에 추가"],
    ["503 SSO is unavailable", "SSO 확인 호출이 예외", "sso_verify_failed error_type=..."],
    ["콜백에서 401 could not verify", "SSO에서 돌아왔지만 SSO 쿠키가 오지 않음", "쿠키가 없으면 도메인 문제(우리 주소가 IdP 도메인 아래가 아님, 또는 http)"],
    ["콜백에서 400 Login flow expired", "5분이 지났거나 같은 콜백을 다시 엶", "처음부터 다시 로그인"],
    ["SSO와 우리 사이를 계속 왕복", "복귀 주소를 잃어버림", "sso_login_redirect가 몇 번 찍히는지"],
    ["로그인 후 403 disabled", "비활성 사용자", "users.is_active"],
  ], [3.6, 4.0, 4.73], { y: 1.8, fontSize: 12 });

  s = slide("4.2 장애 유형별 조치: run이 시작되지 않거나 멈출 때");
  table(s, ["보이는 상태", "뜻", "조치"], [
    ["queued가 오래 유지", "가져갈 슬롯이 없거나 스케줄러가 멈춤", "running 수가 인스턴스 수 × 16에 닿았는지, 같은 사용자의 running이 4개인지 확인. /healthz 확인"],
    ["running인데 lease_expires_at이 과거", "실행하던 인스턴스가 죽음", "조치 없음. 다른 인스턴스가 5초 안에 가져가 이어 감"],
    ["running이 오래 유지되고 lease는 갱신됨", "LLM 응답을 기다리는 중", "LLM 게이트웨이 상태 확인. 턴당 모델 호출 40회, 호출당 120초가 상한"],
    ["waiting_input", "사용자의 확인을 기다림", "정상. 화면에 질문이 떠 있음"],
    ["waiting_executor", "executor 실행을 기다림", "분석이 끝나지 않을 때 표"],
    ["failed", "error에 이유", "원인 서비스 확인"],
  ], [3.6, 3.6, 5.13], { fontSize: 12 });
  bullets(s, [
    "한 run이 연속 5번(RUN_MAX_ATTEMPTS) 실행되고도 결과가 없으면 failed로 끝납니다.",
    "DB 장애로 lease를 40초 동안 갱신하지 못하면 그 인스턴스는 턴을 스스로 멈춥니다(run_lease_unrenewed).",
    "세션에 진행 중인 run이 남아 새 메시지를 못 보내면 sessions.active_run_id와 그 run의 상태를 함께 봅니다.",
  ], { y: 4.85, h: 1.7, fontSize: 12.5 });

  s = slide("4.2 장애 유형별 조치: 분석이 끝나지 않을 때 (executor 대기)");
  steps(s, [
    ["실행 ID 확인", "run의 waiting에서 execution_id를 확인"],
    ["executor 상태 확인", "시스템 화면의 실행 이력 또는 GET /api/v1/executor/executions/{execution_id}"],
    ["이벤트 확인", "executor에서는 끝났는데 run이 그대로면 이벤트가 오지 않은 것. executor_inbox와 이벤트 스트림 탭 확인"],
  ], { h: 1.5, fontSize: 12 });
  table(s, ["상황", "원인", "조치"], [
    ["inbox에 완료 이벤트가 없고 executor_event_recovered가 자주 보임", "Redis가 executor와 다름, 또는 이벤트 소비 루프 문제", "Redis 설정 대조. executor_event_consumer_error 로그 확인"],
    ["로그에 executor_event_group_lost", "Redis가 비워졌거나 스트림이 지워짐", "자동으로 소비자 그룹을 다시 만듦. 그 사이 이벤트는 복구 절차가 채움"],
    ["로그에 missed_event_lookup_failed", "복구 절차가 executor에 물었지만 실패", "executor 상태와 EXECUTOR_API_KEY 확인"],
    ["executor에서도 실행 중", "실제로 오래 걸리는 분석", "기다리거나 사용자가 취소. 자원을 너무 쓰면 관리자가 실행 취소"],
    ["executor에 그 실행이 없음", "executor 데이터가 지워졌거나 다른 executor를 가리킴", "사용자가 취소하고 다시 요청"],
  ], [4.6, 3.6, 4.13], { y: 3.0, fontSize: 12 });
  note(s, "놓친 이벤트 복구는 기다린 지 120초가 지난 run부터 합니다. Redis가 완전히 죽어도 분석은 끝나지만 단계마다 2분 이상 늦어집니다.", 6.4);

  s = slide("4.2 장애 유형별 조치: DB와 Redis");
  table(s, ["로그 또는 상황", "뜻", "조치"], [
    ["QueuePool limit of size ... reached", "앱 풀이 모자람", "일시적이면 무시. 반복되면 DB_POOL_SIZE 증가"],
    ["그래프 풀 대기 시간 초과로 턴 실패", "그래프 풀이 모자라거나 DB가 느림", "DB 응답 시간 확인. CHECKPOINT_POOL_SIZE 증가"],
    ["too many connections", "서버 연결 한도 초과", "pg_stat_activity로 누가 쓰는지 확인. 예산 재계산"],
    ["server closed the connection unexpectedly", "중간 장비가 조용한 연결을 끊음", "DB_KEEPALIVE_IDLE_SECONDS를 낮춤"],
    ["run_claim_failed attempt=N", "run을 가져오는 쿼리 실패", "DB 상태 확인. DB가 돌아오면 자동 복구"],
    ["Redis 재시작", "로그인 세션이 사라질 수 있음", "사용자가 다시 로그인. 소비자 그룹은 자동으로 다시 만듦. 재시작 불필요"],
    ["Sentinel 장애 전환", "쓰기와 이벤트 수신이 5~31초 멈춤", "자동 복구. 전환 중 요청은 실패할 수 있음"],
  ], [4.2, 3.6, 4.53], { fontSize: 12 });
  bullets(s, [
    "DB가 잠깐 끊겼다 돌아오면 재시작 없이 복구됩니다. 실행 중이던 턴은 멈춘 뒤 다시 큐로 돌아갑니다.",
    "Redis 관련 로그: event_fanout_reconnect, run_wake_listener_reconnect, executor_event_consumer_error",
  ], { y: 5.3, h: 1.2, fontSize: 12.5 });

  s = slide("4.2 장애 유형별 조치: 키 호출 문제");
  table(s, ["응답", "뜻"], [
    ["401", "키가 없거나, 틀렸거나, 폐기됨"],
    ["400", "X-User-Id 헤더가 없음. 게이트웨이의 모든 호출에 필수"],
    ["403 FORBIDDEN", "일반키로 X-User-Id와 다른 사용자의 것을 조회함. tenant 전체 조회가 필요하면 마스터키"],
    ["502", "executor 또는 batch가 응답하지 않음"],
  ], [2.4, 9.93]);
  bullets(s, [
    "우리가 executor나 batch를 부를 때 401이 나면 우리 EXECUTOR_API_KEY 또는 BATCH_API_KEY가 상대 서비스에 등록된 해시와 맞지 않는 것입니다.",
    "상대 서비스 설정에는 키 원문이 아니라 SHA-256 해시를 넣고, 우리 설정에는 원문을 넣습니다. 반대로 넣는 실수가 통합테스트에서 있었습니다.",
    "키를 새로 발급했거나 폐기한 뒤에는 시스템 화면의 API 호출 시험 탭으로 기대한 상태 코드가 나오는지 확인합니다.",
  ], { y: 3.6, h: 2.6, fontSize: 13 });

  s = slide("4.3 담당자 연락처");
  table(s, ["구분", "담당 업무", "소속", "이름", "연락처", "비고"], [
    ["gaia-api-service", "서비스 운영, 장애 1차 대응", "", "", "", ""],
    ["gaia-api-service", "개발, 패치", "", "", "", ""],
    ["executor", "분석 코드 실행, 런타임", "", "", "", ""],
    ["batch", "배치 실행", "", "", "", ""],
    ["사내 플랫폼", "컨테이너, 배포, 앞단 라우팅", "", "", "", ""],
    ["PostgreSQL", "서비스형 DB", "", "", "", ""],
    ["Redis", "", "", "", "", ""],
    ["LLM·임베딩 게이트웨이", "모델 호출", "", "", "", ""],
    ["SSO (IdP)", "로그인", "", "", "", ""],
  ], [2.6, 3.2, 1.7, 1.5, 2.0, 1.33], { boldFirst: false });
  note(s, "연락처는 담당자가 직접 작성합니다.", 6.4);

  const cautions = [
    ["Redis는 executor와 같은 서버, 같은 DB 번호", "다르면 오류 없이 이벤트가 오지 않아 모든 분석이 단계마다 2분씩 느려짐. executor_event_recovered가 계속 찍힘", "REDIS_URL 또는 REDIS_SENTINEL_*을 executor 설정과 똑같이 맞춤"],
    ["Sentinel 노드를 REDIS_URL로 직접 가리키지 않음", "장애 전환으로 그 노드가 레플리카가 되면 READONLY 오류로 멈춤", "Sentinel 환경은 반드시 REDIS_MODE: sentinel"],
    ["dev와 prd가 같은 DB 서버를 씀", "연결 한도 150과 서버 자원을 함께 씀. DATABASE_URL의 데이터베이스 이름을 잘못 적으면 오류 없이 다른 환경에 붙음", "설정의 데이터베이스 이름 확인. 직접 접속하면 SELECT current_database()로 먼저 확인"],
    ["마이그레이션 실패 시 모든 인스턴스가 뜨지 못함", "AUTO_MIGRATE: true(기본)라서 기동 때 자동 실행. 실패하면 새 인스턴스가 뜨지 못하고, 옛 인스턴스가 이미 내려갔다면 서비스가 멈춤", "dev, stg에서 먼저 적용된 것만 prd로 올림. 하나씩 교체. 실패하면 이전 버전으로 되돌림"],
    ["PostgreSQL 연결 수에는 예산이 있음", "인스턴스 하나가 최대 14. 넘으면 같은 서버의 모든 서비스에서 too many connections", "합계에 여유 20 이상. 인스턴스 3개 이상이면 하나씩 교체. 올리기 전에 다시 계산"],
    ["중간 장비가 조용한 연결을 끊음", "쉬던 연결이 끊겨 다음 턴이 server closed the connection으로 실패", "DB_KEEPALIVE_IDLE_SECONDS를 장비의 idle 제한보다 짧게"],
    ["인스턴스 하나에 uvicorn worker는 1개", "늘리면 백그라운드 루프와 DB 풀이 곱해져 연결 예산이 깨짐", "처리량이 필요하면 인스턴스 수를 늘림"],
    ["큰 요청과 긴 연결을 쓰는 서비스", "앞단이 본문 크기를 줄이거나 응답을 버퍼링하거나 연결을 끊으면 서비스 문제처럼 보임", "413 응답 형식, 이벤트 도착 방식, SSE 끊김 간격으로 앞단 문제를 구분"],
    ["사용자와 키 변경은 조금 늦게 반영", "다른 인스턴스에 사용자 30초, 키 60초", "바로 막아야 하면 폐기 뒤 60초를 기다리거나 재시작"],
    ["임베딩 모델이나 차원 변경", "기존 벡터가 검색에서 빠져 워크플로우 추천이 비어 보임", "바꾼 뒤 POST /api/v1/workflows/{id}/reindex로 다시 색인"],
    ["공유 저장소의 경로와 계정", "마운트 경로나 UID가 다르면 파일을 못 읽음", "STORAGE_ROOT, STORAGE_EXECUTOR_PATH, EXECUTOR_RESULT_ROOT를 executor와 맞춤. UID 1000"],
    ["키는 설정 파일에 있음", "config.{env}.yml에 키와 비밀번호가 들어 있음", "내부망 깃랩 밖으로 실제 값을 옮기지 않음"],
    ["브랜치는 master, stg, prd 순서로 올림", "stg나 prd에 직접 커밋하면 merge --ff-only가 실패하고 환경마다 코드가 달라짐", "작업은 feature 브랜치에서 하고 master에 머지. stg와 prd는 ff-only로만 받음 (5.2)"],
  ];
  [cautions.slice(0, 7), cautions.slice(7)].forEach((p, i) => {
    s = slide(`4.4 운영 시 주의사항 (${i + 1}/2)`);
    table(s, ["항목", "문제와 증상", "예방"], p, [3.4, 4.9, 4.03], { fontSize: 12 });
  });

  s = slide("4.4 운영 시 주의사항: DB 연결 예산");
  lead(s, "계산식은 인스턴스 수 × (DB_POOL_SIZE × 2 + CHECKPOINT_POOL_SIZE)입니다. 기본값이면 인스턴스당 14입니다.", Y0, 0.45);
  table(s, ["우리 인스턴스 수", "평소", "하나씩 교체 중", "한꺼번에 교체 중"], [
    ["2", "28", "42", "56"],
    ["3", "42", "56", "84"],
    ["4", "56", "70", "112"],
  ], [3.2, 3.0, 3.0, 3.13], { y: 1.8 });
  bullets(s, [
    "여기에 executor(인스턴스당 16), batch(인스턴스당 6), dev와 prd를 모두 더한 값이 150 아래여야 합니다.",
    "예: prd(우리 2, executor 1, batch 1)와 dev(우리 1, executor 1, batch 1)이면 평소 86, prd의 우리 서비스를 한꺼번에 교체하는 동안 114입니다.",
    "우리가 4개로 늘어난 상태에서 한꺼번에 교체하면 170으로 한도를 넘습니다.",
    "표는 모든 풀이 꽉 찬 최악의 경우입니다. 평소 실제 연결 수는 훨씬 적습니다.",
  ], { y: 3.75, h: 2.7, fontSize: 13 });
}

// ================= 5. 유지보수 가이드
section("5. 유지보수 가이드", ["5.1 개발자 개발 환경 setting 정보", "5.2 패치방법 (App Server)", "부록 A. 자주 쓰는 SQL · 부록 B. 운영 스크립트"]);
{
  let s = slide("5.1 개발 환경 setting: 필요한 것");
  table(s, ["항목", "내용"], [
    ["Python", "3.11. 의존성 관리는 uv (uv sync)"],
    ["PostgreSQL", "pgvector 확장 필요. 로컬 compose는 pgvector/pgvector:pg17 이미지 사용"],
    ["Redis", "6.2 이상"],
    ["executor", "executor 레포의 compose 스택. 공유 폴더를 함께 마운트"],
    ["LLM", "LLM 게이트웨이 또는 scripts/mock_llm.py"],
    ["batch (선택)", "배치 화면을 볼 때만 필요"],
    ["브랜치", "master(dev 배포), stg, prd. 작업은 master에서 feature 브랜치를 따서 진행"],
  ], [2.4, 9.93]);
  bullets(s, [
    "로컬 설정은 APP_ENV를 비운 채 공통 config.yml 위에 환경변수(.env 또는 docker-compose.yml의 environment)가 덮습니다.",
    "로컬에서는 SSO_ADAPTER=dev로 가짜 로그인을 쓸 수 있습니다. 서버 환경에서는 기동이 거부됩니다.",
    "executor의 공유 저장소를 마운트할 수 없으면 .env.testmode.example을 씁니다(EXECUTOR_IO_MODE=api, 테스트 전용).",
  ], { y: 4.75, h: 1.8, fontSize: 12.5 });

  s = slide("5.1 개발 환경 setting: 실행과 검사");
  const hw = (CW - 0.3) / 2;
  s.addText("Docker Compose로 실행", { x: MX, y: Y0, w: hw, h: 0.35, fontSize: 14, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "sub head" });
  code(s, [
    "# shared-infra(postgres, redis)와",
    "# executor compose가 떠 있는 상태에서",
    "docker compose up -d --build",
    "",
    "# mock LLM을 쓸 때",
    "docker compose --profile mock up -d",
  ].join("\n"), { y: Y0 + 0.45, w: hw, h: 1.7 });
  s.addText("직접 실행", { x: MX + hw + 0.3, y: Y0, w: hw, h: 0.35, fontSize: 14, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "sub head" });
  code(s, [
    "cp .env.example .env    # DB, executor 경로 수정",
    "uv sync",
    "uv run python -m src.dtest.local   # 로컬 포트 8080",
    "",
    "# 내부망에서는",
    "uv run python app.py",
  ].join("\n"), { x: MX + hw + 0.3, y: Y0 + 0.45, w: hw, h: 1.7 });
  table(s, ["하는 일", "명령 또는 주소"], [
    ["웹 화면 (로컬)", "http://localhost:8080/dev/"],
    ["API 문서 (로컬만)", "http://localhost:8080/docs"],
    ["단위 테스트", "uv run pytest"],
    ["정적 검사", "uv run ruff format, uv run ruff check, uv run ty check"],
    ["종단 점검", "uv run python scripts/smoke_e2e.py"],
    ["부하 측정 (로컬, mock LLM)", "uv run python scripts/loadtest.py --users 100 --turns 3"],
  ], [3.6, 8.73], { y: 3.75, mono: [1], fontSize: 12 });
  note(s, "src/dtest/assets/와 src/dtest/agent/prompts/는 compose에서 마운트되어 있어 수정하면 재빌드 없이 다음 요청부터 반영됩니다.", 6.45);

  s = slide("5.2 패치방법 (App Server): 브랜치와 절차");
  table(s, ["브랜치", "배포 환경", "받는 방법"], [
    ["feature/...", "없음 (작업용)", "master에서 따서 작업"],
    ["master", "dev", "feature 브랜치를 머지"],
    ["stg", "stg", "git merge --ff-only master"],
    ["prd", "prd", "git merge --ff-only stg"],
  ], [2.6, 3.0, 6.73]);
  steps(s, [
    ["feature 작업", "master에서 feature 브랜치를 따서 작업. uv run pytest"],
    ["master 머지", "master에 머지하면 dev에 배포. dev에서 확인 (3.6)"],
    ["stg 반영", "stg에서 git merge --ff-only master. stg 배포와 확인"],
    ["prd 반영", "prd에서 git merge --ff-only stg. prd 배포"],
    ["확인", "배포 후 확인 5단계 (3.6)"],
  ], { y: 3.35, h: 1.6, fontSize: 12 });
  bullets(s, [
    "stg와 prd에는 직접 커밋하지 않습니다. 직접 커밋이 있으면 --ff-only 머지가 실패합니다.",
    "세 브랜치의 코드는 같고, 환경 차이는 APP_ENV가 고르는 config.{APP_ENV}.yml뿐입니다.",
  ], { y: 5.15, h: 0.8, fontSize: 12.5 });
  table(s, ["사내 플랫폼 배포 절차 (작성 필요)", "내용"], [["빌드와 배포 도구, 승인 절차", ""]], [4.0, 8.33], { y: 6.0, boldFirst: false });

  s = slide("5.2 패치방법 (App Server): 마이그레이션과 롤백");
  const pw = (CW - 0.3) / 2;
  card(s, MX, Y0, pw, 2.5, "마이그레이션은 자동 실행", [
    { text: "AUTO_MIGRATE: true(기본값, 세 환경 공통)라서 새 버전의 인스턴스가 시작하면서 마이그레이션을 실행합니다.", options: { breakLine: true } },
    { text: "여러 인스턴스가 동시에 떠도 잠금을 잡은 한 인스턴스만 실행합니다.", options: { breakLine: true } },
    { text: "새 마이그레이션은 dev, stg를 거치며 먼저 적용되므로 prd에는 확인된 것만 올라갑니다.", options: {} },
  ], { fontSize: 13 });
  card(s, MX + pw + 0.3, Y0, pw, 2.5, "실패했을 때", [
    { text: "마이그레이션이 실패하면 새 인스턴스가 뜨지 못합니다. 기동 로그의 dtest_startup_failed와 바로 위 예외를 봅니다.", options: { breakLine: true } },
    { text: "하나씩 교체하면 옛 인스턴스가 남아 서비스를 계속합니다.", options: { breakLine: true } },
    { text: "이전 버전으로 되돌린 뒤 원인을 고쳐 다시 올립니다.", options: {} },
  ], { fontSize: 13 });
  bullets(s, [
    "롤백은 이전 버전으로 되돌리면 됩니다. 마이그레이션은 이전 버전 코드가 계속 동작하도록(컬럼과 인덱스 추가만) 작성하므로 스키마는 되돌리지 않습니다.",
    "배포 중에는 옛 인스턴스가 종료 정리(최대 45초)를 마치고 내려가며, 진행 중이던 턴은 새 인스턴스가 이어 갑니다.",
    "마이그레이션을 배포와 따로 실행하고 싶으면 AUTO_MIGRATE: false로 두고 배포할 버전의 코드로 python scripts/migrate.py를 실행합니다.",
    "새 마이그레이션 번호는 master 기준으로 하나씩 늘립니다. feature 브랜치를 머지하기 전에 master의 최신 번호와 겹치지 않는지 확인합니다.",
  ], { y: 4.05, h: 2.5, fontSize: 13 });

  s = slide("5.2 패치방법 (App Server): 빌드와 변경 유형별 방법");
  table(s, ["변경 유형", "방법"], [
    ["코드", "절차대로 배포"],
    ["설정 값", "config.{APP_ENV}.yml을 고쳐 배포. 실행 중인 인스턴스는 설정을 다시 읽지 않음. 한 값만 바꿀 때는 같은 이름의 환경변수"],
    ["모델 목록", "MODELS를 고쳐 배포. default: true는 정확히 하나. 목록에서 뺀 모델로 기다리던 run은 기본 모델로 이어 감"],
    ["skill, tool, 프롬프트", "src/dtest/assets/와 src/dtest/agent/prompts/를 고쳐 배포. 깨진 tool 파일은 그 파일만 건너뛰고 tool_load_failed 경고"],
    ["의존성", "pyproject.toml을 고치고 uv lock으로 uv.lock 갱신"],
    ["우리가 쓰는 키 교체", "상대 서비스에 새 해시 추가, 우리 설정 변경 배포, 상대 서비스에서 옛 해시 삭제 순서"],
  ], [2.6, 9.73], { fontSize: 12 });
  bullets(s, [
    "내부망은 Python 3.11입니다. 3.12 전용 문법이 들어가면 실행에서 깨집니다.",
    "FastAPI는 0.137 미만, langgraph-checkpoint-postgres는 3.1.3으로 고정되어 있습니다. 올리기 전에 tests/test_checkpoint_saver.py를 확인합니다.",
    "코드는 src/dtest/ 아래에 두고 import는 src.dtest.로 씁니다.",
  ], { y: 4.55, h: 2.0, fontSize: 12.5 });

  s = slide("부록 A. 자주 쓰는 SQL");
  const hw2 = (CW - 0.3) / 2;
  code(s, [
    "-- run 상태 분포 (부하와 적체 확인)",
    "SELECT status, count(*) FROM runs",
    "WHERE created_at > now() - interval '1 day'",
    "GROUP BY 1 ORDER BY 2 DESC;",
    "",
    "-- 지금 인스턴스별로 돌고 있는 run",
    "SELECT lease_owner, count(*) FROM runs",
    "WHERE status = 'running'",
    "  AND lease_expires_at > now()",
    "GROUP BY 1;",
    "",
    "-- 오래 대기 중인 queued run",
    "SELECT id, user_id, created_at FROM runs",
    "WHERE status = 'queued'",
    "ORDER BY created_at LIMIT 20;",
    "",
    "-- 최근 실패한 run과 이유",
    "SELECT id, user_id, finished_at,",
    "       left(error, 200) FROM runs",
    "WHERE status = 'failed'",
    "ORDER BY finished_at DESC LIMIT 20;",
  ].join("\n"), { w: hw2, h: 5.5, fontSize: 12 });
  code(s, [
    "-- executor를 오래 기다리는 run",
    "SELECT id, waiting ->> 'execution_id',",
    "       updated_at FROM runs",
    "WHERE status = 'waiting_executor'",
    "ORDER BY updated_at LIMIT 20;",
    "",
    "-- 배치 리포트 작업 상태",
    "SELECT state, failed_stage, count(*)",
    "FROM batch_report_jobs",
    "WHERE created_at > now() - interval '7 days'",
    "GROUP BY 1, 2 ORDER BY 3 DESC;",
    "",
    "-- 우리 서비스의 풀별 연결 수",
    "SELECT application_name, state, count(*)",
    "FROM pg_stat_activity",
    "WHERE application_name LIKE 'pr-agentic-%'",
    "GROUP BY 1, 2 ORDER BY 1, 2;",
    "",
    "-- 서버 전체에서 누가 연결을 쓰는지",
    "SELECT datname, usename, application_name,",
    "       count(*) FROM pg_stat_activity",
    "GROUP BY 1, 2, 3 ORDER BY 4 DESC;",
  ].join("\n"), { x: MX + hw2 + 0.3, w: hw2, h: 5.5, fontSize: 12 });

  s = slide("부록 B. 운영 스크립트 (scripts/)");
  table(s, ["스크립트", "용도"], [
    ["migrate.py", "마이그레이션을 따로 실행 (AUTO_MIGRATE: false일 때)"],
    ["set_user_role.py, set_user_role.sql", "관리자 지정과 역할 변경"],
    ["check_redis_sentinel.py", "Redis Sentinel 접속 확인"],
    ["check_embedding.sh, check_embedding.ps1", "임베딩 게이트웨이 확인"],
    ["check_executor_mcp.sh", "executor MCP 확인"],
    ["migrate_project_memory.py", "예전 항목형 프로젝트 메모리를 주제형으로 옮김"],
    ["smoke_e2e.py", "로그인부터 분석까지 종단 점검"],
    ["run_scenarios.py", "분석 시나리오 일괄 실행(품질 회귀 점검)"],
    ["loadtest.py, mock_llm.py", "로컬 부하 측정, LLM 게이트웨이 대역"],
    ["seed_test_workflows.py", "테스트용 워크플로우 등록"],
    ["run_local_https.ps1, run_app_tls.py, make_local_cert.py", "개발 PC에서 https로 띄워 SSO 확인"],
  ], [5.4, 6.93], { mono: [0], fontSize: 12 });
  note(s, "스크립트는 이미지에 들어가지 않으므로 배포할 버전의 레포에서 같은 설정으로 실행합니다.", 6.45);
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("slides", n);
})();
