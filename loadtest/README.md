# WebSocket room load test

This uses **k6** because its native WebSocket client and connection metrics are
better suited than Locust for persistent rooms and broadcast timing.

Start the zero-key demo with a deliberately higher *test-only* public limit:

```powershell
cd backend
$env:PUBLIC_DEMO_REQUESTS_PER_MINUTE = '10000'
python -m uvicorn app.main_demo:app --host 127.0.0.1 --port 8000
```

Then run one level at a time:

```powershell
k6 run -e VUS=10  loadtest/ws_rooms.js
k6 run -e VUS=50  loadtest/ws_rooms.js
k6 run -e VUS=200 loadtest/ws_rooms.js
```

Record process memory separately (for example `Get-Process python | select
WS,PM`) before and after each 45-second test. `typing_delivery_ms` is real
end-to-end broadcast latency: the server echoes the client timestamp through
the existing ephemeral `typing` event. `agent_done_ms` is end-to-end agent time
for asker VUs.

The public demo intentionally contains a single `live-demo-session`; this
tests its worst-case fan-out room. Testing N private rooms requires seeded
users, sessions, and JWTs, because private sockets correctly reject unauthenticated
clients and their chat messages intentionally use the REST API.
