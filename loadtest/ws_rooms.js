/* k6 WebSocket room-load test.

The demo exposes one public agent room (live-demo-session), so this measures
the realistic public-demo worst case: many simultaneous askers/observers in a
single broadcast room. Private room load needs authenticated test JWTs and is
deliberately not faked by this script.

Examples:
  k6 run -e VUS=10  loadtest/ws_rooms.js
  k6 run -e VUS=50  loadtest/ws_rooms.js
  k6 run -e VUS=200 loadtest/ws_rooms.js
*/
import ws from 'k6/ws';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const WS_URL = __ENV.WS_URL || 'ws://127.0.0.1:8000/ws/chat/live-demo-session';
const VUS = Number(__ENV.VUS || 10);
const ASKERS_PERCENT = Number(__ENV.ASKERS_PERCENT || 25);
const DURATION = __ENV.DURATION || '45s';

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    ws_connecting: ['p(95)<1000'],
    connection_success_rate: ['rate>0.99'],
    typing_delivery_ms: ['p(95)<500'],
  },
};

const connectionSuccess = new Counter('connection_success_rate');
const connectionFailure = new Counter('connection_failures');
const typingDelivery = new Trend('typing_delivery_ms', true);
const agentDone = new Trend('agent_done_ms', true);

export default function () {
  const isAsker = (__VU % 100) < ASKERS_PERCENT;
  const openedAt = Date.now();
  const response = ws.connect(WS_URL, {}, socket => {
    socket.on('open', () => {
      connectionSuccess.add(1);
      // All clients exercise the room's presence + typing broadcast path.
      socket.send(JSON.stringify({ type: 'typing', is_typing: true, client_sent_at: Date.now() }));
      if (isAsker) {
        socket.setTimeout(() => {
          socket.send(JSON.stringify({ type: 'message', question: 'What does invoice 4471 cover?' }));
        }, 500 + (__VU % 5) * 200);
      }
    });
    socket.on('message', raw => {
      const event = JSON.parse(raw);
      if (event.type === 'typing' && event.client_sent_at) typingDelivery.add(Date.now() - event.client_sent_at);
      if (event.type === 'done' && isAsker) agentDone.add(Date.now() - openedAt);
    });
    socket.on('error', () => connectionFailure.add(1));
    socket.setTimeout(() => socket.close(), 15000);
  });
  check(response, { 'websocket upgrade accepted': result => result && result.status === 101 });
}
