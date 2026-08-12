import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { motion } from 'framer-motion';
import { Brain } from 'lucide-react';
import toast from 'react-hot-toast';

export default function AuthCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuthStore();

  useEffect(() => {
    const code = searchParams.get('code');
    // Remove the one-time code from browser history before exchanging it.
    window.history.replaceState({}, document.title, '/auth/callback');
    if (code) {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      fetch(`${apiUrl}/api/v1/auth/exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
        .then(response => response.ok ? response.json() : Promise.reject(new Error('Exchange failed')))
        .then(({ access_token }) => login(access_token))
        .then(() => { toast.success('Welcome to NeuralRAG!'); navigate('/dashboard'); })
        .catch(() => { toast.error('Authentication failed'); navigate('/login'); });
    } else { navigate('/login'); }
  }, [login, navigate, searchParams]);

  return (
    <div className="min-h-screen bg-ink flex items-center justify-center">
      <motion.div className="flex flex-col items-center gap-6" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <motion.div className="w-20 h-20 rounded-2xl bg-line-2 flex items-center justify-center shadow-2xl"
          animate={{ rotate: 360 }} transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}>
          <Brain className="w-10 h-10 text-paper" />
        </motion.div>
        <div className="text-center"><h2 className="text-2xl font-bold  mb-2">Authenticating...</h2><p className="text-mute">Setting up your workspace</p></div>
      </motion.div>
    </div>
  );
}
