import { useEffect, useState } from 'react';

const eventNames = [
  'telemetry', 'anomaly', 'suppressed', 'workflow_step', 'approval_requested',
  'approval_decided', 'sla_warning', 'sla_escalated', 'audit_event', 'health',
  'scenario_started', 'scenario_cleared', 'workflow_demo_injected',
] as const;

export type StreamEvent = { type: string; data: unknown; receivedAt: number };

export function useEventStream() {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [revision, setRevision] = useState(0);
  const [approvalRevision, setApprovalRevision] = useState(0);

  useEffect(() => {
    const base = import.meta.env.VITE_API_BASE_URL || '/api/v1';
    const source = new EventSource(`${base}/stream`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const handlers = eventNames.map((name) => {
      const handler = (event: Event) => {
        const message = event as MessageEvent<string>;
        let data: unknown = message.data;
        try { data = JSON.parse(message.data) as unknown; } catch { /* retain raw event data */ }
        setEvents((current) => [{ type: name, data, receivedAt: Date.now() }, ...current].slice(0, 100));
        if (name !== 'telemetry' && name !== 'health') setRevision((value) => value + 1);
        if (name === 'approval_requested' || name === 'approval_decided' || name === 'sla_escalated') {
          setApprovalRevision((value) => value + 1);
        }
      };
      source.addEventListener(name, handler);
      return [name, handler] as const;
    });
    return () => {
      handlers.forEach(([name, handler]) => source.removeEventListener(name, handler));
      source.close();
    };
  }, []);

  return { connected, events, revision, approvalRevision };
}