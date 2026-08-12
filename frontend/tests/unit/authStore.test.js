import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { useAuthStore } from '../../src/store/authStore';
describe('auth workspace state', () => {
  beforeEach(() => useAuthStore.setState({ token: null, user: null, workspaces: [], activeWorkspaceId: null, isAuthenticated: false }));
  it('selects the first workspace returned by the API', async () => { vi.spyOn(axios, 'get').mockResolvedValueOnce({ data: [{ id: 'w1', name: 'Team', role: 'owner' }] }); await useAuthStore.getState().fetchWorkspaces(); expect(useAuthStore.getState().activeWorkspaceId).toBe('w1'); });
  it('hydrates a token into axios authorization', () => { useAuthStore.setState({ token: 'token' }); useAuthStore.getState().setHydrated(); expect(axios.defaults.headers.common.Authorization).toBe('Bearer token'); });
});
