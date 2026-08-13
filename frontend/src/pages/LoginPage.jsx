import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuthStore } from '../store/authStore';
import PipelineStrip from '../components/shared/PipelineStrip';
import { ArrowLeft, Shield, Zap, AlertTriangle } from 'lucide-react';
import toast from 'react-hot-toast';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const PROOF = [
  { value: '11/11', label: 'tests passing' },
  { value: '2', label: 'concurrent clients verified' },
  { value: '5', label: 'nodes traced live' },
];

export default function LoginPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [authConfigured, setAuthConfigured] = useState(null); // null = still checking
  const [heroTrace, setHeroTrace] = useState({});

  useEffect(() => { if (isAuthenticated) navigate('/dashboard'); }, [isAuthenticated]);

  // Check whether the backend actually has Google credentials configured,
  // so we can tell the person that clearly instead of letting them click
  // through to a confusing 503 page mid-OAuth-flow.
  useEffect(() => {
    fetch(`${API_URL}/`)
      .then(r => r.json())
      .then(d => setAuthConfigured(!!d.auth_configured))
      .catch(() => setAuthConfigured(false));
  }, []);

  // Same idle "boot sequence" as the landing hero, so the two pages feel
  // like one continuous piece of software rather than a marketing page
  // bolted onto a generic auth template.
  useEffect(() => {
    const keys = ['analyze_query', 'check_cache', 'retrieve_documents', 'generate_answer', 'grade_answer'];
    keys.forEach((k, i) => {
      setTimeout(() => setHeroTrace(t => ({ ...t, [k]: { status: 'active' } })), i * 300);
      setTimeout(() => setHeroTrace(t => ({ ...t, [k]: { status: 'done' } })), i * 300 + 240);
    });
  }, []);

  const handleGoogleLogin = () => {
    if (authConfigured === false) {
      toast.error("Google sign-in isn't configured on this deployment yet. See DEPLOYMENT.md.");
      return;
    }
    window.location.href = `${API_URL}/api/v1/auth/google/login`;
  };

  return (
    <div className="min-h-screen bg-ink text-paper font-sans flex">
      {/* Left: schematic / proof panel -- hidden on small screens, this is
          the "aesthetic" half, but it's built from real content (the same
          pipeline strip and real measured numbers as the landing page),
          not a stock illustration. */}
      <div className="hidden lg:flex lg:w-1/2 border-r border-line flex-col justify-between p-10">
        <div className="font-mono text-sm">
          <span className="text-paper">neuralrag</span><span className="text-mute">://pipeline</span>
        </div>

        <div>
          <div className="font-mono text-xs text-trace mb-4 tracking-wider">SYS · BOOT SEQUENCE</div>
          <div className="panel rounded-lg p-6 mb-8">
            <PipelineStrip trace={heroTrace} />
          </div>
          <h2 className="font-display text-2xl mb-2 max-w-sm">A RAG agent with nothing hidden.</h2>
          <p className="text-mute text-sm max-w-sm leading-relaxed">
            Every retrieval score, cache decision, and retry -- visible in real time,
            not a black box that occasionally cites a source.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-6">
          {PROOF.map((p, i) => (
            <div key={i}>
              <div className="font-display text-2xl">{p.value}</div>
              <div className="font-mono text-[10px] text-mute">{p.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right: auth form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center relative px-6">
        <button onClick={() => navigate('/')} className="absolute top-6 left-6 flex items-center gap-1.5 text-mute hover:text-paper transition-colors text-sm font-mono">
          <ArrowLeft className="w-3.5 h-3.5" /> back
        </button>

        <div className="w-full max-w-sm">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="mb-8 lg:hidden">
              <div className="font-mono text-xs text-trace mb-2">neuralrag://pipeline</div>
            </div>
            <div className="mb-8">
              <h1 className="font-display text-2xl mb-1">Sign in</h1>
              <p className="text-mute text-sm">Access your document workspace</p>
            </div>

            {authConfigured === false && (
              <div className="flex items-start gap-2 mb-4 p-3 rounded border border-pulse/30 bg-pulse/5">
                <AlertTriangle className="w-3.5 h-3.5 text-pulse shrink-0 mt-0.5" />
                <p className="text-xs text-paper/80 leading-relaxed">
                  Google sign-in isn't configured on this deployment yet.
                  <span className="block text-mute mt-0.5 font-mono text-[11px]">See DEPLOYMENT.md for the 5-minute setup.</span>
                </p>
              </div>
            )}

            <button onClick={handleGoogleLogin} disabled={isLoading || authConfigured !== true}
              className="w-full flex items-center justify-center gap-3 py-3 px-5 rounded font-medium text-sm text-ink bg-paper hover:bg-trace transition-colors disabled:opacity-40">
              {isLoading ? <div className="w-4 h-4 border-2 border-ink/30 border-t-ink rounded-full animate-spin" /> : (
                <>
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                  <span>{authConfigured === false ? 'Google sign-in unavailable' : 'Continue with Google'}</span>
                </>
              )}
            </button>

            <div className="flex items-center gap-3 my-6"><div className="flex-1 h-px bg-line" /><span className="text-mute text-[10px] font-mono">OR</span><div className="flex-1 h-px bg-line" /></div>

            <button onClick={() => navigate('/live-demo')}
              className="w-full flex items-center justify-center gap-2 py-3 px-5 rounded font-medium text-sm text-paper border border-line-2 hover:border-trace hover:text-trace transition-colors">
              Try the live demo instead
            </button>

            <div className="space-y-2.5 mt-8">
              {[{ icon: Shield, text: 'Your data stays in your own deployment' }, { icon: Zap, text: 'No account needed for the live demo' }].map(({ icon: Icon, text }, i) => (
                <div key={i} className="flex items-center gap-2.5">
                  <Icon className="w-3.5 h-3.5 text-trace shrink-0" />
                  <span className="text-mute text-xs">{text}</span>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
