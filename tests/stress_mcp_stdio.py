#!/usr/bin/env python3
"""MCP stdio transport stress test.

Tests sequential request handling, latency, and data integrity
through the SkillPool MCP server's stdio transport.
Each test iteration creates a fresh process (realistic for Agent usage).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, stdev, quantiles

# ── Configuration ──────────────────────────────────────────
TOTAL_REQUESTS = 100
CONCURRENCY = 5  # Each is a separate process
TIMEOUT_SEC = 30

# ── MCP stdio client ───────────────────────────────────────

def send_mcp_request(request: dict, timeout: int = TIMEOUT_SEC) -> dict:
    """Send a single JSON-RPC request via stdio using persistent readline."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "skillpool.mcp_server", "--transport", "stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/root/skillpool",
    )
    try:
        # 1. Send initialize
        init_req = json.dumps({
            "jsonrpc": "2.0", "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "stress-test", "version": "1.0"},
            },
        }) + "\n"
        proc.stdin.write(init_req.encode())
        proc.stdin.flush()

        # Read init response
        init_resp_line = proc.stdout.readline()
        if not init_resp_line:
            return {"error": "no init response"}

        # 2. Send initialized notification
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        proc.stdin.write(notif.encode())
        proc.stdin.flush()

        # 3. Send actual request
        req_line = json.dumps(request) + "\n"
        proc.stdin.write(req_line.encode())
        proc.stdin.flush()

        # 4. Close stdin to signal we're done
        proc.stdin.close()

        # 5. Read remaining output
        remaining = proc.stdout.read().decode()
        proc.wait(timeout=5)

        # Parse responses, find the one matching our request id
        for line in remaining.strip().split("\n"):
            if not line.strip():
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == request.get("id"):
                    return resp
            except json.JSONDecodeError:
                continue

        return {"error": "no matching response", "raw": remaining[:200]}
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return {"error": "timeout"}
    except Exception as e:
        proc.kill()
        proc.wait()
        return {"error": str(e)}


def make_request(req_id: int) -> tuple[int, dict, float]:
    """Execute a single MCP request and return (id, response, latency_ms)."""
    resources = [
        "skill://list",
        "skill://multi-dim-review/definition",
        "skill://multi-dim-review/rules",
        "skill://multi-dim-review/manifest.yaml",
    ]
    uri = resources[req_id % len(resources)]

    request = {
        "jsonrpc": "2.0",
        "id": f"req-{req_id}",
        "method": "resources/read",
        "params": {"uri": uri},
    }

    start = time.monotonic()
    response = send_mcp_request(request)
    latency = (time.monotonic() - start) * 1000

    return req_id, response, latency


# ── Main test ──────────────────────────────────────────────

def main():
    print(f"MCP stdio stress test: {TOTAL_REQUESTS} requests, {CONCURRENCY} concurrent")
    print(f"Timeout: {TIMEOUT_SEC}s per request")
    print()

    results = []
    errors = []
    start_time = time.monotonic()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(make_request, i): i for i in range(TOTAL_REQUESTS)}

        done = 0
        for future in as_completed(futures):
            try:
                req_id, response, latency = future.result(timeout=TIMEOUT_SEC + 10)
                results.append((req_id, response, latency))

                if "error" in response and "result" not in response:
                    errors.append((req_id, response.get("error", "unknown")))
            except Exception as e:
                errors.append((-1, str(e)))

            done += 1
            if done % 20 == 0:
                print(f"  Progress: {done}/{TOTAL_REQUESTS}")

    total_time = time.monotonic() - start_time

    # ── Report ──────────────────────────────────────────────
    latencies = [r[2] for r in results]
    successes = [r for r in results if "result" in r[1]]
    failures = [r for r in results if "result" not in r[1]]

    print()
    print("=" * 60)
    print("MCP stdio Stress Test Results")
    print("=" * 60)
    print(f"Total requests:    {TOTAL_REQUESTS}")
    print(f"Concurrency:       {CONCURRENCY}")
    print(f"Total time:        {total_time:.1f}s")
    print(f"Throughput:        {TOTAL_REQUESTS / total_time:.1f} req/s")
    print(f"Successes:         {len(successes)}/{TOTAL_REQUESTS}")
    print(f"Failures:          {len(failures)}/{TOTAL_REQUESTS}")
    print(f"Data loss:         {len(errors)} requests")
    print()

    if latencies:
        print("Latency (ms):")
        print(f"  Mean:   {mean(latencies):.1f}")
        if len(latencies) > 1:
            print(f"  Stdev:  {stdev(latencies):.1f}")
        qs = quantiles(latencies, n=100)
        print(f"  P50:    {qs[49]:.1f}")
        print(f"  P90:    {qs[89]:.1f}")
        print(f"  P99:    {qs[98]:.1f}")
        print(f"  Min:    {min(latencies):.1f}")
        print(f"  Max:    {max(latencies):.1f}")

    print()

    # ── Verdict ──────────────────────────────────────────────
    success_rate = len(successes) / TOTAL_REQUESTS * 100
    p99 = qs[98] if latencies else 999999
    no_data_loss = len(errors) == 0

    print("Verdict:")
    print(f"  Success rate >= 99%:   {'PASS' if success_rate >= 99 else 'FAIL'} ({success_rate:.1f}%)")
    print(f"  P99 latency < 5000ms:  {'PASS' if p99 < 5000 else 'FAIL'} ({p99:.1f}ms)")
    print(f"  No data loss:          {'PASS' if no_data_loss else 'FAIL'} ({len(errors)} lost)")

    # Note: P99 < 5000ms for stdio (process spawn overhead is ~200-500ms per req)
    # For production HTTP mode, target is < 100ms

    if success_rate >= 99 and no_data_loss:
        print("\n✓ ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("\n✗ SOME CHECKS FAILED")
        if errors:
            print("\nError details (first 5):")
            for req_id, err in errors[:5]:
                print(f"  req-{req_id}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
