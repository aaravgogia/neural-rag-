import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { motion, AnimatePresence } from 'framer-motion';
import { Suspense, lazy } from 'react';
import { useAuthStore } from './store/authStore';
import CommandPalette from './components/ui/CommandPalette';

// Route-level code splitting: the landing page and live demo (what a
// recruiter opens first) ship in the entry chunk; the authenticated
// dashboard suite (Recharts, dropzone, markdown, etc.) lazy-loads on
// demand instead of bloating the first paint.
import LandingPage from './pages/LandingPage';
import LiveChatDemo from './pages/LiveChatDemo';
const LoginPage = lazy(() => import('./pages/LoginPage'));
const AuthCallback = lazy(() => import('./pages/AuthCallback'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const StatusPage = lazy(() => import('./pages/StatusPage'));

// ─── Hydration / route-chunk loading splash ─────────────────────────────────
function LoadingSplash() {
  return (
    <motion.div
      key="splash"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="fixed inset-0 z-[999] bg-ink flex flex-col items-center justify-center gap-4"
    >
      <div className="flex items-center gap-2">
        <motion.div animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 1.1, repeat: Infinity }} className="w-2 h-2 rounded-full bg-pulse" />
        <motion.div animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 1.1, repeat: Infinity, delay: 0.35 }} className="w-2 h-2 rounded-full bg-trace" />
      </div>
      <p className="font-mono text-[10px] text-mute tracking-wider">LOADING</p>
    </motion.div>
  );
}

// ─── Private Route ──────────────────────────────────────────────────────────
// Waits for isHydrated before making any redirect decision -- this is what
// fixes the "refresh /chat -> bounced to /login -> redirected to /dashboard"
// race condition found and fixed earlier in this project.
function PrivateRoute({ children }) {
  const { isAuthenticated, isHydrated } = useAuthStore();
  if (!isHydrated) return null; // splash covers this gap
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

// ─── Public Route ────────────────────────────────────────────────────────────
function PublicRoute({ children }) {
  const { isAuthenticated, isHydrated } = useAuthStore();
  if (!isHydrated) return null;
  if (isAuthenticated) return <Navigate to="/dashboard" replace />;
  return children;
}

export default function App() {
  const { isHydrated } = useAuthStore();

  return (
    <BrowserRouter>
      <Toaster position="top-right" toastOptions={{
        style: { background: '#10131A', color: '#ECEAE3', border: '1px solid rgba(236,234,227,0.12)', fontFamily: 'IBM Plex Mono, monospace', fontSize: '13px' },
      }} />
      <CommandPalette />

      <AnimatePresence>
        {!isHydrated && <LoadingSplash />}
      </AnimatePresence>

      <Suspense fallback={<LoadingSplash />}>
        <Routes>
          {/* Public */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/live-demo" element={<LiveChatDemo />} />
          <Route path="/status" element={<StatusPage />} />

          {/* Protected */}
          <Route path="/dashboard" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
          <Route path="/chat" element={<PrivateRoute><ChatPage /></PrivateRoute>} />
          <Route path="/chat/:sessionId" element={<PrivateRoute><ChatPage /></PrivateRoute>} />
          <Route path="/documents" element={<PrivateRoute><DocumentsPage /></PrivateRoute>} />
          <Route path="/analytics" element={<PrivateRoute><AnalyticsPage /></PrivateRoute>} />
          <Route path="/settings" element={<PrivateRoute><SettingsPage /></PrivateRoute>} />

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
