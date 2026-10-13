"""Throughput check against a running service (use scripts/mock_llm.py to isolate the service).

    uv run python scripts/loadtest.py --users 50 --turns 3 [--base http://localhost:8080]

Each virtual user logs in (dev SSO), keeps one SSE stream open and sends chat turns one after
another, waiting for ``message_final``. Reports turn throughput and latency percentiles, plus
read-API throughput (GET /users/me) under the same load.
"""

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def user(base: str, turns: int, latencies: list[float], errors: list[str]) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=120) as client:
        await client.get("/api/v1/auth/login/sso")
        client.headers["X-CSRF-Token"] = (await client.get("/api/v1/auth/session")).json()["csrf_token"]
        project = (await client.get("/api/v1/users/me")).json()["default_project_id"]
        session = (await client.post(f"/api/v1/projects/{project}/sessions", json={"title": "load"})).json()["session"]["id"]
        finals: asyncio.Queue = asyncio.Queue()

        async def listen():
            async with client.stream("GET", f"/api/v1/sessions/{session}/events", timeout=None) as r:
                async for line in r.aiter_lines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        if event["type"] in {"message_final", "run_error"}:
                            await finals.put(event)

        listener = asyncio.create_task(listen())
        await asyncio.sleep(0.2)
        for i in range(turns):
            started = time.perf_counter()
            r = await client.post(f"/api/v1/sessions/{session}/messages", json={"content": f"안녕 {i}"})
            if r.status_code != 202:
                errors.append(f"send {r.status_code}")
                continue
            event = await asyncio.wait_for(finals.get(), 120)
            if event["type"] == "run_error":
                errors.append(event["data"]["message"][:80])
            latencies.append(time.perf_counter() - started)
        listener.cancel()


async def reads(base: str, seconds: float) -> int:
    count = 0
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        await client.get("/api/v1/auth/login/sso")
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            await client.get("/api/v1/users/me")
            count += 1
    return count


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--readers", type=int, default=10)
    args = parser.parse_args()
    latencies: list[float] = []
    errors: list[str] = []
    started = time.perf_counter()
    chat = asyncio.gather(*(user(args.base, args.turns, latencies, errors) for _ in range(args.users)))
    read_counts = asyncio.gather(*(reads(args.base, 10) for _ in range(args.readers)))
    _, counts = await asyncio.gather(chat, read_counts)
    elapsed = time.perf_counter() - started
    q = statistics.quantiles(latencies, n=100) if len(latencies) > 1 else [0] * 99
    print(f"turns {len(latencies)} in {elapsed:.1f}s -> {len(latencies) / elapsed:.1f} turns/s")
    print(f"turn latency p50 {q[49]:.2f}s p95 {q[94]:.2f}s max {max(latencies):.2f}s")
    print(f"read API {sum(counts) / 10:.0f} req/s with {args.readers} readers during chat load")
    print(f"errors {len(errors)} {errors[:3]}")


asyncio.run(main())
