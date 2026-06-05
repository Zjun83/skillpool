#!/usr/bin/env python3
"""Stress test for SkillPool MCP HTTP endpoints.

Usage:
    python tests/stress_test_http.py --target http://localhost:8101/mcp --concurrency 10,50,100,200

Part of SkillPool — independent infrastructure, shared by all agents.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import httpx


async def mcp_request(
    client: httpx.AsyncClient,
    method: str,
    params: dict | None,
    session_id: str | None,
    auth_key: str | None,
) -> tuple[float, int]:
    """Send MCP request and return (elapsed_seconds, status_code)."""
    payload = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params:
        payload["params"] = params

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    start = time.monotonic()
    try:
        resp = await client.post(
            MCP_URL,
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        elapsed = time.monotonic() - start
        return elapsed, resp.status_code
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"Request error: {e}")
        return elapsed, 0


async def get_session(client: httpx.AsyncClient, auth_key: str | None) -> str | None:
    """Initialize MCP session and return session ID."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "id": 1,
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "stress-test", "version": "1.0"},
        },
    }

    try:
        resp = await client.post(MCP_URL, json=payload, headers=headers, timeout=10.0)
        # Extract session ID from response headers
        session_id = resp.headers.get("mcp-session-id")
        return session_id
    except Exception as e:
        print(f"Failed to get session: {e}")
        return None


async def run_level(
    concurrency: int,
    duration_s: int,
    auth_key: str | None,
    test_type: str = "resource_read",
) -> dict:
    """Run stress test at given concurrency level."""
    results = {"latencies": [], "errors": 0, "total": 0}

    async with httpx.AsyncClient() as client:
        # Get session
        session_id = await get_session(client, auth_key)
        if not session_id:
            print("ERROR: Could not get MCP session")
            return results

        # Choose test method
        if test_type == "resource_read":
            method = "resources/read"
            params = {"uri": "skill://list"}
        else:
            method = "tools/call"
            params = {"name": "skill_search", "arguments": {"intent": "code review"}}

        # Run for duration
        start_time = time.monotonic()
        tasks = []

        while time.monotonic() - start_time < duration_s:
            # Limit concurrent tasks
            while len(tasks) >= concurrency:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    elapsed, status = task.result()
                    results["latencies"].append(elapsed)
                    results["total"] += 1
                    if status != 200:
                        results["errors"] += 1
                tasks = list(_)

            # Spawn new task
            task = asyncio.create_task(mcp_request(client, method, params, session_id, auth_key))
            tasks.append(task)

        # Wait for remaining tasks
        for task in asyncio.as_completed(tasks):
            elapsed, status = await task
            results["latencies"].append(elapsed)
            results["total"] += 1
            if status != 200:
                results["errors"] += 1

    return results


def print_stats(level: int, results: dict) -> None:
    """Print statistics for a concurrency level."""
    latencies = results["latencies"]
    if not latencies:
        print(f"  Level {level}: No results")
        return

    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
    error_rate = results["errors"] / results["total"] * 100 if results["total"] > 0 else 0

    print(
        f"  Level {level}: {results['total']} requests, "
        f"P50={p50*1000:.1f}ms, P95={p95*1000:.1f}ms, P99={p99*1000:.1f}ms, "
        f"errors={error_rate:.2f}%"
    )


MCP_URL = "http://localhost:8101/mcp"


async def main():
    parser = argparse.ArgumentParser(description="Stress test SkillPool MCP HTTP")
    parser.add_argument("--target", default="http://localhost:8101/mcp", help="MCP endpoint URL")
    parser.add_argument("--concurrency", default="10,50,100", help="Comma-separated concurrency levels")
    parser.add_argument("--duration", type=int, default=10, help="Duration per level in seconds")
    parser.add_argument("--auth-key", help="API key for authentication")
    parser.add_argument("--type", choices=["resource_read", "tool_call"], default="resource_read")
    args = parser.parse_args()

    global MCP_URL
    MCP_URL = args.target

    levels = [int(x) for x in args.concurrency.split(",")]

    print(f"Target: {MCP_URL}")
    print(f"Test type: {args.type}")
    print(f"Concurrency levels: {levels}")
    print(f"Duration per level: {args.duration}s")
    print()

    for level in levels:
        print(f"Running level {level}...")
        results = await run_level(level, args.duration, args.auth_key, args.type)
        print_stats(level, results)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
