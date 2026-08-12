import { create } from 'zustand';
import toast from 'react-hot-toast';
import { useAuthStore } from './authStore';
import { WS_URL } from '../lib/endpoints';

/**
 * WebSocket-backed chat store. Unlike chatStore.js (REST, request/response),
 * this drives the live agent trace panel and token-by-token streaming by
 * consuming the real event stream from /ws/chat/{session_id}.
 */
export const useWsChatStore = create((set, get) => ({
  socket: null,
  connected: false,
  viewerCount: 1,
  messages: [],
  streamingAnswer: '',
  trace: {},
  cacheHit: false,
  evalMetrics: null,
  isStreaming: false,

  connect: (sessionId) => {
    const existing = get().socket;
    if (existing) existing.close();

    const socket = new WebSocket(`${WS_URL}/ws/chat/${sessionId}`);

    socket.onopen = () => set({ connected: true });
    socket.onclose = (event) => {
      set({ connected: false });
      if (event.code === 1013) toast.error('The live demo is busy. Please try again shortly.');
    };

    socket.onmessage = (evt) => {
      const event = JSON.parse(evt.data);
      const state = get();

      switch (event.type) {
        case 'presence':
          set({ viewerCount: event.viewers });
          break;

        case 'user_message':
          set({
            messages: [...state.messages, { role: 'human', content: event.question, id: `u-${Date.now()}` }],
            streamingAnswer: '',
            trace: {},
            cacheHit: false,
            evalMetrics: null,
            isStreaming: true,
          });
          break;

        case 'node_start':
          set({ trace: { ...state.trace, [event.node]: { status: 'active', startedAt: event.ts } } });
          break;

        case 'node_end': {
          const started = state.trace[event.node]?.startedAt;
          set({
            trace: {
              ...state.trace,
              [event.node]: { status: 'done', durationMs: event.duration_ms, result: event.result },
            },
          });
          break;
        }

        case 'token':
          set({ streamingAnswer: state.streamingAnswer + event.token });
          break;

        case 'web_search': {
          const prior = state.trace.web_search_fallback || {};
          set({
            trace: {
              ...state.trace,
              web_search_fallback: {
                ...prior,
                status: event.status === 'completed' ? 'done' : 'active',
                durationMs: event.duration_ms ?? prior.durationMs,
                result: { ...(prior.result || {}), results_found: event.results_found, configured: event.configured },
              },
            },
          });
          break;
        }

        case 'done':
          set({
            messages: [...state.messages, {
              role: 'ai', content: event.answer, sources: event.sources,
              citations: event.citations || [],
              id: `a-${Date.now()}`, evalMetrics: event.eval_metrics, cacheHit: event.cache_hit,
            }],
            streamingAnswer: '',
            isStreaming: false,
            cacheHit: event.cache_hit,
            evalMetrics: event.eval_metrics,
          });
          break;

        case 'rate_limit':
          toast.error(`${event.message || 'Message limit reached'}${event.retry_after ? ` Try again in ${event.retry_after}s.` : ''}`);
          set({ isStreaming: false });
          break;

        default:
          break;
      }
    };

    set({ socket });
  },

  sendMessage: (question) => {
    const { socket } = get();
    if (socket && socket.readyState === WebSocket.OPEN) {
      // A logged-in client sends its existing JWT in the first application
      // frame, keeping it out of WebSocket URLs and proxy logs.
      socket.send(JSON.stringify({ question, access_token: useAuthStore.getState().token || undefined }));
    }
  },

  disconnect: () => {
    const { socket } = get();
    if (socket) socket.close();
    set({ socket: null, connected: false });
  },
}));
