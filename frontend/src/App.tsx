import {
  Activity,
  AlertTriangle,
  ClipboardCheck,
  Cpu,
  Database,
  Gauge,
  Radio,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { NavLink, Route, Routes, useLocation } from 'react-router-dom';
import type { ApprovalPackage } from './api/client';
import { useEventStream } from './hooks/useEventStream';
import { useLoad } from './hooks/useLoad';
import {
  AnomaliesPage,
  ApprovalsPage,
  AssetsPage,
  AuditPage,
  CommandCenter,
  SimulatorPage,
  SystemPage,
  TracePage,
} from './pages';

const navigation: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: '/', label: 'Command Center', icon: Gauge, end: true },
  { to: '/anomalies', label: 'Anomalies', icon: AlertTriangle },
  { to: '/approvals', label: 'Approvals', icon: ClipboardCheck },
  { to: '/trace', label: 'Workflow Trace', icon: Activity },
  { to: '/assets', label: 'Assets & Health', icon: Wrench },
  { to: '/audit', label: 'Audit Ledger', icon: Database },
  { to: '/system', label: 'LLM & System', icon: Cpu },
  { to: '/simulator', label: 'Simulator', icon: Radio },
];

export default function App() {
  const { connected, events, revision, approvalRevision } = useEventStream();
  const approvals = useLoad<ApprovalPackage[]>('/approvals', approvalRevision);
  const location = useLocation();
  const current = navigation.find((item) => item.to === location.pathname)?.label || 'Operations';
  const liveMode = import.meta.env.VITE_PIPELINE_MODE || 'live';

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Activity size={19} strokeWidth={2.5} /></div>
          <div><strong>FIELD / SIGNAL</strong><span>MAINTENANCE SYSTEMS</span></div>
        </div>
        <div className="site-select"><span className="site-dot" /> North Plant <span className="site-code">NP-01</span></div>
        <nav aria-label="Primary navigation">
          <span className="nav-caption">OPERATIONS</span>
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
              {label === 'Approvals' && <ApprovalCount count={approvals.data?.length ?? 0} />}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="operator-avatar">OP</div>
          <div><strong>Operations desk</strong><span>Tier 2 approver</span></div>
          <span className="presence-dot" aria-label="Operator active" />
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb"><span>PLANT / MAINTENANCE</span><b>/</b><strong>{current}</strong></div>
          <div className="topbar-status">
            <span className={`connection ${connected ? 'online' : ''}`}><i />{connected ? 'Stream connected' : 'Reconnecting'}</span>
            <span className={`mode-pill ${liveMode === 'shadow' ? 'shadow' : ''}`}>{liveMode.toUpperCase()}</span>
            <span className="topbar-time">UTC</span>
          </div>
        </header>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<CommandCenter events={events} refreshKey={revision} />} />
            <Route path="/anomalies" element={<AnomaliesPage refreshKey={revision} />} />
            <Route path="/approvals" element={<ApprovalsPage refreshKey={approvalRevision} />} />
            <Route path="/trace" element={<TracePage refreshKey={revision} />} />
            <Route path="/assets" element={<AssetsPage refreshKey={revision} />} />
            <Route path="/audit" element={<AuditPage refreshKey={revision} />} />
            <Route path="/system" element={<SystemPage refreshKey={revision} />} />
            <Route path="/simulator" element={<SimulatorPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function ApprovalCount({ count }: { count: number }) {
  return <span className="nav-count" aria-label={`${count} pending approvals`}>{count.toString().padStart(2, '0')}</span>;
}
