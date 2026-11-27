// 논리 ERD, 물리 ERD, Table 정의서 PPT. 데이터는 export_json.py가 만든 erd_data.json.
// 사용: node build_erd_pptx.js logical|physical|tabledef <출력.pptx>  (tools 폴더에서 실행)
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/mnt/skills/public/pptx/scripts/apply_theme.js");
const D = "../";
const DG = "../diagrams/export/";
const KIND = process.argv[2]; const OUT = process.argv[3];
const DOCTITLE = {logical:"gaia-api-service 논리 ERD", physical:"gaia-api-service 물리 ERD", tabledef:"gaia-api-service Table 정의서"}[KIND];

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
pres.title = DOCTITLE;
const C = pres.SchemeColor;
const W = 13.33, MX = 0.5, CW = W - 2 * MX;
const FOOT = DOCTITLE;

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
  const cell = (t, opt) => ({ text: String(t), options: Object.assign({ fontSize: fs, color: C.text1, valign: "middle", margin: o.margin || [3, 6, 3, 6] }, opt) });
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
    s.addText(String(i + 1 + (o.start || 0)), { x: x + 0.15, y: y + 0.15, w: 0.42, h: 0.42, fontSize: 13, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "step no" });
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

const DATA = JSON.parse(require("fs").readFileSync(__dirname + "/erd_data.json", "utf8"));
const EX = D + "diagrams/export/";
const sizeOf = (p) => {
  const b = require("fs").readFileSync(p);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
};
const TB = DATA.tables;
const APP = TB.filter(t => t.group === "app"), EXT = TB.filter(t => t.group !== "app");
const NCOL = TB.reduce((a, t) => a + t.cols.length, 0);

// ---- row height estimate for manual pagination
function textW(s, fs) {
  let w = 0;
  for (const ch of String(s)) w += ch.charCodeAt(0) > 0x2e80 ? fs : fs * 0.56;
  return w; // points
}
function rowH(row, colW, fs) {
  let lines = 1;
  row.forEach((c, j) => {
    const avail = colW[j] * 72 - 12;
    lines = Math.max(lines, Math.ceil(textW(c, fs) / avail));
  });
  return (lines * fs * 1.2 + 7.5) / 72;
}
function pages(rows, colW, fs, firstH, nextH) {
  const out = [];
  let cur = [], h = 0, lim = firstH;
  const head = rowH(["x"], [10], fs);
  rows.forEach(r => {
    const rh = rowH(r, colW, fs);
    if (cur.length && h + rh + head > lim) { out.push(cur); cur = []; h = 0; lim = nextH; }
    cur.push(r); h += rh;
  });
  if (cur.length) out.push(cur);
  return out;
}
function tableH(rows, colW, fs) {
  return rowH(["x"], [10], fs) + rows.reduce((a, r) => a + rowH(r, colW, fs), 0);
}
function pagedTable(title, head, rows, colW, o = {}) {
  let fs = o.fontSize || 10;
  const first = o.firstY ?? Y0;
  let ps = pages(rows, colW, fs, 6.95 - first, 6.95 - Y0);
  // a table that spills by a few rows fits on fewer slides one point smaller
  const ps2 = pages(rows, colW, fs - 1, 6.95 - first, 6.95 - Y0);
  if (ps2.length < ps.length) { ps = ps2; fs -= 1; }
  const slides = [];
  ps.forEach((p, i) => {
    const s = i === 0 && o.first ? o.first : slide(ps.length > 1 ? `${title} (${i + 1}/${ps.length})` : title);
    if (i === 0 && o.onFirst) o.onFirst(s);
    table(s, head, p, colW, { y: i === 0 ? first : Y0, fontSize: fs, boldFirst: false, mono: o.mono || [], margin: [2, 5, 2, 5] });
    slides.push({ s, y: (i === 0 ? first : Y0) + tableH(p, colW, fs), fs });
  });
  return slides;
}
function cover(title, sub) {
  pres.addSection({ title: "표지" });
  SEC = "표지";
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: SEC });
  s.addText(title, { placeholder: "title" });
  s.addText([{ text: "사내 데이터 분석 Agent 서비스", options: { breakLine: true } }, { text: sub, options: {} }], { placeholder: "body" });
}
function history(rows) {
  const t = slide("개정 이력");
  table(t, ["버전", "일자", "내용", "작성", "검토"], rows.concat([["", "", "", "", ""]]), [1.2, 1.8, 6.33, 1.5, 1.5], { boldFirst: false });
  return t;
}
function erdImages(prefix, titles) {
  titles.forEach((tt, i) => {
    const s = slide(tt);
    const p = EX + `${prefix}-${i + 1}.png`;
    const [w, h] = sizeOf(p);
    image(s, p, w, h, { y: 1.1, h: 5.75, alt: tt });
  });
}
function tableList(title) {
  const rows = TB.map(t => [String(t.no), t.name, t.ko, t.area, t.pk, String(t.cols.length), t.growth, t.cleanup]);
  pagedTable(title, ["No", "테이블", "한글명", "영역", "기본키", "컬럼 수", "행 증가", "자동 정리"], rows,
    [0.5, 2.3, 1.9, 1.7, 2.0, 0.8, 1.73, 1.4], { fontSize: 10.5, mono: [1] });
}

// =====================================================================
if (KIND === "logical") {
  cover("gaia-api-service 논리 ERD", `엔티티 ${TB.length}개, 속성 ${NCOL}개 (마이그레이션 0008까지 반영)`);
  history([["0.1", "2026-11-25", "초안 작성 (Markdown)", "", ""],
           ["0.2", "2026-11-27", "PPT 작성. 모든 속성을 한글 속성명과 함께 표시. LangGraph, Alembic 테이블 추가", "", ""]]);
  section("1. 개요", ["1.1 데이터 저장소와 공통 규칙", "1.2 데이터 영역", "1.3 ERD", "1.4 관계와 카디널리티"]);
  let s = slide("1.1 데이터 저장소와 공통 규칙");
  table(s, DATA.overview[0], DATA.overview.slice(1), [3.0, 4.6, 4.73], { fontSize: 11.5 });
  bullets(s, [
    "기본키는 UUID 문자열(36자)입니다. 이벤트와 이력처럼 순서가 필요한 테이블만 자동 증가 정수입니다.",
    "시각은 모두 시간대가 있는 UTC입니다.",
    "프로젝트, 세션, 워크플로우는 지우지 않고 deleted_at에 시각을 적습니다(논리 삭제).",
    "외래키 제약은 핵심 계층(사용자, 프로젝트, 세션, 메시지, run, 워크플로우)에만 있습니다. 부속 테이블은 값으로만 참조합니다.",
    "분석 코드의 실행 기록, 노트북, 리포트 파일은 executor가 가집니다. 우리 DB에는 그 식별자만 남습니다.",
  ], { y: 4.1, h: 2.6, fontSize: 12.5 });
  s = slide("1.2 데이터 영역");
  table(s, DATA.areas[0], DATA.areas.slice(1).concat([
    ["LangGraph 체크포인트", "checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations", "Agent의 대화 상태"],
    ["LangGraph store", "store, store_migrations", "프로젝트 메모리 본문, 도구 실행 결과, 배치 리포트 요약"],
    ["마이그레이션", "alembic_version", "적용된 마이그레이션 번호"],
  ]), [2.4, 4.6, 5.33], { fontSize: 12 });
  erdImages("04-erd-logical", ["1.3 ERD: 전체", "1.3 ERD: 사용자, 대화, 실행, executor 연동, gaia 연동",
    "1.3 ERD: 워크플로우, 배치 리포트, 프로젝트 메모리, 서비스 간 인증", "1.3 ERD: LangGraph 체크포인트와 store, 마이그레이션 버전"]);
  pagedTable("1.4 관계와 카디널리티", DATA.rels[0], DATA.rels.slice(1), [2.3, 2.3, 0.9, 1.6, 5.23], { fontSize: 10.5 });
  section("2. 엔티티별 속성", [`엔티티 ${TB.length}개의 모든 속성`, "키: PK 기본키, FK 외래키 제약, UK 유일 제약", "필수: 값이 반드시 있어야 하는 속성"]);
  TB.forEach((t, i) => {
    const rows = t.cols.map((c, j) => [String(j + 1), c.ko, c.name, c.key, c.null === "N" ? "필수" : "선택", c.desc]);
    const colW = [0.5, 2.1, 2.4, 0.8, 0.6, 5.93];
    const leadH = t.about ? Math.max(0.45, Math.ceil(textW(t.about, 12) / (CW * 72)) * 0.25 + 0.1) : 0;
    pagedTable(`2.${i + 1} ${t.name} (${t.ko})`, ["No", "속성명", "컬럼", "키", "필수", "설명"], rows, colW, {
      mono: [2], firstY: Y0 + leadH,
      onFirst: (s) => { if (t.about) s.addText(t.about, { x: MX, y: Y0 - 0.05, w: CW, h: leadH, fontSize: 12, color: C.accent3, margin: 0, valign: "top", isTextBox: true, objectName: "about" }); },
    });
  });
}

// =====================================================================
if (KIND === "physical") {
  cover("gaia-api-service 물리 ERD", `테이블 ${TB.length}개, 컬럼 ${NCOL}개, 인덱스 ${DATA.indexes.length}개 (마이그레이션 0008까지 반영)`);
  history([["0.1", "2026-11-25", "초안 작성 (Markdown)", "", ""],
           ["0.2", "2026-11-27", "PPT 작성. 모든 컬럼을 타입과 함께 표시. LangGraph, Alembic 테이블과 인덱스 추가", "", ""]]);
  section("1. DB 구성과 ERD", ["1.1 DB 구성", "1.2 물리 ERD", "1.3 테이블 목록", "1.4 인덱스"]);
  let s = slide("1.1 DB 구성");
  table(s, DATA.dbconf[0], DATA.dbconf.slice(1), [2.6, 9.73], { fontSize: 11.5 });
  erdImages("05-erd-physical", ["1.2 물리 ERD: 사용자, 대화, 실행, executor 연동, gaia 연동",
    "1.2 물리 ERD: 워크플로우, 배치 리포트, 프로젝트 메모리, 서비스 간 인증", "1.2 물리 ERD: LangGraph 체크포인트와 store, 마이그레이션 버전"]);
  tableList("1.3 테이블 목록");
  const ir = DATA.indexes.map(x => [x.table, x.name, x.cols, x.use]);
  pagedTable("1.4 인덱스", ["테이블", "인덱스", "컬럼", "받치는 조회"], ir, [2.3, 3.6, 3.4, 3.03], {
    fontSize: 10.5, mono: [1], firstY: Y0 + 0.45,
    onFirst: (s) => lead(s, "기본키와 UNIQUE 제약이 만드는 인덱스는 테이블별 컬럼의 PK, UK 표시로 확인합니다. 아래는 그 밖의 인덱스 전부입니다.", Y0, 0.4),
  });
  section("2. 테이블별 컬럼", [`테이블 ${TB.length}개의 모든 컬럼`, "NULL: N이면 NOT NULL", "기본값의 (앱)은 애플리케이션이 넣는 값", "참조: FK 제약 대상, (값만)은 제약 없이 값으로 참조"]);
  TB.forEach((t, i) => {
    const rows = t.cols.map((c, j) => {
      let ref = c.fk || "";
      if (!ref) { const m = c.desc.match(/\(([a-z_]+\.[a-z_]+) 값/) || c.desc.match(/우리 ([a-z_]+\.[a-z_]+) 값/); if (m) ref = m[1] + " (값만)"; }
      return [String(j + 1), c.name, c.type, c.null, c.key, c.default, ref];
    });
    pagedTable(`2.${i + 1} ${t.name} (${t.ko})`, ["No", "컬럼", "데이터 타입", "NULL", "키", "기본값", "참조"], rows,
      [0.5, 3.0, 1.9, 0.7, 0.9, 2.3, 3.03], {
        mono: [1, 2], firstY: Y0 + 0.4,
        onFirst: (s) => s.addText(`기본키 ${t.pk}. 행 증가: ${t.growth}. 자동 정리: ${t.cleanup}.`, { x: MX, y: Y0 - 0.05, w: CW, h: 0.38, fontSize: 12, color: C.accent3, margin: 0, valign: "top", isTextBox: true, objectName: "meta" }),
      });
  });
}

// =====================================================================
if (KIND === "tabledef") {
  cover("gaia-api-service Table 정의서", `테이블 ${TB.length}개, 컬럼 ${NCOL}개 (마이그레이션 0008까지 반영)`);
  history([["0.1", "2026-11-25", "초안 작성 (Excel)", "", ""],
           ["0.2", "2026-11-27", "PPT, Markdown 작성. 모든 컬럼에 한글명 추가. LangGraph, Alembic 테이블 정의 추가", "", ""]]);
  section("1. 개요", ["1.1 문서 정보와 표기 규칙", "1.2 테이블 목록"]);
  let s = slide("1.1 문서 정보와 표기 규칙");
  table(s, ["항목", "내용"], [
    ["시스템", "gaia-api-service (사내 데이터 분석 Agent 서비스)"],
    ["DBMS", "PostgreSQL, vector 확장(pgvector) 필요. 스키마 public"],
    ["데이터베이스", "dev: dtest / prd: dtestprd (DATABASE_URL의 마지막 부분)"],
    ["모델 정의", "src/dtest/core/models.py, src/dtest/gaia_bridge/models.py"],
    ["마이그레이션", "src/dtest/migrations/versions/ (Alembic, 0001~0008)"],
  ], [2.4, 9.93], { fontSize: 12 });
  table(s, ["표기", "규칙"], [
    ["타입", "varchar(36)은 UUID 문자열. 시각 컬럼은 모두 timestamptz이고 UTC로 저장"],
    ["NULL", "N이면 NOT NULL"],
    ["키", "PK 기본키, FK 외래키 제약, UK UNIQUE 제약"],
    ["기본값", "(앱)은 DB 기본값이 아니라 애플리케이션이 넣는 값. DB에 직접 INSERT할 때는 직접 넣어야 함"],
    ["참조", "FK 제약은 핵심 계층(사용자, 프로젝트, 세션, 메시지, run, 워크플로우)에만 있음. 나머지는 값으로만 참조"],
    ["삭제", "프로젝트, 세션, 워크플로우는 지우지 않고 deleted_at에 시각을 적음(논리 삭제)"],
  ], [2.4, 9.93], { y: 3.55, fontSize: 12 });
  tableList("1.2 테이블 목록");
  section("2. 테이블 정의", [`테이블 ${TB.length}개, 컬럼 ${NCOL}개`, "앱 테이블 19개, LangGraph와 Alembic 테이블 7개"]);
  TB.forEach((t, i) => {
    const title = `2.${i + 1} ${t.name} (${t.ko})`;
    const idx = DATA.indexes.filter(x => x.table === t.name).map(x => [x.name, x.cols, x.use]);
    const meta = [["영역", t.area], ["기본키", t.pk], ["설명", t.about || ""], ["행 증가 / 자동 정리", `${t.growth} / ${t.cleanup}`]];
    if (!idx.length) meta.push(["추가 인덱스", "없음 (기본키와 UNIQUE 제약이 만드는 인덱스만 있음)"]);
    const metaW = [2.0, 10.33];
    const mh = tableH(meta, metaW, 10.5);
    const rows = t.cols.map((c, j) => [String(j + 1), c.name, c.ko, c.type, c.null, c.key, c.default, c.desc]);
    const colW = [0.45, 2.25, 1.7, 1.35, 0.55, 0.65, 1.45, 3.93];
    const sl = pagedTable(title, ["No", "컬럼명", "한글명", "데이터 타입", "NULL", "키", "기본값", "설명"], rows, colW, {
      fontSize: 10.5, mono: [1, 3], firstY: Y0 + mh + 0.15,
      onFirst: (s) => table(s, ["항목", "내용"], meta, metaW, { fontSize: 10.5, y: Y0, name: "meta" }),
    });
    if (!idx.length) return;
    const ih = tableH(idx, [3.6, 4.4, 4.33], 10.5) + 0.35;
    let last = sl[sl.length - 1];
    let s2 = last.s, y = last.y + 0.2;
    if (y + ih > 6.95) { s2 = slide(`${title} 인덱스`); y = Y0; }
    s2.addText("추가 인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 PK, UK 컬럼 참고)", { x: MX, y, w: CW, h: 0.3, fontSize: 11, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "idx head" });
    table(s2, ["인덱스", "컬럼", "받치는 조회"], idx, [3.6, 4.4, 4.33], { y: y + 0.33, fontSize: 10.5, boldFirst: false, mono: [0] });
  });
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("slides", n);
})();
