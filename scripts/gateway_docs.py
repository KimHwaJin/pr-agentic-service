"""Build the gateway API docs from the executor's and pr-batch's OpenAPI.

The executor and batch gateways (``/api/v1/executor/{path}``,
``/api/v1/batch/{path}``) relay a fixed list of routes, so our own OpenAPI
shows only ``{path:path}``. This script takes the upstream OpenAPI of each
service, keeps the routes our allow lists open to API key callers
(``routers/executor.py`` and ``routers/batch.py`` ``_ALLOWED``), rewrites
them as we serve them (our path, our headers, our errors) and writes:

- ``docs/gateway/openapi/executor-gateway.openapi.json``
- ``docs/gateway/openapi/batch-gateway.openapi.json`` (with our own batch
  routes: ``scripts/from-notebook`` and ``/batch-reports``)
- the generated parts of the Markdown docs, between
  ``<!-- gen:begin NAME -->`` and ``<!-- gen:end NAME -->`` in
  ``docs/gateway/*.md`` (endpoint tables, schema tables, TypeScript types;
  the Korean agent guides ``*-for-agents.ko.md`` get the same types).

Run from the repo root after either service changes its API, or after our
allow lists change, and commit the result::

    # executor repo: its OpenAPI without a database
    uv run python -c "import json; \\
      from executor_service.container import ApplicationContainer; \\
      from executor_service.interfaces.http.app import create_app; \\
      from executor_service.settings import Settings; \\
      app = create_app(ApplicationContainer(Settings(runtime_enabled=False, \\
        docs_enabled=True))); print(json.dumps(app.openapi()))" > executor.json
    # pr-batch repo: docs/api/openapi.json (committed there)

    uv run python scripts/gateway_docs.py \\
      --executor executor.json --batch ../pr-batch/docs/api/openapi.json
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOCS = ROOT / "docs/gateway"
METHODS = ("get", "post", "put", "patch", "delete")
UUID = "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"
# identity headers the upstream OpenAPI declares; we make our own
UPSTREAM_IDENTITY = {
    "x-tenant-id",
    "x-user-id",
    "x-project-id",
    "x-session-id",
}
# request headers each gateway passes on (routers/*.py)
EXECUTOR_PASSED = {"content-type"}
BATCH_PASSED = {"content-type", "idempotency-key", "if-match", "accept"}

USER_HEADER = {
    "name": "X-User-Id",
    "in": "header",
    "required": True,
    "schema": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$"},
    "description": (
        "Who calls (always required, every key kind). The agentic "
        "service's tenant: one of its active users (employee id). "
        "Another tenant: an employee id (system accounts svc-...). "
        "Standard key: reads cover only this user's rows. Master key: reads "
        "cover the whole tenant. "
        "Writes are made for this user."
    ),
}
USER_QUERY = {
    "name": "user_id",
    "in": "query",
    "required": False,
    "schema": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$"},
    "description": (
        "Reads only. Master key: narrows the tenant-wide read to this user. "
        "Standard key: may only repeat X-User-Id (anything else is 403)."
    ),
}
PROJECT_HEADER = {
    "name": "X-Project-Id",
    "in": "header",
    "required": False,
    "schema": {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$",
    },
    "description": (
        "Optional project. Our tenant: a project the X-User-Id user is a "
        "member of (else 404). Another tenant: its own value, form-checked."
    ),
}
SESSION_HEADER = {
    "name": "X-Session-Id",
    "in": "header",
    "required": False,
    "schema": {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$",
    },
    "description": (
        "Optional session, needs X-Project-Id. Our tenant: a session of that "
        "project the user owns (else 404)."
    ),
}
GATEWAY_ERROR_SCHEMA = {
    "type": "object",
    "title": "GatewayError",
    "description": (
        "Every error, ours and the relayed service's: "
        '{"error": {"code", "message", "details", "context"?}}.'
    ),
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message", "details"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "array",
                                "items": {
                                    "anyOf": [
                                        {"type": "string"},
                                        {"type": "integer"},
                                    ]
                                },
                            },
                            "type": {"type": "string"},
                            "message": {"type": "string"},
                            "context": {"type": "object"},
                        },
                    },
                },
                "context": {"type": "object"},
            },
        }
    },
}
OUR_ERRORS = {
    "400": "INVALID_IDENTITY: X-User-Id missing or malformed, X-Project-Id/"
    "X-Session-Id malformed, user_id query malformed",
    "401": "LOGIN_REQUIRED (no X-Api-Key) or INVALID_API_KEY (unknown or "
    "revoked key)",
    "403": "FORBIDDEN: unknown or inactive user, or a standard key naming "
    "another user in user_id",
    "404": "NOT_FOUND: the route is not open to key callers, the resource "
    "is not visible to the caller, or (our tenant) not a member of "
    "X-Project-Id",
    "413": "TOO_LARGE: request body over 32 MB",
    "502": "Relayed service not reachable",
    "504": "Relayed service did not answer in time",
}


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sample(path: str) -> str:
    """An upstream path template with sample values, to test patterns."""
    return re.sub(
        r"\{([^}]+)\}",
        lambda m: "3" if m[1] == "cell_index" else UUID,
        path,
    )


def open_routes(
    spec: dict[str, Any], allowed: list[tuple[str, re.Pattern]]
) -> list[tuple[str, str, dict[str, Any]]]:
    """(method, upstream path, operation) of every allowed route, in the
    order of our allow list."""
    found = []
    for method, pattern in allowed:
        hits = [
            (path, item[method.lower()])
            for path, item in spec["paths"].items()
            if method.lower() in item
            and pattern.fullmatch(sample(path).removeprefix("/api/v1/"))
        ]
        if len(hits) != 1:
            raise SystemExit(
                f"{method} {pattern.pattern}: {len(hits)} upstream routes"
            )
        found.append((method, hits[0][0], hits[0][1]))
    return found


def refs(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            out.add(ref.rsplit("/", 1)[1])
        for item in value.values():
            out |= refs(item)
    elif isinstance(value, list):
        for item in value:
            out |= refs(item)
    return out


def closure(schemas: dict[str, Any], names: set[str]) -> list[str]:
    seen: set[str] = set()
    todo = sorted(names)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(sorted(refs(schemas[name]) - seen))
    return sorted(seen)


def rewrite(
    op: dict[str, Any], *, gateway: str, passed: set[str], scope: str
) -> dict[str, Any]:
    """An upstream operation as our gateway serves it."""
    op = copy.deepcopy(op)
    params = [
        p
        for p in op.get("parameters", [])
        if not (
            p["in"] == "header"
            and (
                p["name"].lower() in UPSTREAM_IDENTITY
                or p["name"].lower() not in passed
            )
        )
    ]
    params.append(USER_HEADER)
    if scope in {"executor", "registration"}:
        params.append(PROJECT_HEADER)
    if scope == "executor":
        params.append(SESSION_HEADER)
    op["parameters"] = params
    op["security"] = [{"X-Api-Key": []}]
    op["tags"] = [gateway]
    op.pop("operationId", None)
    responses = op.setdefault("responses", {})
    for status, text in OUR_ERRORS.items():
        responses.setdefault(
            status,
            {
                "description": text,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/GatewayError"}
                    }
                },
            },
        )
    for status, response in responses.items():
        content = response.get("content") or {}
        if status.startswith("2") and any(
            not item.get("schema") for item in content.values()
        ):  # a file: the type is the file's own
            response["content"] = {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        if status.startswith(("4", "5")) and "content" in response:
            response["content"] = {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/GatewayError"}
                }
            }
    return op


def add_user_query(op: dict[str, Any], method: str) -> None:
    """The ``user_id`` filter, where the upstream list takes one, with our
    rule (the key kind) as its description."""
    op["parameters"] = [
        {**USER_QUERY, "schema": p.get("schema", USER_QUERY["schema"])}
        if p["in"] == "query" and p["name"] == "user_id"
        else p
        for p in op["parameters"]
    ]


def drop_ranges(op: dict[str, Any]) -> None:
    """``Range`` is not passed on: the whole file comes back (200)."""
    for status in ("206", "416"):
        op["responses"].pop(status, None)


def build(
    title: str,
    description: str,
    routes: list[tuple[str, str, dict[str, Any]]],
    schemas: dict[str, Any],
) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for method, path, op in routes:
        paths.setdefault(path, {})[method.lower()] = op
    used = closure(schemas, refs(paths) - {"GatewayError"})
    components = {name: schemas[name] for name in used}
    components["GatewayError"] = GATEWAY_ERROR_SCHEMA
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": "1.0", "description": description},
        "servers": [
            {
                "url": "https://{api_host}",
                "description": "pr-agentic-service deployed on Kubernetes "
                "(the environment's public origin; ask the service owner)",
                "variables": {"api_host": {"default": "api-host"}},
            }
        ],
        "paths": paths,
        "components": {
            "schemas": components,
            "securitySchemes": {
                "X-Api-Key": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Api-Key",
                    "description": (
                        "A pr-agentic-service key (pas_live_... on "
                        "stg/prd, pas_dev_... on dev), issued by our "
                        "administrators. Its kind is standard or master."
                    ),
                }
            },
        },
    }


# --- Markdown ------------------------------------------------------------


def anchor(name: str) -> str:
    return "schema-" + name.lower()


def type_of(schema: dict[str, Any], link: bool = True) -> str:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[1]
        return f"[{name}](#{anchor(name)})" if link else name
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(
            json.dumps(v, ensure_ascii=False) for v in schema["enum"]
        )
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = [type_of(s, link) for s in schema[key]]
            return " | ".join(dict.fromkeys(parts))
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return type_of(schema["allOf"][0], link)
    kind = schema.get("type")
    if kind == "array":
        return type_of(schema.get("items", {}), link) + "[]"
    if kind == "object" and "additionalProperties" in schema:
        extra = schema["additionalProperties"]
        if isinstance(extra, dict) and extra:
            return f"object<string, {type_of(extra, link)}>"
        return "object"
    if isinstance(kind, list):
        return " | ".join(kind)
    fmt = schema.get("format")
    if kind == "string" and fmt in {"uuid", "date-time", "date", "binary"}:
        return f"string ({fmt})"
    return kind or "any"


def limits(schema: dict[str, Any]) -> str:
    for key in ("anyOf", "oneOf"):
        if key in schema:
            got = [limits(s) for s in schema[key]]
            return "; ".join(g for g in got if g)
    out = []
    for key, label in (
        ("minLength", "길이 ≥"),
        ("maxLength", "길이 ≤"),
        ("minimum", "≥"),
        ("exclusiveMinimum", ">"),
        ("maximum", "≤"),
        ("exclusiveMaximum", "<"),
        ("minItems", "항목 ≥"),
        ("maxItems", "항목 ≤"),
    ):
        if key in schema:
            value = schema[key]
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            out.append(f"{label} {value}")
    if "pattern" in schema:
        out.append(f"`{schema['pattern']}`")
    return ", ".join(out)


def cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def schema_table(name: str, schema: dict[str, Any]) -> str:
    lines = [f'<a id="{anchor(name)}"></a>', f"#### {name}", ""]
    if schema.get("description"):
        lines += [cell(schema["description"]), ""]
    if "enum" in schema:
        lines += ["값: " + ", ".join(f"`{v}`" for v in schema["enum"]), ""]
        return "\n".join(lines)
    if "oneOf" in schema or "anyOf" in schema:
        lines += [f"다음 중 하나: {type_of(schema)}", ""]
        if "discriminator" in schema:
            lines += [
                f"구분 필드: `{schema['discriminator']['propertyName']}`",
                "",
            ]
        return "\n".join(lines)
    props = schema.get("properties", {})
    if not props:
        lines += [f"타입: {type_of(schema)}", ""]
        return "\n".join(lines)
    required = set(schema.get("required", []))
    lines += [
        "| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for field, prop in props.items():
        default = (
            f"`{json.dumps(prop['default'], ensure_ascii=False)}`"
            if "default" in prop
            else ""
        )
        text = prop.get("description", "")
        if "discriminator" in prop:
            text = (
                f"구분 필드 `{prop['discriminator']['propertyName']}`. " + text
            )
        lines.append(
            f"| `{field}` | {cell(type_of(prop))} | "
            f"{'O' if field in required else ''} | {cell(default)} | "
            f"{cell(limits(prop))} | {cell(text)} |"
        )
    if schema.get("additionalProperties") is False:
        lines += ["", "모르는 필드는 422로 거절합니다."]
    return "\n".join(lines + [""])


def endpoint_section(method: str, path: str, op: dict[str, Any]) -> str:
    lines = [f"#### `{method} {path}`", ""]
    if op.get("summary"):
        lines += [cell(op["summary"]), ""]
    params = [
        p
        for p in op.get("parameters", [])
        if p["name"] not in {"X-User-Id", "X-Project-Id", "X-Session-Id"}
    ]
    if params:
        lines += [
            "| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for p in params:
            schema = p.get("schema", {})
            default = (
                f"`{json.dumps(schema['default'], ensure_ascii=False)}`"
                if "default" in schema
                else ""
            )
            text = p.get("description") or schema.get("description", "")
            lines.append(
                f"| {p['in']} | `{p['name']}` | {cell(type_of(schema))} | "
                f"{'O' if p.get('required') else ''} | {cell(default)} | "
                f"{cell(limits(schema))} | {cell(text)} |"
            )
        lines.append("")
    body = op.get("requestBody")
    if body:
        for media, content in body.get("content", {}).items():
            lines.append(
                f"- 요청 본문 (`{media}`): "
                f"{type_of(content.get('schema', {}))}"
            )
    for status, response in op.get("responses", {}).items():
        if not status.startswith("2"):
            continue
        content = response.get("content") or {}
        if not content:
            lines.append(f"- 응답 `{status}`: 본문 없음")
        for media, item in content.items():
            schema = item.get("schema", {})
            shown = type_of(schema) if schema else "파일 바이트 (스트리밍)"
            lines.append(f"- 응답 `{status}` (`{media}`): {shown}")
    upstream_errors = [
        f"`{s}`"
        for s, r in op.get("responses", {}).items()
        if s[0] in "45" and s not in OUR_ERRORS and s != "422"
    ]
    if upstream_errors:
        lines.append("- 이 경로의 그 밖의 오류: " + ", ".join(upstream_errors))
    return "\n".join(lines + [""])


def endpoints_md(spec: dict[str, Any]) -> str:
    out = []
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method in item:
                out.append(
                    endpoint_section(method.upper(), path, item[method])
                )
    return "\n".join(out)


def schemas_md(spec: dict[str, Any], skip: set[str]) -> str:
    schemas = spec["components"]["schemas"]
    return "\n".join(
        schema_table(name, schemas[name])
        for name in sorted(schemas)
        if name not in skip
    )


def summary_md(spec: dict[str, Any]) -> str:
    lines = [
        "| # | Method | Path | 요청 본문 | 성공 응답 |",
        "| --- | --- | --- | --- | --- |",
    ]
    n = 0
    for path, item in spec["paths"].items():
        for method in METHODS:
            if method not in item:
                continue
            op = item[method]
            n += 1
            body = ", ".join(
                type_of(c.get("schema", {}), link=False)
                for c in (op.get("requestBody") or {})
                .get("content", {})
                .values()
            )
            ok = ", ".join(
                f"{s} {response_type(r)}".strip()
                for s, r in op["responses"].items()
                if s.startswith("2")
            )
            lines.append(
                f"| {n} | {method.upper()} | `{path}` | {cell(body) or '-'} | "
                f"{cell(ok)} |"
            )
    return "\n".join(lines)


# --- TypeScript (agent docs) -------------------------------------------


def ts_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[1]
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return " | ".join(dict.fromkeys(ts_type(s) for s in schema[key]))
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return ts_type(schema["allOf"][0])
    kind = schema.get("type")
    if kind == "array":
        inner = ts_type(schema.get("items", {}))
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if kind == "object":
        return "Record<string, unknown>"
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind or "", "unknown")


def ts_md(spec: dict[str, Any], skip: set[str]) -> str:
    out = ["```ts"]
    schemas = spec["components"]["schemas"]
    # request bodies refuse unknown fields; responses may gain fields
    sent = set(
        closure(
            schemas,
            refs(
                [
                    op.get("requestBody", {})
                    for item in spec["paths"].values()
                    for op in item.values()
                    if isinstance(op, dict)
                ]
            ),
        )
    )
    for name in sorted(schemas):
        if name in skip:
            continue
        schema = schemas[name]
        props = schema.get("properties")
        if not props:
            out.append(f"type {name} = {ts_type(schema)};")
            continue
        required = set(schema.get("required", []))
        note = (
            " // unknown fields → 422"
            if schema.get("additionalProperties") is False and name in sent
            else ""
        )
        out.append(f"interface {name} {{{note}")
        for field, prop in props.items():
            extra = limits(prop)
            if "default" in prop:
                value = json.dumps(prop["default"], ensure_ascii=False)
                extra = f"default {value}" + (f"; {extra}" if extra else "")
            comment = f" // {extra}" if extra else ""
            mark = "" if field in required else "?"
            out.append(f"  {field}{mark}: {ts_type(prop)};{comment}")
        out.append("}")
    out.append("```")
    return "\n".join(out)


def response_type(response: dict[str, Any]) -> str:
    """The type of a response's first content, or empty."""
    if not response.get("content"):
        return ""
    schema = next(iter(response["content"].values())).get("schema", {})
    return type_of(schema, link=False)


def fill(path: Path, parts: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for name, body in parts.items():
        pattern = re.compile(
            rf"(<!-- gen:begin {name} -->\n).*?(<!-- gen:end {name} -->)",
            re.S,
        )
        if not pattern.search(text):
            raise SystemExit(f"{path.name}: no gen block {name}")
        text = pattern.sub(
            lambda m, body=body: m[1] + body.strip() + "\n" + m[2], text
        )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--executor", required=True, help="executor OpenAPI")
    parser.add_argument("--batch", required=True, help="pr-batch OpenAPI")
    args = parser.parse_args()

    from fastapi import FastAPI

    from src.dtest.api_service.app import mount_api
    from src.dtest.api_service.routers import batch, executor
    from src.dtest.core.config import get_settings

    ours_app = FastAPI(title="pr-agentic-service", version="0.1.0")
    mount_api(ours_app, get_settings())
    ours = ours_app.openapi()

    # executor
    upstream = load(args.executor)
    keyed = [(m, p) for m, p, _, key in executor.ROUTES if key]
    routes = []
    for method, path, op in open_routes(upstream, keyed):
        op = rewrite(
            op, gateway="executor", passed=EXECUTOR_PASSED, scope="executor"
        )
        add_user_query(op, method)
        drop_ranges(op)
        routes.append(
            (method, path.replace("/api/v1/", "/api/v1/executor/", 1), op)
        )
    exec_spec = build(
        "pr-agentic-service executor gateway",
        "executor /api/v1/<path> through pr-agentic-service as "
        "/api/v1/executor/<path>. Only these routes are open to API key "
        "callers; any other path is 404. See "
        "docs/gateway/executor-gateway.md.",
        routes,
        upstream["components"]["schemas"],
    )

    # pr-batch, then our own batch routes
    upstream = load(args.batch)
    routes = []
    for method, path, op in open_routes(upstream, batch.ROUTES):
        tail = path.removeprefix("/api/v1/")
        scope = "registration" if batch.registers(method, tail) else "batch"
        op = rewrite(op, gateway="batch", passed=BATCH_PASSED, scope=scope)
        add_user_query(op, method)
        routes.append(
            (method, path.replace("/api/v1/", "/api/v1/batch/", 1), op)
        )
    schemas = dict(upstream["components"]["schemas"])
    own = {
        p: item
        for p, item in ours["paths"].items()
        if p == "/api/v1/batch/scripts/from-notebook"
        or p.startswith("/api/v1/batch-reports")
    }
    renamed = {}
    for name in closure(ours["components"]["schemas"], refs(own)):
        new = name if name not in schemas else f"Agentic{name}"
        renamed[name] = new
        schemas[new] = ours["components"]["schemas"][name]
    text = json.dumps(own)
    for old, new in renamed.items():
        text = text.replace(f'schemas/{old}"', f'schemas/{new}"')
    for path, item in json.loads(text).items():
        for method, op in item.items():
            op = copy.deepcopy(op)
            # identity headers are ours to describe; Idempotency-Key
            # (from-notebook) is the caller's, as on the relayed writes
            op["parameters"] = [
                p
                for p in op.get("parameters", [])
                if p["in"] != "header"
                or p["name"].lower() == "idempotency-key"
            ] + [{**USER_HEADER, "description": OUR_USER_DESCRIPTION}]
            op["security"] = [{"X-Api-Key": []}]
            op["tags"] = ["batch (pr-agentic-service)"]
            op.pop("operationId", None)
            for status, text_ in OUR_ERRORS.items():
                op["responses"].setdefault(
                    status,
                    {
                        "description": text_,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/GatewayError"
                                }
                            }
                        },
                    },
                )
            op["responses"].pop("422", None)
            op["responses"]["422"] = {
                "description": "INVALID_BODY",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/GatewayError"}
                    }
                },
            }
            # our routes return pr-batch's body (from-notebook) or an event
            # stream; their own OpenAPI says only "any"
            ok = op["responses"].get("201") or op["responses"].get("200")
            if path.endswith("/from-notebook") and ok:
                ok["content"] = {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ScriptView"}
                    }
                }
            if path.endswith("/stream") and ok:
                ok["description"] = (
                    "Server-sent events: stored events, then live ones"
                )
                ok["content"] = {
                    "text/event-stream": {"schema": {"type": "string"}}
                }
            routes.append((method.upper(), path, op))
    batch_spec = build(
        "pr-agentic-service batch gateway",
        "pr-batch /api/v1/<path> through pr-agentic-service as "
        "/api/v1/batch/<path>, plus this service's own batch routes "
        "(scripts/from-notebook, batch-reports). Any other /api/v1/batch "
        "path is 404. See docs/gateway/batch-gateway.md.",
        routes,
        schemas,
    )

    out = DOCS / "openapi"
    out.mkdir(parents=True, exist_ok=True)
    for name, spec in (
        ("executor-gateway", exec_spec),
        ("batch-gateway", batch_spec),
    ):
        (out / f"{name}.openapi.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    skip = {"GatewayError", "HTTPValidationError", "ValidationError"}
    fill(
        DOCS / "executor-gateway.md",
        {
            "summary": summary_md(exec_spec),
            "endpoints": endpoints_md(exec_spec),
            "schemas": schemas_md(exec_spec, skip),
        },
    )
    fill(
        DOCS / "batch-gateway.md",
        {
            "summary": summary_md(batch_spec),
            "endpoints": endpoints_md(batch_spec),
            "schemas": schemas_md(batch_spec, skip),
        },
    )
    exec_types = {"types": ts_md(exec_spec, skip)}
    batch_types = {"types": ts_md(batch_spec, skip)}
    for suffix in (".md", ".ko.md"):  # English and Korean guides
        fill(DOCS / f"executor-for-agents{suffix}", exec_types)
        fill(DOCS / f"batch-for-agents{suffix}", batch_types)
    print(
        f"executor: {len(exec_spec['paths'])} paths, "
        f"batch: {len(batch_spec['paths'])} paths"
    )


OUR_USER_DESCRIPTION = (
    "One of our active users (users.id or employee id). These routes are "
    "this service's own and need a user of our tenant."
)


if __name__ == "__main__":
    main()
