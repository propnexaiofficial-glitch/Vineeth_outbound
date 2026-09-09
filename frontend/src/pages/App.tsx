import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import Dashboard from './Dashboard';
import Campaigns from './Campaigns';
import CampaignDetail from './CampaignDetail';
import Analytics from './Analytics';
import Leads from './Leads';
import LeadDetail from './LeadDetail';
import Billing from './Billing';
import Settings from './Settings';
import { useCredits } from '../hooks/useCredits';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2000 } },
});

// SVG icons matching the design
function IconDashboard({ active }: { active: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? '#C84B0C' : '#6B7280'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
    </svg>
  );
}
function IconCampaigns({ active }: { active: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? '#C84B0C' : '#6B7280'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}
function IconAnalytics({ active }: { active: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? '#C84B0C' : '#6B7280'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  );
}
function IconBilling({ active }: { active: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? '#C84B0C' : '#6B7280'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="5" width="20" height="14" rx="2" /><line x1="2" y1="10" x2="22" y2="10" />
    </svg>
  );
}
function IconLeads({ active }: { active: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? '#C84B0C' : '#6B7280'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}
function IconLogout() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}
function IconBell() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}
function IconHelp() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}function IconSettings({ active }: { active?: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={active ? '#C84B0C' : '#6B7280'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', Icon: IconDashboard },
  { to: '/campaigns', label: 'Campaigns', Icon: IconCampaigns },
  { to: '/analytics', label: 'Analytics', Icon: IconAnalytics },
  { to: '/billing', label: 'Billing', Icon: IconBilling },
  { to: '/leads', label: 'Leads', Icon: IconLeads },
  { to: '/settings', label: 'Settings', Icon: IconSettings },
];

function Sidebar() {
  return (
    <aside className="flex flex-col w-44 shrink-0 bg-white border-r border-gray-200 h-screen">
      {/* Brand */}
      <div className="px-5 pt-6 pb-4">
        <p className="text-xs font-bold text-[#C84B0C] uppercase tracking-widest">Enterprise</p>
        <p className="text-[11px] text-gray-400 mt-0.5">Management Console</p>
      </div>

      {/* Main nav */}
      <nav className="flex-1 px-3 space-y-0.5" aria-label="Main navigation">
        {NAV_ITEMS.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-[#F5E6DC] text-[#C84B0C] border-l-2 border-[#C84B0C]'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <Icon active={isActive} />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Bottom nav */}
      <div className="px-3 pb-6 space-y-0.5 border-t border-gray-100 pt-3">
        <button className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors">
          <IconHelp />
          <span>Support</span>
        </button>
        <button className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors">
          <IconLogout />
          <span>Logout</span>
        </button>
      </div>
    </aside>
  );
}

function Topbar() {
  const { data: settingsData } = useQuery<{ success: boolean; data: { company_name: string; agent_name: string } }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/settings'),
    staleTime: 60000,
  });

  const companyName = settingsData?.data?.company_name ?? '';
  const { balance } = useCredits();
  const creditBalance = balance.data?.balance ?? null;
  const isLow = creditBalance !== null && creditBalance < 10;
  const isEmpty = creditBalance !== null && creditBalance === 0;

  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center px-6 gap-4 shrink-0">
      {/* Search */}
      <div className="flex-1 max-w-sm">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            placeholder="Search campaigns..."
            className="w-full rounded-lg border border-gray-200 bg-gray-50 pl-9 pr-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[#C84B0C]/30 focus:border-[#C84B0C]"
          />
        </div>
      </div>

      <div className="flex items-center gap-3 ml-auto">
        {/* Credit balance + Bell */}
        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-semibold px-2.5 py-1 rounded-lg border ${
              isEmpty
                ? 'bg-red-50 text-red-600 border-red-200'
                : isLow
                ? 'bg-amber-50 text-amber-600 border-amber-200'
                : 'bg-gray-100 text-gray-600 border-gray-200'
            }`}
            title="Credits remaining"
          >
            Credits : {balance.isLoading
              ? '…'
              : creditBalance === null
              ? '00'
              : creditBalance % 1 === 0
              ? creditBalance.toLocaleString()
              : creditBalance.toFixed(4)}
          </span>
          <button className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors" aria-label="Notifications">
            <IconBell />
          </button>
        </div>
        <button className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors" aria-label="Help">
          <IconHelp />
        </button>
        <button className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors" aria-label="Settings">
          <IconSettings />
        </button>
        {companyName && (
          <div className="flex items-center gap-2 pl-2 border-l border-gray-200">
            <div className="text-right">
              <p className="text-xs font-semibold text-gray-800 leading-tight">{companyName}</p>
              <p className="text-[10px] text-gray-400 uppercase tracking-wide">Account</p>
            </div>
            <div className="w-8 h-8 rounded-full bg-[#C84B0C] flex items-center justify-center text-white text-xs font-bold">
              {companyName.charAt(0).toUpperCase()}
            </div>
          </div>
        )}
      </div>
    </header>
  );
}

function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-[#FAF8F6]">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/campaigns/:id" element={<CampaignDetail />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/leads" element={<Leads />} />
            <Route path="/leads/:id" element={<LeadDetail />} />
            <Route path="/billing" element={<Billing />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
