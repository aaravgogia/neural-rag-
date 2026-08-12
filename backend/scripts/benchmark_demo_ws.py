"""Concurrent WebSocket fallback benchmark for environments without k6/Locust.

It measures one public demo room's true broadcast fan-out. It intentionally
does not claim to cover private rooms, which require real seeded JWT sessions.
Run after starting main_demo with PUBLIC_DEMO_REQUESTS_PER_MINUTE=10000.
"""
import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import websocket


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    items = sorted(values)
    return items[min(len(items) - 1, round((len(items) - 1) * value))]


def run_client(index: int, url: str, start: threading.Event, ask: bool) -> dict:
    began = time.perf_counter()
    typing_latency = None
    answered = False
    try:
        socket = websocket.create_connection(url, timeout=10, origin="http://localhost:5173")
        connected_ms = (time.perf_counter() - began) * 1000
        start.wait(15)
        sent_at = int(time.time() * 1000)
        socket.send(json.dumps({"type": "typing", "is_typing": True, "client_sent_at": sent_at}))
        if ask:
            socket.send(json.dumps({"type": "message", "question": "What does invoice 4471 cover?"}))
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            event = json.loads(socket.recv())
            if event.get("type") == "typing" and event.get("client_sent_at") == sent_at:
                typing_latency = int(time.time() * 1000) - sent_at
            if ask and event.get("type") == "done":
                answered = True
            if typing_latency is not None and (not ask or answered):
                break
        socket.close()
        return {"ok": True, "connect_ms": connected_ms, "typing_ms": typing_latency, "answered": answered}
    except Exception as error:
        return {"ok": False, "error": str(error)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--asker-percent", type=int, default=20)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/chat/live-demo-session")
    args = parser.parse_args()
    start = threading.Event()
    with ThreadPoolExecutor(max_workers=args.clients) as pool:
        futures = [pool.submit(run_client, i, args.url, start, i % 100 < args.asker_percent) for i in range(args.clients)]
        time.sleep(1)
        started = time.perf_counter()
        start.set()
        results = [future.result() for future in as_completed(futures)]
    elapsed = time.perf_counter() - started
    successes = [result for result in results if result["ok"]]
    typing = [result["typing_ms"] for result in successes if result["typing_ms"] is not None]
    answer_count = sum(result["answered"] for result in successes)
    print(json.dumps({
        "clients": args.clients,
        "connection_success_rate": round(len(successes) / args.clients, 4),
        "connection_failures": args.clients - len(successes),
        "connect_p50_ms": round(percentile([result["connect_ms"] for result in successes], .50), 2),
        "connect_p95_ms": round(percentile([result["connect_ms"] for result in successes], .95), 2),
        "typing_events_received": len(typing),
        "typing_delivery_p50_ms": round(percentile(typing, .50), 2),
        "typing_delivery_p95_ms": round(percentile(typing, .95), 2),
        "askers_completed": answer_count,
        "duration_seconds": round(elapsed, 2),
    }, indent=2))


if __name__ == "__main__":
    main()
