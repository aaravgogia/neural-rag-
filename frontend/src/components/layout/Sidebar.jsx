import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useLocation } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useAuthStore } from '../../store/authStore';
import { useChatStore } from '../../store/chatStore';
import { LayoutDashboard, MessageSquare, FileText, BarChart3, Settings, LogOut, ChevronLeft, ChevronRight, Radio } from 'lucide-react';
import toast from 'react-hot-toast';

const navItems = [
  { icon: LayoutDashboard, label: 'Dashboard', path: '/dashboard' },
  { icon: MessageSquare, label: 'Chat', path: '/chat' },
  { icon: FileText, label: 'Documents', path: '/documents' },
  { icon: BarChart3, label: 'Analytics', path: '/analytics' },
  { icon: Settings, label: 'Settings', path: '/settings' },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, workspaces, activeWorkspaceId, setActiveWorkspace, fetchWorkspaces } = useAuthStore();
  const [collapsed, setCollapsed] = useState(false);

  const handleLogout = () => { logout(); navigate('/'); toast.success('Logged out'); };
  useEffect(() => { if (user) fetchWorkspaces().catch(() => {}); }, [user]);

  return (
    <motion.aside animate={{ width: collapsed ? 64 : 240 }} className="relative flex flex-col h-screen bg-ink-2 border-r border-line shrink-0 z-30 font-sans">
      <button onClick={() => setCollapsed(!collapsed)} className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-ink border border-line-2 flex items-center justify-center z-50 hover:border-trace transition-colors">
        {collapsed ? <ChevronRight className="w-3 h-3 text-mute" /> : <ChevronLeft className="w-3 h-3 text-mute" />}
      </button>
      <div className="flex items-center gap-2.5 p-4 border-b border-line h-16">
        <div className="w-7 h-7 rounded-lg bg-paper text-ink flex items-center justify-center font-display font-bold shrink-0">N</div>
        {!collapsed && <div><span className="font-mono text-sm text-paper whitespace-nowrap">neuralrag</span><p className="font-mono text-[9px] text-trace tracking-widest">INTELLIGENCE OS</p></div>}
      </div>
      {!collapsed && <div className="px-3 pt-3"><p className="font-mono text-[10px] text-mute mb-1">WORKSPACE</p><select value={activeWorkspaceId || ''} onChange={e => setActiveWorkspace(e.target.value)} className="w-full bg-ink border border-line rounded-lg px-2 py-2 text-xs text-paper">{workspaces.map(w => <option key={w.id} value={w.id}>{w.name} · {w.role}</option>)}</select></div>}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname.startsWith(item.path);
          return (
            <button key={item.path} onClick={() => navigate(item.path)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded relative transition-colors ${isActive ? 'bg-line text-paper' : 'text-mute hover:text-paper hover:bg-line/50'}`}>
              {isActive && <div className="absolute left-0 top-1 bottom-1 w-0.5 bg-trace rounded-r" />}
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span className="text-sm whitespace-nowrap">{item.label}</span>}
            </button>
          );
        })}
      </nav>
      <div className="p-3 border-t border-line">
        {!collapsed && <div className="status-chip flex items-center gap-2 px-2.5 py-2 mb-3 rounded-lg font-mono text-[10px] text-trace"><Radio className="w-3 h-3 animate-pulse" />SYSTEMS NOMINAL</div>}
        <div className={`flex items-center gap-2.5 p-2 ${collapsed ? 'justify-center' : ''}`}>
          {user?.picture ? <img src={user.picture} alt={user.name} className="w-7 h-7 rounded-full shrink-0" /> :
            <div className="w-7 h-7 rounded-full bg-line-2 flex items-center justify-center text-xs font-mono text-paper shrink-0">{user?.name?.charAt(0) || 'U'}</div>}
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-paper text-xs truncate">{user?.name}</p>
              <p className="text-mute text-[11px] truncate font-mono">{user?.email}</p>
            </div>
          )}
          {!collapsed && <button onClick={handleLogout} className="text-mute hover:text-danger shrink-0"><LogOut className="w-3.5 h-3.5" /></button>}
        </div>
      </div>
    </motion.aside>
  );
}
