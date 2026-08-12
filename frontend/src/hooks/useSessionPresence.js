import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuthStore } from '../store/authStore';
import { WS_URL } from '../lib/endpoints';

/** Ephemeral presence channel; chat messages keep using the existing REST flow. */
export function useSessionPresence(sessionId) {
  const [users, setUsers] = useState([]);
  const [typists, setTypists] = useState([]);
  const socketRef = useRef(null);
  const typingRef = useRef(false);
  const stopTimerRef = useRef(null);
  const { token, user } = useAuthStore();

  const send = useCallback((event) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify(event));
  }, []);

  const notifyTyping = useCallback((value) => {
    if (!sessionId) return;
    if (stopTimerRef.current) clearTimeout(stopTimerRef.current);
    if (!value) {
      if (typingRef.current) send({ type: 'typing', is_typing: false });
      typingRef.current = false;
      return;
    }
    if (!typingRef.current) send({ type: 'typing', is_typing: true });
    typingRef.current = true;
    stopTimerRef.current = setTimeout(() => {
      if (typingRef.current) send({ type: 'typing', is_typing: false });
      typingRef.current = false;
    }, 900);
  }, [send, sessionId]);

  useEffect(() => {
    if (!sessionId || !token) { setUsers([]); setTypists([]); return undefined; }
    const socket = new WebSocket(`${WS_URL}/ws/chat/${sessionId}`);
    socketRef.current = socket;
    socket.onopen = () => send({ type: 'join', access_token: token });
    socket.onmessage = ({ data }) => {
      const event = JSON.parse(data);
      if (event.type === 'presence') setUsers(event.users || []);
      if (event.type === 'typing' && event.user?.id !== user?.id) {
        setTypists(current => event.is_typing
          ? [...current.filter(person => person.id !== event.user.id), event.user]
          : current.filter(person => person.id !== event.user.id));
      }
    };
    return () => {
      if (typingRef.current) send({ type: 'typing', is_typing: false });
      if (stopTimerRef.current) clearTimeout(stopTimerRef.current);
      socket.close();
      socketRef.current = null;
      typingRef.current = false;
    };
  }, [send, sessionId, token, user?.id]);

  return { users, typists, notifyTyping };
}
