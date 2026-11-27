"""Tiny diagram model that writes both a .drawio file and an SVG preview.

Every edge carries explicit waypoints, so the SVG matches what draw.io draws.
"""
from __future__ import annotations

import html
import math
from xml.sax.saxutils import quoteattr

KINDS = {
    "ours": ("#dae8fc", "#6c8ebf"),
    "related": ("#d5e8d4", "#82b366"),
    "infra": ("#f5f5f5", "#666666"),
    "store": ("#fff2cc", "#d6b656"),
    "caller": ("#ffe6cc", "#d79b00"),
    "note": ("#ffffff", "#999999"),
    "group": ("#f4f8fd", "#6c8ebf"),
    "group2": ("#fafafa", "#999999"),
    "state": ("#e1d5e7", "#9673a6"),
    "warn": ("#f8cecc", "#b85450"),
}
FONT = "Helvetica"
SVG_FONT = "'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic','WenQuanYi Zen Hei',sans-serif"


def tw(text: str, size: float) -> float:
    w = 0.0
    for ch in text:
        w += size * (0.92 if ord(ch) > 0x2E80 else 0.56)
    return w


class Page:
    def __init__(self, name: str, w: int, h: int, title: str = ""):
        self.name, self.w, self.h, self.title = name, w, h, title
        self.nodes: dict[str, dict] = {}
        self.order: list[str] = []
        self.edges: list[dict] = []

    # ---- model
    def node(self, id, label, x, y, w, h, kind="ours", shape="rect", sub="",
             size=13, align="center"):
        self.nodes[id] = dict(id=id, label=label, sub=sub, x=x, y=y, w=w, h=h,
                              kind=kind, shape=shape, size=size, align=align)
        self.order.append(id)

    def group(self, id, label, x, y, w, h, kind="group", align="left"):
        self.node(id, label, x, y, w, h, kind=kind, shape="group", align=align)

    def text(self, id, label, x, y, w, h, size=11, align="left", bold=False):
        self.node(id, label, x, y, w, h, kind="note", shape="text", size=size,
                  align=align)
        self.nodes[id]["bold"] = bold

    ROW = 18
    HEAD = 26

    def table(self, id, title, rows, x, y, w=240, sub="", kind="ours"):
        """rows: (mark, name, type). mark is '', 'PK', 'FK', 'PK,FK', 'UK'."""
        h = self.HEAD + (16 if sub else 0) + self.ROW * len(rows) + 6
        self.node(id, title, x, y, w, h, kind=kind, shape="table", sub=sub, size=12)
        self.nodes[id]["rows"] = rows
        return y + h

    def pt(self, id, side, f=0.5):
        n = self.nodes[id]
        if side == "t":
            return (n["x"] + n["w"] * f, n["y"])
        if side == "b":
            return (n["x"] + n["w"] * f, n["y"] + n["h"])
        if side == "l":
            return (n["x"], n["y"] + n["h"] * f)
        return (n["x"] + n["w"], n["y"] + n["h"] * f)

    def edge(self, a, b, label="", ex=("b", 0.5), en=("t", 0.5), via=None,
             dashed=False, both=False, t=0.5, mid=None, color="#333333", er=None):
        s, e = self.pt(a, *ex), self.pt(b, *en)
        if via is None:
            via = []
            vs, ve = ex[0] in "tb", en[0] in "tb"
            if vs and ve:
                if abs(s[0] - e[0]) > 0.5:
                    m = mid if mid is not None else (s[1] + e[1]) / 2
                    via = [(s[0], m), (e[0], m)]
            elif not vs and not ve:
                if abs(s[1] - e[1]) > 0.5:
                    m = mid if mid is not None else (s[0] + e[0]) / 2
                    via = [(m, s[1]), (m, e[1])]
            elif vs and not ve:
                via = [(s[0], e[1])]
            else:
                via = [(e[0], s[1])]
        self.edges.append(dict(a=a, b=b, label=label, ex=ex, en=en,
                               pts=[s] + list(via) + [e], dashed=dashed,
                               both=both, t=t, color=color, er=er))

    # ---- geometry helpers
    @staticmethod
    def along(pts, t):
        segs = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(segs) or 1
        d = total * t
        for i, L in enumerate(segs):
            if d <= L or i == len(segs) - 1:
                r = d / L if L else 0
                return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * r,
                        pts[i][1] + (pts[i + 1][1] - pts[i][1]) * r)
            d -= L

    # ---- draw.io
    def drawio(self, pid: str) -> str:
        out = [f'<diagram id="{pid}" name={quoteattr(self.name)}>',
               f'<mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" '
               f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
               f'pageWidth="{self.w}" pageHeight="{self.h}" math="0" shadow="0">',
               '<root><mxCell id="0"/><mxCell id="1" parent="0"/>']
        if self.title:
            out.append(self._cell(f"{pid}-title", f"<b>{html.escape(self.title)}</b>",
                                  "text;html=1;align=left;verticalAlign=middle;fontSize=18;"
                                  f"fontFamily={FONT};", 40, 16, 900, 30))
        for nid in self.order:
            n = self.nodes[nid]
            fill, stroke = KINDS[n["kind"]]
            lab = "<b>%s</b>" % html.escape(n["label"]).replace("\n", "<br>")
            if n["sub"]:
                lab += ('<br><font style="font-size:%dpx">%s</font>'
                        % (n["size"] - 2, html.escape(n["sub"]).replace("\n", "<br>")))
            base = f"html=1;whiteSpace=wrap;fontFamily={FONT};fontSize={n['size']};"
            if n["shape"] == "table":
                head = self.HEAD + (16 if n["sub"] else 0)
                st = (f"swimlane;html=1;whiteSpace=wrap;fontFamily={FONT};fontSize=12;fontStyle=1;"
                      f"startSize={head};fillColor={fill};strokeColor={stroke};"
                      "swimlaneFillColor=#ffffff;collapsible=0;rounded=1;arcSize=6;")
                out.append(self._cell(f"{pid}-{nid}", lab, st, n["x"], n["y"], n["w"], n["h"]))
                for ri, (mark, nm, typ) in enumerate(n["rows"]):
                    v = (f'<b>{mark}</b>&nbsp;' if mark else "") + html.escape(nm)
                    if typ:
                        v += f'&nbsp;&nbsp;<font color="#888888">{html.escape(typ)}</font>'
                    out.append(
                        f'<mxCell id="{pid}-{nid}-r{ri}" value={quoteattr(v)} '
                        f'style="text;html=1;align=left;verticalAlign=middle;spacingLeft=6;'
                        f'fontFamily={FONT};fontSize=11;overflow=hidden;connectable=0;" vertex="1" '
                        f'parent="{pid}-{nid}"><mxGeometry y="{head + 2 + ri * self.ROW}" '
                        f'width="{n["w"]}" height="{self.ROW}" as="geometry"/></mxCell>')
                continue
            if n["shape"] == "group":
                st = (base + f"rounded=1;arcSize=3;dashed=1;fillColor={fill};"
                      f"strokeColor={stroke};verticalAlign=top;align={n['align']};"
                      "spacingLeft=10;spacingRight=10;spacingTop=4;")
            elif n["shape"] == "cyl":
                st = (base + "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=10;"
                      f"fillColor={fill};strokeColor={stroke};")
            elif n["shape"] == "text":
                lab = html.escape(n["label"]).replace("\n", "<br>")
                if n.get("bold"):
                    lab = f"<b>{lab}</b>"
                st = (f"text;html=1;whiteSpace=wrap;fontFamily={FONT};"
                      f"fontSize={n['size']};align={n['align']};verticalAlign=middle;")
            elif n["shape"] == "round":
                st = base + f"rounded=1;arcSize=40;fillColor={fill};strokeColor={stroke};"
            elif n["shape"] == "diamond":
                st = base + f"rhombus;fillColor={fill};strokeColor={stroke};"
            else:
                st = (base + f"rounded=1;arcSize=8;fillColor={fill};strokeColor={stroke};"
                      f"align={n['align']};" + ("spacingLeft=8;" if n["align"] == "left" else ""))
            out.append(self._cell(f"{pid}-{nid}", lab, st, n["x"], n["y"], n["w"], n["h"]))
        for i, e in enumerate(self.edges):
            a, b = self.nodes[e["a"]], self.nodes[e["b"]]
            s, t_ = e["pts"][0], e["pts"][-1]
            fx = lambda p, n: ((p[0] - n["x"]) / n["w"], (p[1] - n["y"]) / n["h"])
            (ex_, ey_), (nx_, ny_) = fx(s, a), fx(t_, b)
            st = (f"edgeStyle=none;rounded=0;html=1;endArrow=block;endFill=1;"
                  f"strokeColor={e['color']};fontFamily={FONT};fontSize=11;"
                  f"exitX={ex_:.3f};exitY={ey_:.3f};exitDx=0;exitDy=0;"
                  f"entryX={nx_:.3f};entryY={ny_:.3f};entryDx=0;entryDy=0;")
            if e["er"]:
                st = st.replace("endArrow=block;endFill=1;",
                                "endArrow=ERmandOne;endFill=0;endSize=10;startSize=10;"
                                + ("startArrow=ERzeroToMany;startFill=0;" if e["er"] == "many"
                                   else "startArrow=ERzeroToOne;startFill=0;"))
            if e["both"]:
                st += "startArrow=block;startFill=1;"
            if e["dashed"]:
                st += "dashed=1;"
            eid = f"{pid}-e{i}"
            pts = "".join(f'<mxPoint x="{p[0]:.0f}" y="{p[1]:.0f}"/>' for p in e["pts"][1:-1])
            arr = f'<Array as="points">{pts}</Array>' if pts else ""
            out.append(f'<mxCell id="{eid}" style="{st}" edge="1" parent="1" '
                       f'source="{pid}-{e["a"]}" target="{pid}-{e["b"]}">'
                       f'<mxGeometry relative="1" as="geometry">{arr}</mxGeometry></mxCell>')
            if e["label"]:
                lab = html.escape(e["label"]).replace("\n", "<br>")
                out.append(f'<mxCell id="{eid}-l" value={quoteattr(lab)} '
                           f'style="edgeLabel;html=1;align=center;verticalAlign=middle;'
                           f'resizable=0;points=[];fontFamily={FONT};fontSize=11;'
                           f'labelBackgroundColor=#ffffff;" vertex="1" connectable="0" '
                           f'parent="{eid}"><mxGeometry x="{2 * e["t"] - 1:.3f}" relative="1" '
                           f'as="geometry"><mxPoint as="offset"/></mxGeometry></mxCell>')
        out.append("</root></mxGraphModel></diagram>")
        return "\n".join(out)

    @staticmethod
    def _cell(cid, value, style, x, y, w, h):
        return (f'<mxCell id="{cid}" value={quoteattr(value)} style="{style}" vertex="1" '
                f'parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
                f'as="geometry"/></mxCell>')

    # ---- svg
    def svg(self) -> str:
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
             f'viewBox="0 0 {self.w} {self.h}" font-family="{SVG_FONT}">',
             '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
             'markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
             'fill="#333"/></marker></defs>',
             f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>']
        if self.title:
            o.append(f'<text x="40" y="38" font-size="18" font-weight="bold">'
                     f'{html.escape(self.title)}</text>')
        for nid in self.order:
            n = self.nodes[nid]
            fill, stroke = KINDS[n["kind"]]
            x, y, w, h = n["x"], n["y"], n["w"], n["h"]
            if n["shape"] == "group":
                o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" '
                         f'stroke="{stroke}" stroke-dasharray="6 4"/>')
                gx, ga = ((x + w - 12, "end") if n["align"] == "right" else (x + 12, "start"))
                o.append(f'<text x="{gx}" y="{y + 20}" font-size="{n["size"]}" '
                         f'text-anchor="{ga}" font-weight="bold">{html.escape(n["label"])}</text>')
                continue
            if n["shape"] == "table":
                head = self.HEAD + (16 if n["sub"] else 0)
                o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="#ffffff" '
                         f'stroke="{stroke}"/>')
                o.append(f'<path d="M{x},{y + head} v{-(head - 5)} a5,5 0 0 1 5,-5 h{w - 10} '
                         f'a5,5 0 0 1 5,5 v{head - 5} z" fill="{fill}" stroke="{stroke}"/>')
                o.append(f'<text x="{x + w / 2}" y="{y + 17}" font-size="12" font-weight="bold" '
                         f'text-anchor="middle">{html.escape(n["label"])}</text>')
                if n["sub"]:
                    o.append(f'<text x="{x + w / 2}" y="{y + 33}" font-size="10" '
                             f'text-anchor="middle">{html.escape(n["sub"])}</text>')
                for ri, (mark, nm, typ) in enumerate(n["rows"]):
                    ry = y + head + 2 + ri * self.ROW + 13
                    tx = x + 8
                    if mark:
                        o.append(f'<text x="{tx}" y="{ry}" font-size="10" font-weight="bold">'
                                 f'{mark}</text>')
                        tx += tw(mark, 10) + 8
                    o.append(f'<text x="{tx}" y="{ry}" font-size="11">{html.escape(nm)}</text>')
                    if typ:
                        o.append(f'<text x="{tx + tw(nm, 11) + 10}" y="{ry}" font-size="11" '
                                 f'fill="#888888">{html.escape(typ)}</text>')
                continue
            if n["shape"] == "text":
                lines = n["label"].split("\n")
                lh = n["size"] * 1.35
                y0 = y + h / 2 - lh * (len(lines) - 1) / 2 + n["size"] * 0.35
                anchor, tx = (("middle", x + w / 2) if n["align"] == "center" else ("start", x))
                for i, ln in enumerate(lines):
                    o.append(f'<text x="{tx}" y="{y0 + i * lh:.1f}" font-size="{n["size"]}" '
                             f'text-anchor="{anchor}"'
                             + (' font-weight="bold"' if n.get("bold") else "")
                             + f'>{html.escape(ln)}</text>')
                continue
            if n["shape"] == "cyl":
                r = 10
                o.append(f'<path d="M{x},{y + r} a{w / 2},{r} 0 0 1 {w},0 v{h - 2 * r} '
                         f'a{w / 2},{r} 0 0 1 {-w},0 z" fill="{fill}" stroke="{stroke}"/>')
                o.append(f'<path d="M{x},{y + r} a{w / 2},{r} 0 0 0 {w},0" fill="none" '
                         f'stroke="{stroke}"/>')
                cy = y + h / 2 + r / 2
            elif n["shape"] == "diamond":
                o.append(f'<path d="M{x + w / 2},{y} L{x + w},{y + h / 2} L{x + w / 2},{y + h} '
                         f'L{x},{y + h / 2} z" fill="{fill}" stroke="{stroke}"/>')
                cy = y + h / 2
            else:
                rx = min(h / 2, 20) if n["shape"] == "round" else 6
                o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                         f'fill="{fill}" stroke="{stroke}"/>')
                cy = y + h / 2
            lines = [(ln, True, n["size"]) for ln in n["label"].split("\n")]
            if n["sub"]:
                lines += [(ln, False, n["size"] - 2) for ln in n["sub"].split("\n")]
            lh = n["size"] * 1.35
            y0 = cy - lh * (len(lines) - 1) / 2 + n["size"] * 0.35
            anchor, tx = (("middle", x + w / 2) if n["align"] == "center" else ("start", x + 10))
            for i, (ln, bold, sz) in enumerate(lines):
                o.append(f'<text x="{tx}" y="{y0 + i * lh:.1f}" font-size="{sz}" '
                         f'text-anchor="{anchor}"' + (' font-weight="bold"' if bold else "")
                         + f'>{html.escape(ln)}</text>')
        for e in self.edges:
            d = "M" + " L".join(f"{p[0]:.1f},{p[1]:.1f}" for p in e["pts"])
            if e["er"]:
                o.append(f'<path d="{d}" fill="none" stroke="{e["color"]}" stroke-width="1.2"'
                         + (' stroke-dasharray="5 4"' if e["dashed"] else "") + "/>")
                o.append(self._er(e["pts"][0], e["pts"][1], e["er"], e["color"]))
                o.append(self._er(e["pts"][-1], e["pts"][-2], "one1", e["color"]))
                continue
            o.append(f'<path d="{d}" fill="none" stroke="{e["color"]}" stroke-width="1.2" '
                     'marker-end="url(#arr)"'
                     + (' marker-start="url(#arr)"' if e["both"] else "")
                     + (' stroke-dasharray="5 4"' if e["dashed"] else "") + "/>")
        for e in self.edges:
            if not e["label"]:
                continue
            cx, cy = self.along(e["pts"], e["t"])
            lines = e["label"].split("\n")
            w = max(tw(ln, 11) for ln in lines) + 6
            h = 14 * len(lines) + 2
            o.append(f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" width="{w:.1f}" '
                     f'height="{h}" fill="#ffffff"/>')
            for i, ln in enumerate(lines):
                o.append(f'<text x="{cx:.1f}" y="{cy - h / 2 + 12 + i * 14:.1f}" font-size="11" '
                         f'text-anchor="middle" fill="#222">{html.escape(ln)}</text>')
        o.append("</svg>")
        return "\n".join(o)


def _er(self, p, q, kind, color):
    """ER end marker at p, line heading toward q."""
    L = math.dist(p, q) or 1
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    nx, ny = -uy, ux
    P = lambda a, b: f"{p[0] + ux * a + nx * b:.1f},{p[1] + uy * a + ny * b:.1f}"
    st = f'fill="none" stroke="{color}" stroke-width="1.2"'
    if kind == "one1":  # exactly one: two bars
        return (f'<path d="M{P(6, -5)} L{P(6, 5)} M{P(10, -5)} L{P(10, 5)}" {st}/>')
    out = f'<circle cx="{p[0] + ux * 14:.1f}" cy="{p[1] + uy * 14:.1f}" r="3.5" fill="#fff" stroke="{color}"/>'
    if kind == "many":
        out += f'<path d="M{P(10, 0)} L{P(0, -5)} M{P(10, 0)} L{P(0, 5)}" {st}/>'
    else:
        out += f'<path d="M{P(6, -5)} L{P(6, 5)}" {st}/>'
    return out


Page._er = _er


def write(pages: list[Page], stem: str, outdir: str):
    import os
    import cairosvg
    os.makedirs(os.path.join(outdir, "export"), exist_ok=True)
    body = "\n".join(p.drawio(f"p{i + 1}") for i, p in enumerate(pages))
    with open(os.path.join(outdir, stem + ".drawio"), "w", encoding="utf-8") as f:
        f.write('<mxfile host="app.diagrams.net" agent="gaia-api-service docs" '
                f'version="24.7.17">\n{body}\n</mxfile>\n')
    for i, p in enumerate(pages):
        base = os.path.join(outdir, "export", f"{stem}-{i + 1}")
        svg = p.svg()
        with open(base + ".svg", "w", encoding="utf-8") as f:
            f.write(svg)
        cairosvg.svg2png(bytestring=svg.replace(SVG_FONT, 'Noto Sans KR Thin').encode(), write_to=base + ".png", scale=1.5)
