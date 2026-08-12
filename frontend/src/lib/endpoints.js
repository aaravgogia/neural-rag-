const configuredApiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const configuredWsUrl = import.meta.env.VITE_WS_URL || configuredApiUrl;

// Render exposes RENDER_EXTERNAL_URL as HTTPS. Blueprint links can pass that
// value to Vite and this normalizer supplies the browser-required WSS scheme.
export const API_URL = configuredApiUrl.replace(/\/$/, '');
export const WS_URL = configuredWsUrl
  .replace(/^https:/i, 'wss:')
  .replace(/^http:/i, 'ws:')
  .replace(/\/$/, '');
