import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isHydrated: false, // gates routing until localStorage has been read
      workspaces: [],
      activeWorkspaceId: null,
      setActiveWorkspace: (activeWorkspaceId) => set({ activeWorkspaceId }),
      fetchWorkspaces: async () => { const { data } = await axios.get(`${API_URL}/api/v1/workspaces`); set(state => ({ workspaces: data, activeWorkspaceId: data.some(w => w.id === state.activeWorkspaceId) ? state.activeWorkspaceId : data[0]?.id || null })); },

      // Called once by the persist middleware after rehydration completes
      setHydrated: () => {
        const { token } = get();
        if (token) {
          axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
          set({ isAuthenticated: true, isHydrated: true });
        } else {
          set({ isHydrated: true });
        }
      },

      setToken: (token) => {
        set({ token, isAuthenticated: !!token });
        if (token) axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      },
      setUser: (user) => set({ user }),

      login: async (token) => {
        axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        try {
          const { data } = await axios.get(`${API_URL}/api/v1/auth/me`);
          set({ token, user: data, isAuthenticated: true, isHydrated: true }); await get().fetchWorkspaces();
        } catch (err) {
          delete axios.defaults.headers.common['Authorization'];
          set({ token: null, user: null, isAuthenticated: false, isHydrated: true });
          throw err;
        }
      },

      logout: () => {
        delete axios.defaults.headers.common['Authorization'];
        set({ user: null, token: null, isAuthenticated: false, workspaces: [], activeWorkspaceId: null });
      },

      // kept for backward compatibility with anything still calling it directly
      initAuth: () => {
        const { token } = get();
        if (token) {
          axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
          set({ isAuthenticated: true });
        }
      }
    }),
    {
      name: 'neural-rag-auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ token: state.token, user: state.user, activeWorkspaceId: state.activeWorkspaceId }),
      // Fires once localStorage has actually been read back into the store
      onRehydrateStorage: () => (state) => {
        if (state) state.setHydrated();
      }
    }
  )
);
