#!/usr/bin/env python3
"""
ScreenDrop Stress Tester
========================
Tests WebSocket connection capacity and upload throughput of the ScreenDrop Go server.

Usage:
    pip install websockets requests pillow aiohttp

    # Basic run (defaults)
    python screendrop_stress_test.py

    # Custom target and load
    python screendrop_stress_test.py --host 192.168.1.42 --port 8080 \
        --ws-clients 200 --uploads 50 --concurrency 10

Flags:
    --host          Server IP or hostname      (default: localhost)
    --port          Server port                (default: 8080)
    --ws-clients    Number of WS connections   (default: 100)
    --ramp-delay    Seconds between each conn  (default: 0.05)
    --uploads       Total uploads to send      (default: 30)
    --concurrency   Parallel upload workers    (default: 5)
    --image-size    Fake image side length px  (default: 1920x1080)
    --timeout       Per-request timeout (s)    (default: 10)
"""

import asyncio
import argparse
import time
import io
import sys
import json
import statistics
import threading
from dataclasses import dataclass, field
from typing import List

import requests
import websockets
from PIL import Image, ImageDraw
import random


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="ScreenDrop stress tester")
    p.add_argument("--host",        default="localhost")
    p.add_argument("--port",        type=int, default=8080)
    p.add_argument("--ws-clients",  type=int, default=100000,  help="Concurrent WS connections")
    p.add_argument("--ramp-delay",  type=float, default=0.05, help="Seconds between each WS connection")
    p.add_argument("--uploads",     type=int, default=3000,   help="Total image uploads")
    p.add_argument("--concurrency", type=int, default=5,    help="Parallel upload workers")
    p.add_argument("--image-size",  default="1920x1080",    help="WxH of generated test images")
    p.add_argument("--timeout",     type=int, default=10,   help="Per-request timeout seconds")
    return p.parse_args()


# ──────────────────────────────────────────────
# Test image factory
# ──────────────────────────────────────────────

def make_fake_screenshot(width: int, height: int) -> bytes:
    """Generate a unique PNG in memory — looks like a colourful screenshot."""
    img = Image.new("RGB", (width, height), color=(
        random.randint(30, 80),
        random.randint(30, 80),
        random.randint(30, 80),
    ))
    draw = ImageDraw.Draw(img)
    # Random rectangles to vary bytes so dedup doesn't fire in clipboard_watcher
    for _ in range(20):
        x0, y0 = random.randint(0, width), random.randint(0, height)
        x1, y1 = x0 + random.randint(50, 400), y0 + random.randint(30, 300)
        draw.rectangle([x0, y0, x1, y1], fill=(
            random.randint(100, 255),
            random.randint(100, 255),
            random.randint(100, 255),
        ))
    draw.text((10, 10), f"stress-test @ {time.time():.3f}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ──────────────────────────────────────────────
# Results collector (thread-safe)
# ──────────────────────────────────────────────

@dataclass
class Results:
    # WebSocket
    ws_connected: int = 0
    ws_failed: int = 0
    ws_messages_received: int = 0
    ws_connect_times: List[float] = field(default_factory=list)

    # Uploads
    upload_ok: int = 0
    upload_failed: int = 0
    upload_latencies: List[float] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_ws_connect(self, elapsed: float):
        with self._lock:
            self.ws_connected += 1
            self.ws_connect_times.append(elapsed)

    def record_ws_fail(self):
        with self._lock:
            self.ws_failed += 1

    def record_ws_message(self):
        with self._lock:
            self.ws_messages_received += 1

    def record_upload(self, elapsed: float):
        with self._lock:
            self.upload_ok += 1
            self.upload_latencies.append(elapsed)

    def record_upload_fail(self):
        with self._lock:
            self.upload_failed += 1


# ──────────────────────────────────────────────
# WebSocket client (async)
# ──────────────────────────────────────────────

async def ws_client(uri: str, client_id: int, results: Results,
                    stop_event: asyncio.Event, timeout: int):
    t0 = time.perf_counter()
    try:
        async with websockets.connect(uri, open_timeout=timeout) as ws:
            results.record_ws_connect(time.perf_counter() - t0)
            # Just wait and count messages until the stop signal
            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "image":
                        results.record_ws_message()
                except asyncio.TimeoutError:
                    pass  # poll loop, normal
                except websockets.exceptions.ConnectionClosed:
                    break
    except Exception:
        results.record_ws_fail()


async def run_ws_phase(base_url: str, num_clients: int, ramp_delay: float,
                       results: Results, stop_event: asyncio.Event, timeout: int):
    ws_uri = base_url.replace("http://", "ws://") + "/ws"
    print(f"\n{'─'*55}")
    print(f"  PHASE 1 — WebSocket connections")
    print(f"  Target : {ws_uri}")
    print(f"  Clients: {num_clients}  |  Ramp delay: {ramp_delay}s each")
    print(f"{'─'*55}")

    tasks = []
    for i in range(num_clients):
        task = asyncio.create_task(
            ws_client(ws_uri, i, results, stop_event, timeout)
        )
        tasks.append(task)
        if ramp_delay > 0:
            await asyncio.sleep(ramp_delay)
        connected_now = results.ws_connected + results.ws_failed
        if (i + 1) % max(1, num_clients // 10) == 0 or i == num_clients - 1:
            print(f"  [{i+1:>4}/{num_clients}]  connected={results.ws_connected}  failed={results.ws_failed}")

    print(f"\n  Ramp complete. {results.ws_connected} clients connected, {results.ws_failed} failed.")
    return tasks


# ──────────────────────────────────────────────
# Upload worker (sync, runs in thread pool)
# ──────────────────────────────────────────────

def upload_one(base_url: str, width: int, height: int,
               results: Results, timeout: int, worker_id: int, upload_id: int):
    img_bytes = make_fake_screenshot(width, height)
    url = base_url + "/upload"
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            url,
            files={"image": ("screenshot.png", img_bytes, "image/png")},
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        if resp.status_code == 200:
            results.record_upload(elapsed)
            return elapsed
        else:
            results.record_upload_fail()
            return None
    except Exception as e:
        results.record_upload_fail()
        return None


async def run_upload_phase(base_url: str, num_uploads: int, concurrency: int,
                           width: int, height: int, results: Results, timeout: int):
    print(f"\n{'─'*55}")
    print(f"  PHASE 2 — Upload throughput")
    print(f"  Uploads   : {num_uploads}")
    print(f"  Concurrency: {concurrency} parallel workers")
    print(f"  Image size : {width}×{height}px")
    print(f"{'─'*55}")

    loop = asyncio.get_event_loop()
    semaphore = asyncio.Semaphore(concurrency)
    t_start = time.perf_counter()

    async def bounded_upload(i):
        async with semaphore:
            return await loop.run_in_executor(
                None, upload_one, base_url, width, height, results, timeout, i % concurrency, i
            )

    tasks = [bounded_upload(i) for i in range(num_uploads)]
    done = 0
    for coro in asyncio.as_completed(tasks):
        await coro
        done += 1
        if done % max(1, num_uploads // 10) == 0 or done == num_uploads:
            print(f"  [{done:>4}/{num_uploads}]  ok={results.upload_ok}  failed={results.upload_failed}")

    total_time = time.perf_counter() - t_start
    return total_time


# ──────────────────────────────────────────────
# Connectivity pre-check
# ──────────────────────────────────────────────

def check_server(base_url: str, timeout: int) -> bool:
    print(f"\n  Checking server at {base_url} ...")
    try:
        r = requests.get(base_url, timeout=timeout)
        print(f"  ✓ Server responded with HTTP {r.status_code}")
        return True
    except Exception as e:
        print(f"  ✗ Could not reach server: {e}")
        return False


# ──────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────

def print_report(results: Results, upload_total_time: float, args):
    w = 55
    print(f"\n{'═'*w}")
    print(f"  STRESS TEST REPORT")
    print(f"{'═'*w}")

    # WebSocket
    print(f"\n  WebSocket Connections")
    print(f"  {'Attempted':<28} {args.ws_clients}")
    print(f"  {'Connected':<28} {results.ws_connected}")
    print(f"  {'Failed':<28} {results.ws_failed}")
    print(f"  {'Messages received':<28} {results.ws_messages_received}")
    if results.ws_connect_times:
        print(f"  {'Connect time avg':<28} {statistics.mean(results.ws_connect_times)*1000:.1f}ms")
        print(f"  {'Connect time p95':<28} {_p95(results.ws_connect_times)*1000:.1f}ms")
        print(f"  {'Connect time max':<28} {max(results.ws_connect_times)*1000:.1f}ms")

    # Uploads
    print(f"\n  Uploads ({args.image_size} PNG)")
    print(f"  {'Attempted':<28} {args.uploads}")
    print(f"  {'Succeeded':<28} {results.upload_ok}")
    print(f"  {'Failed':<28} {results.upload_failed}")
    if results.upload_latencies:
        print(f"  {'Latency avg':<28} {statistics.mean(results.upload_latencies)*1000:.1f}ms")
        print(f"  {'Latency p95':<28} {_p95(results.upload_latencies)*1000:.1f}ms")
        print(f"  {'Latency max':<28} {max(results.upload_latencies)*1000:.1f}ms")
    if upload_total_time > 0 and results.upload_ok > 0:
        rps = results.upload_ok / upload_total_time
        print(f"  {'Throughput':<28} {rps:.2f} uploads/sec")

    # Broadcast check
    expected_msgs = results.upload_ok * results.ws_connected
    print(f"\n  Broadcast delivery")
    print(f"  {'Expected messages':<28} {expected_msgs}")
    print(f"  {'Received messages':<28} {results.ws_messages_received}")
    if expected_msgs > 0:
        pct = results.ws_messages_received / expected_msgs * 100
        print(f"  {'Delivery rate':<28} {pct:.1f}%")
        if pct < 80:
            print(f"\n  ⚠  Low delivery (<80%) — server may be dropping")
            print(f"     messages under load or broadcast channel is full.")

    print(f"\n{'═'*w}\n")


def _p95(data: list) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * 0.95)
    return s[min(idx, len(s) - 1)]


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

async def main():
    args = parse_args()

    try:
        w, h = map(int, args.image_size.lower().split("x"))
    except ValueError:
        print("--image-size must be WxH, e.g. 1920x1080")
        sys.exit(1)

    base_url = f"http://{args.host}:{args.port}"
    results = Results()

    print(f"\n{'═'*55}")
    print(f"  ScreenDrop Stress Tester")
    print(f"  Target: {base_url}")
    print(f"{'═'*55}")

    if not check_server(base_url, args.timeout):
        sys.exit(1)

    stop_event = asyncio.Event()

    # Phase 1: ramp up WS connections, keep them open
    ws_tasks = await run_ws_phase(
        base_url, args.ws_clients, args.ramp_delay, results, stop_event, args.timeout
    )

    # Brief pause so all connections settle before hammering uploads
    print(f"\n  Waiting 1s for connections to stabilise...")
    await asyncio.sleep(1.0)

    # Phase 2: send uploads while WS clients are all connected
    upload_total_time = await run_upload_phase(
        base_url, args.uploads, args.concurrency, w, h, results, args.timeout
    )

    # Let the last broadcast ripple through before we tear down
    print(f"\n  Waiting 2s for final broadcasts to propagate...")
    await asyncio.sleep(2.0)

    # Tear down WS clients
    stop_event.set()
    if ws_tasks:
        await asyncio.gather(*ws_tasks, return_exceptions=True)

    print_report(results, upload_total_time, args)


if __name__ == "__main__":
    asyncio.run(main())
