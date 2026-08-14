import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { useChatStore } from '../store/chatStore';
import axios from 'axios';
import CountUp from 'react-countup';
import { MessageSquare, FileText, Plus, Upload, Activity, Zap, ChevronRight, Sparkles, ArrowUpRight, Orbit, AlertTriangle, RefreshCw } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import Sidebar from '../components/layout/Sidebar';
import toast from 'react-hot-toast';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const COLORS = ['#4FD8C4', '#FF7A45', '#888E99', '#ECEAE3', '#4FD8C4'];

function StatCard({ icon: Icon, title, value, color, delay }) {
  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }} className="panel panel-lift rounded-2xl p-5 border border-line relative overflow-hidden">
      <div className="absolute right-0 top-0 h-16 w-16 signal-grid opacity-40" />
      <div className={`p-3 rounded-xl ${color} inline-flex mb-4`}><Icon className="w-5 h-5 text-paper" /></div>
      <div className="text-3xl font-display font-bold text-paper mb-1"><CountUp end={value} duration={2} /></div>
      <div className="text-mute text-sm">{title}</div>
    </motion.div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const activeWorkspaceId = useAuthStore((state) => state.activeWorkspaceId);
  const { sessions, createSession, fetchSessions } = useChatStore();
  const [analytics, setAnalytics] = useState(null);
  const [analyticsError, setAnalyticsError] = useState('');

  useEffect(() => {
    if (!activeWorkspaceId) return;
    fetchSessions().catch(() => {});
    fetchAnalytics();
  }, [activeWorkspaceId]);

  const fetchAnalytics = async () => {
    try {
      const { data } = await axios.get(`${API_URL}/api/v1/analytics/dashboard`);
      setAnalytics(data);
      setAnalyticsError('');
    } catch {
      // A dashboard must never silently replace unavailable production data
      // with invented numbers. Keep the empty state honest and recoverable.
      setAnalytics({ total_queries: 0, total_documents: 0, total_sessions: 0, queries_today: 0, daily_activity: [], document_types: [] });
      setAnalyticsError('Live analytics are temporarily unavailable.');
    }
  };

  const handleNewChat = async () => {
    try {
      const session = await createSession({ title: 'New Chat' });
      navigate(`/chat/${session.id}`);
      toast.success('New chat created!');
    } catch (error) {
      toast.error(error.message || 'Could not create a chat. Select a workspace and try again.');
    }
  };

  const stats = analytics ? [
    { icon: MessageSquare, title: 'Total Queries', value: analytics.total_queries, color: 'bg-line-2', delay: 0 },
    { icon: FileText, title: 'Documents', value: analytics.total_documents, color: 'from-blue-500 to-cyan-600', delay: 0.1 },
    { icon: Activity, title: 'Sessions', value: analytics.total_sessions, color: 'from-green-500 to-emerald-600', delay: 0.2 },
    { icon: Zap, title: 'Queries Today', value: analytics.queries_today, color: 'from-orange-500 to-red-600', delay: 0.3 },
  ] : [];

  return (
    <div className="flex h-screen bg-ink overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="sticky top-0 z-20 bg-ink/80 backdrop-blur-md border-b border-line px-8 py-4 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-trace font-mono text-[10px] tracking-[.18em] mb-1"><Orbit className="w-3 h-3" />WORKSPACE OVERVIEW</div>
            <h1 className="text-2xl font-display font-semibold text-paper">Good morning, {user?.name?.split(' ')[0] || 'there'}.</h1>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/documents')} className="flex items-center gap-2 px-4 py-2.5 panel rounded-xl border border-line text-paper/80 text-sm"><Upload className="w-4 h-4" />Upload Doc</button>
            <button onClick={handleNewChat} className="flex items-center gap-2 px-4 py-2.5 bg-paper rounded-xl text-ink text-sm font-medium hover:bg-trace transition-colors"><Plus className="w-4 h-4" />New Chat</button>
          </div>
        </div>
        <div className="p-8 space-y-8 max-w-7xl">
          {analyticsError && <div className="flex items-center justify-between gap-4 rounded-xl border border-pulse/30 bg-pulse/5 px-4 py-3 text-sm text-paper/90"><span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 shrink-0 text-pulse" />{analyticsError}</span><button onClick={fetchAnalytics} className="inline-flex items-center gap-1.5 font-mono text-xs text-trace hover:text-paper"><RefreshCw className="h-3.5 w-3.5" />retry</button></div>}
          <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="relative overflow-hidden rounded-3xl border border-line bg-ink-2 p-7">
            <div className="absolute inset-y-0 right-0 w-2/5 signal-grid opacity-50" /><div className="absolute -right-16 -top-16 w-52 h-52 rounded-full bg-trace/10 blur-3xl" />
            <div className="relative max-w-xl"><div className="inline-flex status-chip items-center gap-2 rounded-full px-3 py-1 font-mono text-[10px] text-trace"><span className="w-1.5 h-1.5 rounded-full bg-trace animate-pulse" />PRIVATE KNOWLEDGE SPACE</div><h2 className="font-display text-3xl mt-4 text-paper">Your documents, amplified by context.</h2><p className="text-mute text-sm leading-relaxed mt-2">Upload source material, ask precise questions, and keep every insight inside your own workspace.</p><div className="flex gap-3 mt-5"><button onClick={handleNewChat} className="bg-paper text-ink px-4 py-2.5 rounded-xl text-sm font-medium flex items-center gap-2 hover:bg-trace transition-colors">Start exploring <ArrowUpRight className="w-4 h-4" /></button><button onClick={() => navigate('/documents')} className="text-paper border border-line-2 px-4 py-2.5 rounded-xl text-sm flex items-center gap-2 hover:border-trace transition-colors"><Upload className="w-4 h-4" />Add sources</button></div></div>
          </motion.section>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{stats.map((stat, i) => <StatCard key={i} {...stat} />)}</div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 panel panel-lift rounded-2xl p-6 border border-line">
              <div className="flex items-center justify-between mb-6"><div><p className="font-mono text-[10px] text-trace tracking-widest">SIGNAL HISTORY</p><h3 className="text-paper font-display font-semibold text-lg mt-1">Query Activity</h3></div><Sparkles className="w-5 h-5 text-pulse" /></div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={analytics?.daily_activity || []}>
                  <defs><linearGradient id="colorQueries" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#4FD8C4" stopOpacity={0.3} /><stop offset="95%" stopColor="#4FD8C4" stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" stroke="#6b7280" tick={{ fill: '#6b7280', fontSize: 12 }} />
                  <YAxis stroke="#6b7280" tick={{ fill: '#6b7280', fontSize: 12 }} />
                  <Tooltip contentStyle={{ background: 'rgba(0,0,0,0.8)', border: '1px solid rgba(99,102,241,0.3)', borderRadius: '12px', color: 'white' }} />
                  <Area type="monotone" dataKey="queries" stroke="#4FD8C4" strokeWidth={2} fill="url(#colorQueries)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="panel panel-lift rounded-2xl p-6 border border-line">
              <h3 className="text-paper font-bold text-lg mb-6">Document Types</h3>
              <ResponsiveContainer width="100%" height={150}>
                <PieChart>
                  <Pie data={analytics?.document_types || []} cx="50%" cy="50%" innerRadius={40} outerRadius={70} dataKey="count" nameKey="type">
                    {(analytics?.document_types || []).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: 'rgba(0,0,0,0.8)', border: '1px solid rgba(99,102,241,0.3)', borderRadius: '12px', color: 'white' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="panel rounded-2xl p-6 border border-line">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-paper font-bold text-lg">Recent Chats</h3>
              <button onClick={() => navigate('/chat')} className="text-trace text-sm flex items-center gap-1">View all <ChevronRight className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              {sessions.slice(0, 5).map((session) => (
                <div key={session.id} onClick={() => navigate(`/chat/${session.id}`)} className="flex items-center gap-3 p-3 rounded-xl hover:bg-ink-2 cursor-pointer">
                  <div className="w-9 h-9 rounded-xl bg-line flex items-center justify-center shrink-0"><MessageSquare className="w-4 h-4 text-trace" /></div>
                  <div className="flex-1 min-w-0"><p className="text-paper text-sm font-medium truncate">{session.title}</p></div>
                </div>
              ))}
              {sessions.length === 0 && <p className="text-mute text-sm text-center py-4">No chats yet</p>}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
