import { Command } from 'cmdk';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3, FileText, LayoutDashboard, MessageSquare, Plus, Settings, Upload } from 'lucide-react';
import toast from 'react-hot-toast';
import { useAuthStore } from '../../store/authStore';
import { useChatStore } from '../../store/chatStore';

const destinations = [
  ['Dashboard', '/dashboard', LayoutDashboard], ['Chat', '/chat', MessageSquare], ['Documents', '/documents', FileText],
  ['Analytics', '/analytics', BarChart3], ['Settings', '/settings', Settings],
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { isAuthenticated } = useAuthStore();
  const { createSession } = useChatStore();
  const closeAndNavigate = (path) => { setOpen(false); navigate(path); };
  const needsWorkspace = (path) => {
    if (!isAuthenticated) { setOpen(false); navigate('/login'); toast('Sign in to open the workspace.'); return; }
    closeAndNavigate(path);
  };
  const newChat = async () => {
    if (!isAuthenticated) { needsWorkspace('/chat'); return; }
    try {
      const session = await createSession({ title: 'New Chat' });
      closeAndNavigate(`/chat/${session.id}`);
      toast.success('New chat created');
    } catch { toast.error('Could not create a chat'); }
  };

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setOpen(value => !value);
      }
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  if (!open) return null;
  return <div className="fixed inset-0 z-[100] flex justify-center pt-[14vh] px-4" role="dialog" aria-modal="true" aria-label="Command palette">
    <button className="absolute inset-0 bg-ink/80" onClick={() => setOpen(false)} aria-label="Close command palette" />
    <Command className="relative w-full max-w-xl overflow-hidden rounded-lg border border-line-2 bg-ink-2 shadow-2xl font-sans">
      <div className="flex items-center border-b border-line px-4">
        <span className="font-mono text-xs text-trace mr-3">&gt;_</span>
        <Command.Input autoFocus placeholder="Jump to a surface or run an action..." className="w-full bg-transparent py-4 text-sm text-paper outline-none placeholder:text-mute" />
        <kbd className="font-mono text-[10px] text-mute border border-line rounded px-1.5 py-0.5">ESC</kbd>
      </div>
      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="px-3 py-8 text-center text-sm text-mute">No matching command.</Command.Empty>
        <Command.Group heading="Navigate" className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-mute">
          {destinations.map(([label, path, Icon]) => <Command.Item key={path} value={label} onSelect={() => needsWorkspace(path)} className="flex cursor-pointer items-center gap-3 rounded px-3 py-2.5 text-sm text-paper data-[selected=true]:bg-line data-[selected=true]:text-trace"><Icon className="h-4 w-4 text-mute" />{label}</Command.Item>)}
        </Command.Group>
        <Command.Group heading="Actions" className="mt-1 border-t border-line pt-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-mute">
          <Command.Item value="New chat" onSelect={newChat} className="flex cursor-pointer items-center gap-3 rounded px-3 py-2.5 text-sm text-paper data-[selected=true]:bg-line data-[selected=true]:text-trace"><Plus className="h-4 w-4 text-trace" />New chat</Command.Item>
          <Command.Item value="Upload document" onSelect={() => needsWorkspace('/documents')} className="flex cursor-pointer items-center gap-3 rounded px-3 py-2.5 text-sm text-paper data-[selected=true]:bg-line data-[selected=true]:text-trace"><Upload className="h-4 w-4 text-trace" />Upload document</Command.Item>
        </Command.Group>
      </Command.List>
      <div className="border-t border-line px-4 py-2 font-mono text-[10px] text-mute">CMD/CTRL K · COMMAND SURFACE</div>
    </Command>
  </div>;
}
