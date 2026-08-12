import { create } from 'zustand';
import axios from 'axios';
import { useAuthStore } from './authStore';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const useChatStore = create((set, get) => ({
  sessions: [], currentSession: null, messages: [], isLoading: false,
  fetchSessions: async () => {
    const workspace_id = useAuthStore.getState().activeWorkspaceId; if (!workspace_id) return set({ sessions: [], currentSession: null, messages: [] });
    const response = await axios.get(`${API_URL}/api/v1/chat/sessions`, { params: { workspace_id } });
    set({ sessions: response.data });
  },
  createSession: async (data = {}) => {
    const workspace_id = useAuthStore.getState().activeWorkspaceId; if (!workspace_id) throw new Error('Select a workspace first');
    const response = await axios.post(`${API_URL}/api/v1/chat/sessions`, { ...data, workspace_id });
    const session = response.data;
    set(state => ({ sessions: [session, ...state.sessions], currentSession: session, messages: [] }));
    return session;
  },
  selectSession: async (sessionId) => {
    const response = await axios.get(`${API_URL}/api/v1/chat/sessions/${sessionId}/messages`);
    const session = get().sessions.find(s => s.id === sessionId);
    set({ currentSession: session, messages: response.data });
  },
  deleteSession: async (sessionId) => {
    await axios.delete(`${API_URL}/api/v1/chat/sessions/${sessionId}`);
    set(state => ({
      sessions: state.sessions.filter(s => s.id !== sessionId),
      currentSession: state.currentSession?.id === sessionId ? null : state.currentSession,
      messages: state.currentSession?.id === sessionId ? [] : state.messages
    }));
  },
  sendMessage: async (question, useAgent = true) => {
    const { currentSession } = get();
    if (!currentSession) return;
    const userMessage = { id: Date.now().toString(), role: 'human', content: question, created_at: new Date().toISOString() };
    set(state => ({ messages: [...state.messages, userMessage], isLoading: true }));
    try {
      const response = await axios.post(`${API_URL}/api/v1/chat/query`, {
        question, session_id: currentSession.id, namespace: currentSession.namespace, use_agent: useAgent
      });
      const aiMessage = {
        id: response.data.message_id, role: 'ai', content: response.data.answer,
        sources: response.data.sources, processing_time: response.data.processing_time,
        created_at: new Date().toISOString()
      };
      set(state => ({ messages: [...state.messages, aiMessage], isLoading: false }));
      return response.data;
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },
  clearMessages: () => set({ messages: [] })
}));
