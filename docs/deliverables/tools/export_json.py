"""Dump the schema and the doc tables the ERD decks need into JSON."""
import json, os, re, sys
sys.argv = sys.argv[:1]  # gen_md가 산출물 폴더(../)를 그대로 갱신한다
import gen_md as G

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..") + os.sep


def md_table(path, heading):
    text = open(path, encoding="utf-8").read()
    sec = text[text.index(heading):]
    rows = []
    for ln in sec.splitlines()[1:]:
        if ln.startswith("#"):
            if rows:
                break
            continue
        if ln.startswith("|"):
            c = [x.strip().replace("`", "") for x in ln.strip().strip("|").split("|")]
            if set("".join(c)) <= set("- "):
                continue
            rows.append(c)
        elif rows:
            break
    return rows


tables = []
for n in G.ALL:
    t = G.T[n]
    tables.append(dict(name=n, ko=t["ko"], area=t["area"], pk=t["pk"], growth=t["growth"], cleanup=t["cleanup"],
                       no=t["no"], about=G.about(n), group=t["group"],
                       cols=[{k: c[k] for k in ("name", "ko", "type", "null", "key", "default", "desc", "fk")} for c in t["cols"]]))
out = dict(tables=tables, indexes=G.IDX,
           areas=md_table(D + "04-erd-logical.md", "## 2. 데이터 영역"),
           rels=md_table(D + "04-erd-logical.md", "## 5. 관계와 카디널리티"),
           dbconf=md_table(D + "05-erd-physical.md", "## 1. DB 구성"),
           overview=md_table(D + "04-erd-logical.md", "## 1. 개요"))
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "erd_data.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(tables), len(out["rels"]), len(out["dbconf"]), len(out["areas"]))
