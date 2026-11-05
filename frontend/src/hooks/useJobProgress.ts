import { useEffect, useRef, useState } from "react";
import type { ProgressEvent } from "@/types";

/**
 * Subscribe to a job's live progress over WebSocket.  Falls back gracefully:
 * if the socket closes, the caller keeps polling the project detail.
 */
export function useJobProgress(jobId: string | null, enabled: boolean) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<string>("");
  const [done, setDone] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!jobId || !enabled) return;
    setEvents([]);
    setDone(false);
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/jobs/${jobId}`);
    wsRef.current = ws;

    ws.onmessage = (msg) => {
      const ev = JSON.parse(msg.data) as ProgressEvent;
      setEvents((prev) => [...prev, ev]);
      setProgress(ev.progress);
      setPhase(ev.phase);
      if (ev.phase === "done") setDone(true);
    };
    ws.onerror = () => {};
    ws.onclose = () => setDone(true);

    return () => {
      wsRef.current = null;
      ws.close();
    };
  }, [jobId, enabled]);

  return { events, progress, phase, done };
}
