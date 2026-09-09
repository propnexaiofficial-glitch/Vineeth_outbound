import { useEffect, useRef, useState } from 'react';
import { getApiKey } from '../api/client';

interface SSEOptions {
  onEvent?: (event: unknown) => void;
}

export function useSSE(options: SSEOptions = {}) {
  const [latestEvent, setLatestEvent] = useState<unknown>(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const apiKey = getApiKey();
      const url = apiKey
        ? `/api/events/stream?api_key=${encodeURIComponent(apiKey)}`
        : '/api/events/stream';

      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => setConnected(true);

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          setLatestEvent(data);
          options.onEvent?.(data);
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        setConnected(false);
        es.close();
        if (!cancelled) {
          reconnectTimer.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, []);

  return { latestEvent, connected };
}
