import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import {
  Activity, Check, ChevronDown, CircleAlert, CircleCheck, ClipboardCheck, Cpu,
  Clock3, ExternalLink, Filter, RotateCw, ShieldAlert, ShieldCheck, Siren, WifiOff,
} from 'lucide-react';
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Link } from 'react-router-dom';
import {
  api,
  decide,
  type ActiveScenario,
  type ApprovalPackage,
  type Asset,
  type AuditEvent,
  type ScenarioRun,
  type Technician,
  type Workflow,
} from '../api/client';
import type { StreamEvent } from '../hooks/useEventStream';
import { useLoad } from '../hooks/useLoad';

type Props = { refreshKey: number };

export function CommandCenter({ events, refreshKey }: Props & { events: StreamEvent[] }) {
  const assets = useLoad<Asset[]>('/assets', refreshKey);
  const approvals = useLoad<ApprovalPackage[]>('/approvals', refreshKey);
  const anomalies = useLoad<Record<string, unknown>[]>('/anomalies?limit=30', refreshKey);
  const workflows = useLoad<Workflow[]>('/workflows', refreshKey);
  const kpis = useLoad<Record<string, unknown>>('/kpis', refreshKey);
  const streamData = useMemo(() => events
    .filter((event) => event.type === 'telemetry' && isRecord(event.data) && typeof event.data.value === 'number')
    .slice(0, 40)
    .reverse()
    .map((event, index) => ({ index, value: (event.data as { value: number }).value })), [events]);
  const approvalsCount = approvals.data?.length ?? 0;
  const fleet = assets.data ?? [];

  return <>
    <PageHeading eyebrow="CONTROL ROOM / LIVE OVERVIEW" title="Command Center" subtitle="Simulated plant telemetry, maintenance risk, and human decisions." />
    <div className="kpi-strip">
      <Metric label="Pending decisions" value={approvalsCount.toString().padStart(2, '0')} detail="Approval queue" icon={<ClipboardIcon />} tone={approvalsCount ? 'amber' : 'green'} />
      <Metric label="Fleet health" value={fleet.length ? `${Math.round(fleet.reduce((sum, item) => sum + item.health_index, 0) / fleet.length)}%` : '—'} detail="Mean equipment index" icon={<Activity size={16} />} tone="green" />
      <Metric label="Anomalies" value={(anomalies.data?.length ?? 0).toString().padStart(2, '0')} detail="Current session" icon={<Siren size={16} />} tone="amber" />
      <Metric label="Suppressed" value={String((kpis.data?.suppressed_alerts as number | undefined) ?? 0).padStart(2, '0')} detail="Quiet + dedup windows" icon={<Filter size={16} />} tone="muted" />
      <Metric label="Workflows" value={(workflows.data?.length ?? 0).toString().padStart(2, '0')} detail="Session total" icon={<CircleCheck size={16} />} tone="green" />
    </div>

    <section className="layer-strip" aria-label="Pipeline layer status">
      <div className="section-label"><span>PIPELINE</span><b>8 LAYERS</b></div>
      <div className="layers">
        {['DataPulse', 'Features', 'Detection', 'AgentWeave', 'Grounding', 'Adapters', 'HITL', 'Foundation'].map((layer, index) => (
          <div className="layer" key={layer}><span className="layer-index">L{index + 1}</span><b>{layer}</b><i className="layer-led" /></div>
        ))}
      </div>
    </section>

    <div className="dashboard-grid">
      <section className="panel trend-panel">
        <div className="panel-heading"><div><span className="section-label">TELEMETRY</span><h2>Live sensor signal</h2></div><span className="panel-note"><i className="tiny-live" /> STREAM</span></div>
        {streamData.length > 1 ? <div className="chart-wrap">
          <ResponsiveContainer width="100%" height="100%"><AreaChart data={streamData}>
            <defs><linearGradient id="signalFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#b5e85d" stopOpacity={0.28} /><stop offset="100%" stopColor="#b5e85d" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid stroke="#26312c" vertical={false} />
            <XAxis dataKey="index" hide /><YAxis width={42} tick={{ fill: '#84928a', fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ background: '#18211d', border: '1px solid #344239', borderRadius: 4, color: '#edf1e8' }} />
            <Area type="monotone" dataKey="value" stroke="#b5e85d" strokeWidth={2} fill="url(#signalFill)" isAnimationActive={false} />
          </AreaChart></ResponsiveContainer>
        </div> : <EmptyState title="Waiting for telemetry" detail="The stream will draw here as readings arrive." />}
        <div className="chart-footer"><span>READINGS IN VIEW <b>{streamData.length}</b></span><span>ONE-WAY SIMULATOR FEED</span></div>
      </section>

      <section className="panel approval-panel">
        <div className="panel-heading"><div><span className="section-label">HUMAN GATE</span><h2>Needs a decision</h2></div><Link to="/approvals" className="text-link">Open queue <ExternalLink size={13} /></Link></div>
        {approvals.loading ? <Loading /> : approvalsCount ? <div className="approval-preview-list">
          {approvals.data?.slice(0, 3).map((item) => <Link className="approval-preview" to="/approvals" key={item.correlation_id}>
            <div className="approval-preview-top"><strong>{item.asset_id}</strong><span className="tier-tag">TIER {item.required_approver_tier}</span></div>
            <span>{item.anomaly_summary}</span><div className="preview-foot"><span>{item.reasons_for_hitl[0]?.replaceAll('_', ' ')}</span><Countdown deadline={item.sla_deadline} /></div>
          </Link>)}
        </div> : <EmptyState title="Queue clear" detail="No packages are waiting for approval." />}
      </section>

      <section className="panel fleet-panel">
        <div className="panel-heading"><div><span className="section-label">ASSET REGISTER</span><h2>Fleet health</h2></div><Link to="/assets" className="text-link">View fleet <ExternalLink size={13} /></Link></div>
        {assets.loading ? <Loading /> : <div className="fleet-list">{fleet.map((asset) => <div className="fleet-row" key={asset.asset_id}>
          <div className="health-ring" style={{ '--health': `${asset.health_index}%` } as CSSProperties & { '--health': string }}><span>{Math.round(asset.health_index)}</span></div>
          <div className="fleet-asset"><strong>{asset.asset_id}</strong><span>{asset.name}</span></div>
          <span className="tier-tag">T{asset.criticality_tier}</span>
          {asset.safety_critical !== false ? <span className="safety-mark" title="Safety classification requires human approval"><ShieldAlert size={15} />{asset.safety_critical === null ? 'UNCLASSIFIED' : 'SAFETY'}</span> : <span className="normal-mark"><ShieldCheck size={14} /> NORMAL</span>}
        </div>)}</div>}
      </section>

      <section className="panel activity-panel">
        <div className="panel-heading"><div><span className="section-label">AGENT ACTIVITY</span><h2>Recent workflow steps</h2></div><Link to="/trace" className="text-link">Trace <ExternalLink size={13} /></Link></div>
        <div className="activity-feed">{events.filter((event) => event.type === 'workflow_step').slice(0, 7).map((event, index) => {
          const item = isRecord(event.data) ? event.data : {};
          return <div className="activity-row" key={`${event.receivedAt}-${index}`}><span className={`activity-dot ${item.outcome === 'partial' ? 'warn' : ''}`} /><div><strong>{String(item.node || 'workflow')}</strong><span>{String(item.outcome || 'running')} · {String(item.correlation_id || 'new run')}</span></div><time>{new Date(event.receivedAt).toLocaleTimeString()}</time></div>;
        })}{!events.some((event) => event.type === 'workflow_step') && <EmptyState title="No agent activity yet" detail="Steps appear when an anomaly enters the workflow." />}</div>
      </section>
    </div>
  </>;
}

export function AnomaliesPage({ refreshKey }: Props) {
  const { data, error, loading } = useLoad<Record<string, unknown>[]>('/anomalies?limit=200', refreshKey);
  const [assetFilter, setAssetFilter] = useState('all');
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const rows = (data ?? []).filter((item) => assetFilter === 'all' || item.asset_id === assetFilter);
  const assetIds = [...new Set((data ?? []).map((item) => String(item.asset_id)))];
  return <>
    <PageHeading eyebrow="SIGNAL REVIEW" title="Anomalies" subtitle="Detected events with source telemetry and ensemble evidence." />
    <div className="toolbar"><label className="select-control"><Filter size={14} /><select value={assetFilter} onChange={(event) => setAssetFilter(event.target.value)}><option value="all">All assets</option>{assetIds.map((id) => <option key={id}>{id}</option>)}</select><ChevronDown size={14} /></label><span className="toolbar-count">{rows.length} EVENTS</span></div>
    <section className="panel table-panel">{loading ? <Loading /> : error ? <ErrorState message={error} /> : rows.length ? <div className="table-scroll"><table><thead><tr><th>TIME</th><th>ASSET</th><th>TYPE</th><th>SEVERITY</th><th>MODE</th><th>EVENT</th></tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.anomaly_id || index)} onClick={() => setSelected(row)} className="click-row"><td>{formatTime(String(row.detected_at || ''))}</td><td className="mono">{String(row.asset_id)}</td><td>{String(row.anomaly_type).replaceAll('_', ' ')}</td><td><Severity value={Number(row.severity || 0)} /></td><td>{row.shadow ? <span className="mode-pill shadow">SHADOW</span> : <span className="mode-pill">LIVE</span>}</td><td><button className="icon-button" title="Open event details" onClick={(event) => { event.stopPropagation(); setSelected(row); }}><ExternalLink size={15} /></button></td></tr>)}</tbody></table></div> : <EmptyState title="No anomalies recorded" detail="Inject a simulator scenario to produce a labeled event." />}</section>
    {selected && <div className="drawer-backdrop" onClick={() => setSelected(null)}><aside className="detail-drawer" onClick={(event) => event.stopPropagation()}><button className="drawer-close" onClick={() => setSelected(null)} aria-label="Close details">×</button><span className="section-label">EVENT DETAIL</span><h2>{String(selected.asset_id)} / {String(selected.anomaly_type)}</h2><p>{String(selected.anomaly_id)}</p><pre>{JSON.stringify(selected.evidence ?? {}, null, 2)}</pre></aside></div>}
  </>;
}

export function ApprovalsPage({ refreshKey }: Props) {
  const [revision, setRevision] = useState(0);
  const { data, error, loading } = useLoad<ApprovalPackage[]>('/approvals', refreshKey + revision);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [taskDraft, setTaskDraft] = useState('');
  const [priorityDraft, setPriorityDraft] = useState<number | null>(null);
  const [technicianDraft, setTechnicianDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const technicians = useLoad<Technician[]>('/technicians', refreshKey);
  const selected = data?.find((item) => item.correlation_id === selectedId) ?? data?.[0] ?? null;

  async function submit(action: 'approve' | 'modify_approve' | 'reject' | 'escalate') {
    if (!selected) return;
    setSubmitting(true); setMessage(null);
    try {
      if (action === 'modify_approve') {
        await api(`/approvals/${encodeURIComponent(selected.correlation_id)}/decision`, {
          method: 'POST', headers: { 'X-Approver-Id': 'ops-console-user' },
          body: JSON.stringify({
            correlation_id: selected.correlation_id, decision: action, approver: 'ops-console-user',
            modifications: {
              ...(priorityDraft ? { priority: priorityDraft } : {}),
              ...(taskDraft ? { tasks: taskDraft.split('\n').filter(Boolean) } : {}),
              ...(technicianDraft ? { technician_id: technicianDraft } : {}),
            },
          }),
        });
      } else {
        await decide(selected.correlation_id, action, reason || undefined);
      }
      setReason(''); setTaskDraft(''); setPriorityDraft(null); setTechnicianDraft(''); setRevision((value) => value + 1);
      setMessage(action === 'reject' ? 'Work order rejected. No parts were reserved.' : action === 'escalate' ? 'Approval escalated to the next tier.' : 'Decision recorded.');
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Decision failed'); }
    finally { setSubmitting(false); }
  }

  return <>
    <PageHeading eyebrow="HUMAN-IN-THE-LOOP / REQUIRED" title="Approval queue" subtitle="No work order confirmation, parts reservation, or dispatch occurs before your decision." />
    {message && <div className="inline-message" role="status">{message}</div>}
    {loading ? <Loading /> : error ? <ErrorState message={error} /> : !data?.length ? <EmptyState title="No pending decisions" detail="New packages will appear here with their SLA deadline." /> : <div className="approval-layout">
      <section className="queue-column"><div className="queue-heading"><span>PRIORITY QUEUE</span><b>{data.length.toString().padStart(2, '0')}</b></div>{data.map((item) => <button key={item.correlation_id} className={`queue-item ${selected?.correlation_id === item.correlation_id ? 'selected' : ''}`} onClick={() => { setSelectedId(item.correlation_id); setReason(''); setTechnicianDraft(''); }}><div className="queue-item-head"><strong>{item.asset_id}</strong><span>T{item.required_approver_tier}</span></div><p>{item.anomaly_summary}</p><small>{item.reasons_for_hitl.map((reasonItem) => reasonItem.replaceAll('_', ' ')).join(' · ')}</small><Countdown deadline={item.sla_deadline} /></button>)}</section>
      {selected && <section className="approval-detail">
        <div className="detail-title-row"><div><span className="section-label">PACKAGE / {selected.correlation_id}</span><h2>{selected.asset_id} <span className="severity-word">{selected.anomaly_summary}</span></h2></div><div className="deadline-box"><Clock3 size={15} /><span>DEADLINE</span><b>{new Date(selected.sla_deadline).toLocaleTimeString()}</b></div></div>
        {selected.partial && <div className="degraded-banner"><WifiOff size={16} /><div><strong>Partial approval package</strong><span>{selected.degraded_reasons.join(' · ')}</span></div></div>}
        <div className="reasons-row">{selected.reasons_for_hitl.map((tag) => <span className={`reason-chip ${tag.includes('safety') ? 'safety' : ''}`} key={tag}>{tag.replaceAll('_', ' ')}</span>)}</div>
        <div className="detail-columns">
          <div className="detail-section"><div className="section-title"><span>DIAGNOSIS</span><b>TOP {selected.diagnosis.candidates.length}</b></div>{selected.diagnosis.candidates.map((candidate, index) => <div className="candidate" key={`${candidate.failure_mode}-${index}`}><div className="candidate-head"><strong>{candidate.failure_mode}</strong><span>{Math.round(candidate.confidence * 100)}% confidence</span>{candidate.verified ? <Check size={14} className="ok-icon" /> : <CircleAlert size={14} className="warning-icon" />}</div><p>{candidate.rationale}</p>{candidate.citations.map((citation) => <details className="citation" key={`${citation.document}-${citation.section}`}><summary>{citation.document} / {citation.section}</summary><blockquote>{citation.passage}</blockquote></details>)}</div>)}</div>
          <div className="detail-section"><div className="section-title"><span>DRAFT WORK ORDER</span><b>NOT CONFIRMED</b></div>{selected.work_order ? <><div className="order-summary"><strong>{selected.work_order.summary}</strong><span>Priority {selected.work_order.priority} · ${selected.work_order.estimated_cost_usd.toFixed(2)}</span></div><label className="field-label" htmlFor="tasks-edit">Tasks / one per line</label><textarea id="tasks-edit" rows={4} value={taskDraft || selected.work_order.tasks.join('\n')} onChange={(event) => setTaskDraft(event.target.value)} /><label className="field-label" htmlFor="priority-edit">Priority</label><input id="priority-edit" type="number" min="1" max="5" value={priorityDraft ?? selected.work_order.priority} onChange={(event) => setPriorityDraft(Number(event.target.value))} /><div className="parts-review"><span className="section-title">PARTS CHECK</span>{selected.work_order.parts.map((part) => <div className="part-line" key={part.part_number}><span>{part.part_number} / {part.description}</span><b>{selected.parts.long_lead.includes(part.part_number) ? 'LONG LEAD' : selected.parts.parts_tbc ? 'TBC' : 'CHECKED'}</b></div>)}</div></> : <p className="muted-copy">No work order draft is available. Review the degraded reasons before deciding.</p>}
          </div>
        </div>
        <div className="technician-row"><div><span className="section-title">TECHNICIAN PROPOSAL</span><strong>{selected.technician?.name ?? 'No qualified technician found'}</strong></div><span>{selected.technician?.skill_match.join(' · ') ?? 'Manual scheduling required'}</span></div>
        <label className="field-label" htmlFor="technician-edit">Replacement technician for modify + approve</label>
        <select id="technician-edit" className="technician-select" value={technicianDraft} onChange={(event) => setTechnicianDraft(event.target.value)}>
          <option value="">Keep current proposal</option>
          {technicians.data?.map((technician) => <option value={technician.technician_id} key={technician.technician_id}>{technician.technician_id} / {technician.name} · {technician.skills.join(', ')}</option>)}
        </select>
        <label className="field-label" htmlFor="decision-reason">Reason required for reject or escalate</label><textarea id="decision-reason" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Record decision context" />
        <div className="decision-actions"><button className="button button-primary" disabled={submitting} onClick={() => void submit('approve')}><Check size={15} />Approve</button><button className="button button-secondary" disabled={submitting} onClick={() => void submit('modify_approve')}><Activity size={15} />Modify + approve</button><button className="button button-danger" disabled={submitting || !reason.trim()} onClick={() => void submit('reject')}>Reject</button><button className="button button-secondary" disabled={submitting || !reason.trim()} onClick={() => void submit('escalate')}>Escalate</button></div>
      </section>}
    </div>}
  </>;
}

export function TracePage({ refreshKey }: Props) {
  const { data, error, loading } = useLoad<Workflow[]>('/workflows', refreshKey);
  const [selectedId, setSelectedId] = useState('');
  const workflows = data ?? [];
  const selected = workflows.find((item) => item.correlation_id === selectedId) ?? workflows[0];
  return <>
    <PageHeading eyebrow="EXECUTION DETAIL" title="Workflow trace" subtitle="Node outcomes, timing, models, and degraded paths for this session." />
    <div className="toolbar"><label className="select-control"><Activity size={14} /><select value={selected?.correlation_id ?? ''} onChange={(event) => setSelectedId(event.target.value)}><option value="">Select correlation ID</option>{workflows.map((item) => <option key={item.correlation_id} value={item.correlation_id}>{item.correlation_id} · {item.asset.asset_id}</option>)}</select><ChevronDown size={14} /></label></div>
    {loading ? <Loading /> : error ? <ErrorState message={error} /> : selected ? <section className="panel trace-panel"><div className="trace-summary"><div><span className="section-label">{selected.correlation_id}</span><h2>{selected.asset.asset_id} / {selected.status}</h2></div><Link to="/audit" className="text-link">Audit events <ExternalLink size={13} /></Link></div><div className="timeline">{selected.trace.map((step, index) => <div className="timeline-item" key={`${step.node}-${index}`}><span className={`timeline-marker ${step.outcome === 'partial' ? 'warn' : ''}`} /><div className="timeline-content"><div><strong>{step.node}</strong><span className={`outcome ${step.outcome}`}>{step.outcome}</span></div><small>{step.model || 'deterministic'} · {step.duration_ms.toFixed(1)} ms</small></div></div>)}</div></section> : <EmptyState title="No workflows yet" detail="A detected event will create a trace." />}
  </>;
}

export function AssetsPage({ refreshKey }: Props) {
  const { data, loading, error } = useLoad<Asset[]>('/assets', refreshKey);
  const [selectedId, setSelectedId] = useState('');
  const selected = data?.find((asset) => asset.asset_id === selectedId) ?? data?.[0];
  const telemetryAssetId = selected?.asset_id ?? 'WD-001';
  const telemetry = useLoad<Record<string, unknown>[]>(
    `/assets/${telemetryAssetId}/telemetry?window=1h`,
    refreshKey,
  );
  const scenarioRuns = useLoad<ScenarioRun[]>('/simulator/runs', refreshKey);
  const chart = (telemetry.data ?? []).slice(-120).map((reading, index) => ({
    index,
    value: Number(reading.value),
    timestamp: new Date(String(reading.timestamp_utc)).getTime(),
    measure: String(reading.measurement_type),
  }));
  const scenarioRanges = (scenarioRuns.data ?? [])
    .filter((run) => run.asset_id === selected?.asset_id)
    .map((run) => {
      const start = new Date(run.start_time_utc).getTime();
      const end = new Date(run.end_time_utc ?? Date.now()).getTime();
      const startIndex = chart.findIndex((point) => point.timestamp >= start);
      let endIndex = -1;
      for (let index = chart.length - 1; index >= 0; index -= 1) {
        if (chart[index].timestamp <= end) { endIndex = index; break; }
      }
      return startIndex >= 0 && endIndex >= startIndex
        ? { scenario_id: run.scenario_id, startIndex, endIndex }
        : null;
    })
    .filter((range): range is { scenario_id: string; startIndex: number; endIndex: number } => range !== null);
  return <>
    <PageHeading eyebrow="FLEET CONDITION" title="Assets & health" subtitle="Condition index, criticality, and recent sensor readings." />
    {loading ? <Loading /> : error ? <ErrorState message={error} /> : <div className="asset-layout"><section className="panel asset-table"><div className="section-title"><span>FLEET REGISTER</span><b>{data?.length ?? 0} ASSETS</b></div>{data?.map((asset) => <button className={`asset-choice ${selected?.asset_id === asset.asset_id ? 'selected' : ''}`} key={asset.asset_id} onClick={() => setSelectedId(asset.asset_id)}><span className="mono">{asset.asset_id}</span><span>{asset.name}</span><span className="health-value">{asset.health_index.toFixed(0)}</span></button>)}</section>{selected && <section className="asset-detail"><div className="asset-detail-head"><div><span className="section-label">{selected.site_id} / {selected.location}</span><h2>{selected.name}</h2></div><span className="health-large">{selected.health_index.toFixed(0)}<small>HEALTH</small></span></div><div className="asset-meta"><span>TIER {selected.criticality_tier}</span><span>{selected.asset_class.replaceAll('_', ' ')}</span><span>{selected.safety_critical === null ? 'CLASSIFICATION MISSING' : selected.safety_critical ? 'SAFETY CRITICAL' : 'STANDARD'}</span></div><section className="panel chart-panel"><div className="section-title"><span>RECENT TELEMETRY</span><b>{chart.length} SAMPLES</b></div>{chart.length ? <ResponsiveContainer width="100%" height={230}><LineChart data={chart}><CartesianGrid stroke="#26312c" vertical={false} /><XAxis dataKey="index" hide /><YAxis tick={{ fill: '#84928a', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#18211d', border: '1px solid #344239', borderRadius: 4 }} />{scenarioRanges.map((range) => <ReferenceArea key={range.scenario_id} x1={range.startIndex} x2={range.endIndex} fill="#f0bf68" fillOpacity={0.14} stroke="#f0bf68" strokeOpacity={0.5} />)}<Line type="monotone" dataKey="value" stroke="#b5e85d" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer> : <EmptyState title="No readings in this window" detail="Run the simulator to populate recent telemetry." />}{scenarioRanges.length > 0 && <span className="chart-legend"><i /> Shaded bands indicate injected scenario windows</span>}</section></section>}</div>}
  </>;
}

export function AuditPage({ refreshKey }: Props) {
  const { data, error, loading } = useLoad<AuditEvent[]>('/audit', refreshKey);
  const [filter, setFilter] = useState('');
  const [verification, setVerification] = useState<{ ok: boolean; first_bad_seq: number | null } | null>(null);
  const rows = (data ?? []).filter((item) => !filter || item.correlation_id.includes(filter));
  async function verify() {
    setVerification(await api<{ ok: boolean; first_bad_seq: number | null }>('/audit/verify'));
  }
  return <>
    <PageHeading eyebrow="IMMUTABLE EVENT HISTORY" title="Audit ledger" subtitle="Every workflow step and human decision is hash-linked." />
    <div className="toolbar"><input className="filter-input" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter correlation ID" /><button className="button button-secondary" onClick={() => void verify()}><ShieldCheck size={15} />Verify chain</button>{verification && <span className={`verify-result ${verification.ok ? 'good' : 'bad'}`}>{verification.ok ? 'CHAIN OK' : `FIRST BAD SEQ ${verification.first_bad_seq}`}</span>}</div>
    <section className="panel table-panel">{loading ? <Loading /> : error ? <ErrorState message={error} /> : rows.length ? <div className="table-scroll"><table><thead><tr><th>SEQ</th><th>UTC</th><th>ACTOR</th><th>EVENT</th><th>CORRELATION</th><th>HASH / PREVIOUS</th></tr></thead><tbody>{rows.map((event) => <tr key={event.seq}><td className="mono">{event.seq}</td><td>{formatTime(event.timestamp_utc)}</td><td>{event.actor}</td><td>{event.event_type.replaceAll('_', ' ')}</td><td className="mono">{event.correlation_id}</td><td className="hash-cell"><span>{event.hash.slice(0, 12)}</span><small>← {event.prev_hash.slice(0, 12)}</small></td></tr>)}</tbody></table></div> : <EmptyState title="Ledger is empty" detail="System events will be recorded here." />}</section>
  </>;
}

export function SystemPage({ refreshKey }: Props) {
  const config = useLoad<Record<string, unknown>>('/system/config', refreshKey);
  const stats = useLoad<Record<string, unknown>>('/llm/stats', refreshKey);
  const kpis = useLoad<Record<string, unknown>>('/kpis', refreshKey);
  const statCalls = (stats.data?.calls as Record<string, unknown>[] | undefined) ?? [];
  return <>
    <PageHeading eyebrow="RUNTIME OBSERVABILITY" title="LLM & system" subtitle="Model calls, adapter mode, guardrails, and simulator-measured service levels." />
    <div className="kpi-strip system-kpis"><Metric label="LLM calls" value={String(stats.data?.call_count ?? '—')} detail="Session total" icon={<Cpu size={16} />} tone="green" /><Metric label="Fallbacks" value={String(stats.data?.fallback_count ?? 0)} detail="Fast model / fake mode" icon={<RotateCw size={16} />} tone="amber" /><Metric label="Prompt tokens" value={String(stats.data?.prompt_tokens ?? 0)} detail="Reported by client" icon={<Activity size={16} />} tone="muted" /><Metric label="P95 latency" value={stats.data?.p95_latency_seconds ? `${Number(stats.data.p95_latency_seconds).toFixed(2)}s` : '—'} detail="Observed calls" icon={<Clock3 size={16} />} tone="green" /></div>
    <div className="system-grid"><section className="panel"><div className="panel-heading"><div><span className="section-label">CONFIGURATION</span><h2>Guardrails & adapters</h2></div></div>{config.data ? <pre className="json-view">{JSON.stringify(config.data, null, 2)}</pre> : <Loading />}</section><section className="panel"><div className="panel-heading"><div><span className="section-label">MODEL CALLS</span><h2>Recent requests</h2></div></div>{statCalls.length ? <div className="call-list">{statCalls.slice(-12).reverse().map((call, index) => <div className="call-row" key={index}><span className={call.ok ? 'ok-icon' : 'warning-icon'}>{call.ok ? <Check size={14} /> : <CircleAlert size={14} />}</span><strong>{String(call.model)}</strong><small>{call.ok ? 'OK' : String(call.error)}</small></div>)}</div> : <EmptyState title="No model calls" detail="Calls will appear when a workflow runs." />}</section></div>
    <section className="slo-strip"><div><span className="section-label">SIMULATOR SLO TARGETS</span><p>Measured values remain unavailable until the evaluation run is recorded.</p></div><span className="slo-state">NOT MEASURED</span><small>Signal → anomaly &lt; 60 s · Draft WO &lt; 5 min · HITL notice &lt; 10 min</small></section>
    <span className="sr-only">KPI snapshot: {JSON.stringify(kpis.data ?? {})}</span>
  </>;
}

export function SimulatorPage() {
  const assets = useLoad<Asset[]>('/assets');
  const [scenarioRevision, setScenarioRevision] = useState(0);
  const activeScenarios = useLoad<ActiveScenario[]>('/simulator/scenarios', scenarioRevision);
  const scenarioRuns = useLoad<ScenarioRun[]>('/simulator/runs', scenarioRevision);
  const [selectedAsset, setSelectedAsset] = useState('WD-001');
  const [severity, setSeverity] = useState(0.8);
  const [durationTicks, setDurationTicks] = useState(120);
  const [scenarioSeed, setScenarioSeed] = useState(17);
  const [measurementType, setMeasurementType] = useState('vibration_rms');
  const [recoveryAfterTicks, setRecoveryAfterTicks] = useState(40);
  const [message, setMessage] = useState('');
  const [failures, setFailures] = useState({ cmms_down: false, inventory_down: false, llm_fail: false });
  async function scenario(name: string) {
    try {
      const result = await api<{ detected: boolean; pending_approvals: number }>('/simulator/scenarios', {
        method: 'POST',
        body: JSON.stringify({
          asset_id: selectedAsset,
          scenario: name,
          severity,
          duration_ticks: durationTicks,
          seed: scenarioSeed,
          measurement_type: measurementType,
          ...(name === 'recovering_bearing_wear'
            ? { recovery_after_ticks: recoveryAfterTicks }
            : {}),
        }),
      });
      setScenarioRevision((value) => value + 1);
      setMessage(
        result.detected
          ? `${name.replaceAll('_', ' ')} · detector event observed · ${result.pending_approvals} approval(s) pending`
          : `${name.replaceAll('_', ' ')} active · no detector event observed yet`,
      );
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Scenario failed'); }
  }
  async function clearScenario(assetId: string) {
    try {
      await api(`/simulator/scenarios/${encodeURIComponent(assetId)}`, { method: 'DELETE' });
      setScenarioRevision((value) => value + 1);
      setMessage(`Scenario cleared for ${assetId}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Scenario clear failed'); }
  }
  async function injectWorkflowDemo() {
    try {
      const result = await api<{ status: string }>('/simulator/demo-workflow', {
        method: 'POST',
        body: JSON.stringify({ asset_id: selectedAsset }),
      });
      setMessage(`Direct workflow demo event · ${result.status} · not a detector event`);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Workflow demo failed'); }
  }
  async function control(action: 'pause' | 'resume' | 'reset') {
    try { await api(`/simulator/${action}`, { method: 'POST' }); setMessage(`Simulator ${action}d`); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Control failed'); }
  }
  async function toggleFailure(key: keyof typeof failures) {
    const updated = { ...failures, [key]: !failures[key] };
    setFailures(updated);
    try { await api('/simulator/failures', { method: 'POST', body: JSON.stringify(updated) }); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Failure injection failed'); }
  }
  return <>
    <PageHeading eyebrow="CONTROLLED DEMONSTRATION" title="Simulator" subtitle="Inject labeled scenarios and integration failures into the isolated demo plant." />
    {message && <div className="inline-message" role="status">{message}</div>}
    <div className="simulator-toolbar"><label className="field-label" htmlFor="scenario-asset">TARGET ASSET</label><select id="scenario-asset" value={selectedAsset} onChange={(event) => setSelectedAsset(event.target.value)}>{assets.data?.map((asset) => <option value={asset.asset_id} key={asset.asset_id}>{asset.asset_id} / {asset.name}</option>)}</select><div className="button-row"><button className="button button-primary" onClick={() => void control('resume')}>Resume</button><button className="button button-secondary" onClick={() => void control('pause')}>Pause</button><button className="button button-secondary" onClick={() => void control('reset')}>Reset</button></div></div>
    <div className="scenario-settings">
      <label htmlFor="scenario-severity">Severity <output>{severity.toFixed(1)}</output><input id="scenario-severity" type="range" min="0.1" max="1" step="0.1" value={severity} onChange={(event) => setSeverity(Number(event.target.value))} /></label>
      <label htmlFor="scenario-duration">Duration in ticks<input id="scenario-duration" type="number" min="1" max="10000" value={durationTicks} onChange={(event) => setDurationTicks(Number(event.target.value))} /></label>
      <label htmlFor="scenario-seed">Random seed<input id="scenario-seed" type="number" value={scenarioSeed} onChange={(event) => setScenarioSeed(Number(event.target.value))} /></label>
      <label htmlFor="scenario-measurement">Target sensor<select id="scenario-measurement" value={measurementType} onChange={(event) => setMeasurementType(event.target.value)}><option value="vibration_rms">Vibration RMS</option><option value="temperature">Temperature</option><option value="current">Current</option><option value="pressure">Pressure</option></select></label>
      <label htmlFor="scenario-recovery">Recovery starts at tick<input id="scenario-recovery" type="number" min="1" max={Math.max(1, durationTicks - 1)} value={recoveryAfterTicks} onChange={(event) => setRecoveryAfterTicks(Number(event.target.value))} /></label>
    </div>
    <section className="scenario-section"><div className="section-title"><span>LABELED SCENARIOS</span><b>DETERMINISTIC INPUTS</b></div><div className="scenario-grid">{[['healthy', 'Healthy', 'Reference operation'], ['bearing_wear', 'Bearing wear', 'Vibration + temperature drift'], ['intermittent_bearing', 'Intermittent bearing', 'Repeating fault bursts'], ['recovering_bearing_wear', 'Recovering bearing wear', 'Fault followed by recovery'], ['overheat', 'Overheat', 'Temperature + current rise'], ['pressure_drop', 'Pressure drop', 'Pressure trend decreases'], ['safety_critical_case', 'Safety-critical case', 'Chiller authorization path'], ['unclassified_case', 'Unclassified case', 'Missing safety classification'], ['sensor_dropout', 'Sensor dropout', 'Readings disappear'], ['bad_quality', 'Bad-quality readings', 'Quality flags go bad'], ['out_of_order', 'Out-of-order timestamps', 'Time skew in selected sensor']].map(([value, title, detail]) => <button className="scenario-button" key={value} onClick={() => void scenario(value)}><span className="scenario-glyph"><Activity size={17} /></span><strong>{title}</strong><small>{detail}</small></button>)}</div></section>
    <section className="scenario-section"><div className="section-title"><span>ACTIVE SCENARIOS</span><b>{activeScenarios.data?.length ?? 0} RUNNING</b></div>{activeScenarios.data?.length ? <div className="active-scenario-list">{activeScenarios.data.map((active) => <div className="active-scenario" key={active.scenario_id}><div><strong>{active.asset_id} / {active.scenario.replaceAll('_', ' ')}</strong><span>Severity {active.severity.toFixed(1)} · {active.remaining_ticks ?? '∞'} ticks remaining · {active.measurement_type ?? 'all sensors'} · seed {active.seed ?? 'default'}</span></div><button className="button button-secondary" onClick={() => void clearScenario(active.asset_id)}>Clear</button></div>)}</div> : <p className="muted-copy">No timed scenarios are active.</p>}</section>
    <section className="scenario-section"><div className="section-title"><span>SCENARIO RESULTS</span><b>GROUND TRUTH VS DETECTOR</b></div>{scenarioRuns.data?.length ? <div className="table-scroll"><table><thead><tr><th>ASSET / SCENARIO</th><th>DETECTOR</th><th>DELAY</th><th>FALSE POSITIVES</th><th>RUN</th></tr></thead><tbody>{scenarioRuns.data.slice().reverse().map((run) => <tr key={run.scenario_id}><td>{run.asset_id} / {run.scenario.replaceAll('_', ' ')}</td><td>{run.detected ? `DETECTED (${run.detected_count})` : run.missed ? 'MISSED' : 'NO EVENT'}</td><td>{run.detection_latency_seconds === null ? 'N/A' : `${run.detection_latency_seconds.toFixed(1)} s`}</td><td>{run.false_positive_count}</td><td>{run.status}</td></tr>)}</tbody></table></div> : <p className="muted-copy">Inject a scenario to record detector outcomes against its ground-truth window.</p>}</section>
    <section className="scenario-section workflow-demo-section"><div><div className="section-title"><span>WORKFLOW DEMONSTRATION</span><b>SEPARATE FROM DETECTION</b></div><p className="muted-copy">Send a labeled demo event straight to approval without adding a detector anomaly.</p></div><button className="button button-primary" onClick={() => void injectWorkflowDemo()}>Send workflow demo event</button></section>
    <section className="scenario-section failure-section"><div className="section-title"><span>FAILURE INJECTION</span><b>DEGRADED-PATH TESTING</b></div><div className="failure-list">{([["cmms_down", "CMMS unavailable"], ["inventory_down", "Inventory unavailable"], ["llm_fail", "LLM unavailable"]] as const).map(([key, title]) => <label className="failure-toggle" key={key}><span><strong>{title}</strong><small>Simulate dependency failure</small></span><input type="checkbox" checked={failures[key]} onChange={() => void toggleFailure(key)} /><i /></label>)}</div></section>
    <p className="simulator-limit"><ShieldAlert size={15} />No OT connection. Scenarios affect in-memory simulator data only.</p>
  </>;
}

function PageHeading({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div><span className="session-clock">SESSION / DEMO-01</span></div>;
}

function Metric({ label, value, detail, icon, tone }: { label: string; value: string; detail: string; icon: ReactNode; tone: string }) {
  return <div className={`metric metric-${tone}`}><div className="metric-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><small>{detail}</small></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><span className="empty-mark"><Activity size={17} /></span><strong>{title}</strong><p>{detail}</p></div>;
}

function Loading() { return <div className="loading-state"><span className="spinner" /> Loading live data</div>; }
function ErrorState({ message }: { message: string }) { return <div className="error-state"><CircleAlert size={16} />{message}</div>; }
function ClipboardIcon() { return <ClipboardCheck size={16} />; }
function Severity({ value }: { value: number }) { return <span className={`severity ${value >= 0.8 ? 'high' : value >= 0.55 ? 'medium' : 'low'}`}><i />{Math.round(value * 100)}%</span>; }
function Countdown({ deadline }: { deadline: string }) {
  const [, setMinute] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setMinute((value) => value + 1), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = Math.max(0, Math.round((new Date(deadline).getTime() - Date.now()) / 60000));
  return <span className={`countdown ${remaining < 15 ? 'urgent' : ''}`}><Clock3 size={12} />{remaining ? `${remaining}m left` : 'SLA breached'}</span>;
}
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null; }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(); }