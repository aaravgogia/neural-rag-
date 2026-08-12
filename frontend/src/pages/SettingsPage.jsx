import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';
import Sidebar from '../components/layout/Sidebar';
import { Camera, Save, Check, ChevronRight, LogOut } from 'lucide-react';
import toast from 'react-hot-toast';

const SECTIONS = ['Profile', 'Appearance', 'Notifications', 'Security', 'API Keys'];
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function Toggle({ value, onChange, label, description }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-white/5 last:border-0">
      <div><p className="text-paper text-sm font-medium">{label}</p>{description && <p className="text-mute text-xs mt-0.5">{description}</p>}</div>
      <button onClick={() => onChange(!value)} className={`relative w-11 h-6 rounded-full ${value ? 'bg-paper' : 'bg-gray-700'}`}>
        <motion.div animate={{ x: value ? 22 : 2 }} className="absolute top-1 w-4 h-4 rounded-full bg-white shadow" />
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const { user, logout, activeWorkspaceId } = useAuthStore();
  const [usage, setUsage] = useState(null);
  const [active, setActive] = useState('Profile');
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState({ emailNotifications: true, darkMode: true, streamingMode: true, twoFactor: false });
  const update = (key, val) => setSettings(s => ({ ...s, [key]: val }));
  const handleSave = () => { setSaved(true); toast.success('Settings saved!'); setTimeout(() => setSaved(false), 2000); };
  useEffect(() => { if (activeWorkspaceId) axios.get(`${API_URL}/api/v1/analytics/usage`, { params: { workspace_id: activeWorkspaceId } }).then(r => setUsage(r.data)).catch(() => setUsage(null)); }, [activeWorkspaceId]);

  return (
    <div className="flex h-screen bg-ink overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="sticky top-0 z-20 panel border-b border-line px-8 py-4"><h1 className="text-2xl font-bold text-paper"><span className="">Settings</span></h1></div>
        <div className="p-8 flex gap-8 max-w-5xl">
          <div className="w-48 shrink-0">
            <div className="panel rounded-2xl border border-line p-2 space-y-1">
              {SECTIONS.map(s => (
                <button key={s} onClick={() => setActive(s)} className={`w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium flex items-center justify-between ${active === s ? 'bg-paper/30 text-trace border border-line-2' : 'text-mute hover:text-paper hover:bg-ink-2'}`}>
                  {s}<ChevronRight className="w-3.5 h-3.5" />
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 panel rounded-2xl border border-line p-6">
            {active === 'Profile' && (
              <div className="space-y-6">
                <h2 className="text-paper font-bold text-lg">Profile Information</h2>
                <div className="flex items-center gap-5">
                  {user?.picture ? <img src={user.picture} alt="Avatar" className="w-20 h-20 rounded-2xl ring-2 ring-violet-500/50" /> :
                    <div className="w-20 h-20 rounded-2xl bg-line-2 flex items-center justify-center text-2xl font-black text-paper">{user?.name?.charAt(0) || 'U'}</div>}
                  <div><p className="text-paper font-semibold">{user?.name}</p><p className="text-mute text-sm">{user?.email}</p></div>
                </div>
              </div>
            )}
            {active === 'Appearance' && (
              <div className="space-y-4">
                <h2 className="text-paper font-bold text-lg">Appearance</h2>
                <Toggle value={settings.darkMode} onChange={v => update('darkMode', v)} label="Dark Mode" description="Use dark theme across the app" />
                <Toggle value={settings.streamingMode} onChange={v => update('streamingMode', v)} label="Streaming Mode" description="Stream AI responses in real-time" />
              </div>
            )}
            {active === 'Notifications' && (
              <div className="space-y-4">
                <h2 className="text-paper font-bold text-lg">Notifications</h2>
                <Toggle value={settings.emailNotifications} onChange={v => update('emailNotifications', v)} label="Email Notifications" description="Receive updates via email" />
              </div>
            )}
            {active === 'Security' && (
              <div className="space-y-4">
                <h2 className="text-paper font-bold text-lg">Security</h2>
                <Toggle value={settings.twoFactor} onChange={v => update('twoFactor', v)} label="Two-Factor Auth" description="Extra layer of account security" />
                <button onClick={() => { logout(); toast.success('Logged out!'); }} className="flex items-center gap-2 px-4 py-2 bg-danger/10 border border-danger/30 rounded-xl text-danger text-sm"><LogOut className="w-4 h-4" /> Sign Out</button>
              </div>
            )}
            {active === 'API Keys' && <div><h2 className="text-paper font-bold text-lg mb-4">LLM Configuration</h2><input placeholder="sk-..." className="w-full bg-ink-2 border border-line rounded-xl px-4 py-2.5 text-paper text-sm font-mono outline-none" /></div>}
            {usage && <div className="mt-6 rounded-xl border border-line bg-ink-2 p-4"><p className="font-mono text-[10px] tracking-wider text-trace">{usage.plan.toUpperCase()} WORKSPACE QUOTA</p><p className="mt-2 text-sm text-paper">{usage.usage.tokens.toLocaleString()} / {usage.limit.tokens.toLocaleString()} tokens this month</p><div className="mt-2 h-1.5 overflow-hidden rounded bg-line"><div className="h-full bg-trace" style={{ width: `${Math.min(100, usage.usage.tokens / usage.limit.tokens * 100)}%` }} /></div><p className="mt-2 text-xs text-mute">{usage.usage.requests} / {usage.limit.requests} requests</p></div>}
            <button onClick={handleSave} className={`mt-8 flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm text-ink ${saved ? 'bg-trace' : 'bg-paper'}`}>
              {saved ? <><Check className="w-4 h-4" /> Saved!</> : <><Save className="w-4 h-4" /> Save Changes</>}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
