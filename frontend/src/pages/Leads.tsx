import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';

interface Lead {
  lead_id: string;
  name: string;
  phone: string;
  email?: string;
  score: number;
  category: string;
  sentiment?: string;
  campaign_id: string;
  company?: string;
  industry?: string;
  value?: number;
  last_activity?: string;
}

type Tab = 'hot' | 'warm' | 'cold' | 'all';

const PAGE_SIZE = 10;

function LeadAvatar({ name, src }: { name: string; src?: string }) {
  const colors = [
    'bg-orange-100 text-orange-700',
    'bg-blue-100 text-blue-700',
    'bg-purple-100 text-purple-700',
    'bg-green-100 text-green-700',
    'bg-pink-100 text-pink-700',
    'bg-teal-100 text-teal-700',
  ];
  const idx = name.charCodeAt(0) % colors.length;
  const initials = name.split(' ').map((n) => n[0]).slice(0, 2).join('').toUpperCase();
  if (src) {
    return <img src={src} alt={name} className="w-9 h-9 rounded-full object-cover shrink-0" />;
  }
  return (
    <div className={`w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${colors[idx]}`}>
      {initials}
    </div>
  );
}

function TempBadge({ category }: { category: string }) {
  const cat = category.toLowerCase();
  if (cat === 'hot') {
    return (
      <span className="inline-flex items-center rounded-full border border-red-200 bg-red-50 px-2.5 py-0.5 text-xs font-bold text-red-600 uppercase tracking-wide">
        HOT
      </span>
    );
  }
  if (cat === 'warm') {
    return (
      <span className="inline-flex items-center rounded-full border border-yellow-200 bg-yellow-50 px-2.5 py-0.5 text-xs font-bold text-yellow-600 uppercase tracking-wide">
        WARM
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-bold text-blue-600 uppercase tracking-wide">
      COLD
    </span>
  );
}



export default function Leads() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('hot');
  const [page, setPage] = useState(1);

  const { data: leadsData, isLoading } = useQuery<{ success: boolean; data: Lead[] }>({
    queryKey: ['leads-all'],
    queryFn: () => api.get('/api/leads?limit=500'),
    refetchInterval: 5000,
  });

  const { data: timelineData } = useQuery<{ success: boolean; data: { date: string; calls: number; cost: number }[] }>({
    queryKey: ['leads-timeline'],
    queryFn: () => api.get('/api/analytics/timeline'),
    refetchInterval: 10000,
  });

  const allLeads = leadsData?.data ?? [];
  const timeline = timelineData?.data ?? [];

  const hot = allLeads.filter((l) => l.category?.toLowerCase() === 'hot');
  const warm = allLeads.filter((l) => l.category?.toLowerCase() === 'warm');
  const cold = allLeads.filter((l) => l.category?.toLowerCase() === 'cold');

  const tabLeads: Record<Tab, Lead[]> = { hot, warm, cold, all: allLeads };
  const filtered = tabLeads[activeTab];
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Stats — all from real data only
  const activePipelineValue = allLeads.reduce((s, l) => s + (l.value ?? 0), 0);
  const completed = allLeads.filter((l) => l.category?.toLowerCase() === 'hot' || l.category?.toLowerCase() === 'warm').length;
  const conversionRate = allLeads.length > 0 ? ((completed / allLeads.length) * 100).toFixed(1) : '0.0';

  // Momentum chart from real timeline
  const momentumData = timeline.map((d) => ({ day: d.date, qualified: d.calls }));

  const tabs: { key: Tab; label: string }[] = [
    { key: 'hot', label: 'Hot Leads' },
    { key: 'warm', label: 'Warm Leads' },
    { key: 'cold', label: 'Cold Leads' },
    { key: 'all', label: 'All Leads' },
  ];

  function handleTabChange(tab: Tab) {
    setActiveTab(tab);
    setPage(1);
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Leads Pipeline</h1>
          <p className="mt-1 text-sm text-gray-500">Manage your prospects and track conversion performance across stages.</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors shadow-sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
            Export
          </button>
          <button className="flex items-center gap-2 rounded-lg bg-[#C84B0C] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#A83A08] transition-colors shadow-sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            New Lead
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Active Pipeline */}
        <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
          <div className="flex items-start justify-between">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Active Pipeline</p>
            <div className="rounded-lg bg-orange-50 p-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C84B0C" strokeWidth="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18" /><polyline points="17 6 23 6 23 12" /></svg>
            </div>
          </div>
          <p className="mt-3 text-2xl font-bold text-gray-900">
            {activePipelineValue > 0 ? `₹${activePipelineValue.toLocaleString()}` : '—'}
          </p>
          <p className="mt-0.5 text-xs text-gray-400">Total projected value from {allLeads.length} active leads</p>
        </div>

        {/* Conversion Rate */}
        <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
          <div className="flex items-start justify-between">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Conversion Rate</p>
            <div className="rounded-lg bg-blue-50 p-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" strokeWidth="2"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="3" /></svg>
            </div>
          </div>
          <p className="mt-3 text-2xl font-bold text-blue-600">{conversionRate}%</p>
          <p className="mt-0.5 text-xs text-gray-400">Hot + Warm leads out of total</p>
        </div>

        {/* Lead Temperature */}
        <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">Lead Temperature</p>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-10 rounded-lg bg-gradient-to-r from-red-500 to-red-400 flex items-center justify-center">
              <span className="text-xs font-bold text-white">HOT ({hot.length})</span>
            </div>
            <div className="flex-1 h-10 rounded-lg bg-gradient-to-r from-yellow-400 to-yellow-300 flex items-center justify-center">
              <span className="text-xs font-bold text-white">WARM ({warm.length})</span>
            </div>
            <div className="flex-1 h-10 rounded-lg bg-gradient-to-r from-blue-400 to-blue-300 flex items-center justify-center">
              <span className="text-xs font-bold text-white">COLD ({cold.length})</span>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs + Table */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
        {/* Tab bar */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5">
          <div className="flex">
            {tabs.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => handleTabChange(key)}
                className={`relative px-4 py-3.5 text-sm font-medium transition-colors ${
                  activeTab === key
                    ? 'text-[#C84B0C]'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {label}
                {activeTab === key && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#C84B0C] rounded-t" />
                )}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 py-2">
            <button className="p-1.5 rounded text-gray-400 hover:bg-gray-100 transition-colors">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></svg>
            </button>
            <button className="p-1.5 rounded text-gray-400 hover:bg-gray-100 transition-colors">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></svg>
            </button>
          </div>
        </div>

        {isLoading ? (
          <div className="px-5 py-12 text-center text-sm text-gray-400">Loading leads...</div>
        ) : (
          <>
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Lead Name</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Company</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Value</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Contact Info</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-12 text-center text-sm text-gray-400">
                      No {activeTab === 'all' ? '' : activeTab} leads found.
                    </td>
                  </tr>
                ) : (
                  paginated.map((lead) => (
                    <tr
                      key={lead.lead_id}
                      className="hover:bg-gray-50/60 transition-colors cursor-pointer"
                      onClick={() => navigate(`/leads/${lead.lead_id}`)}
                    >
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <LeadAvatar name={lead.name} />
                          <div>
                            <p className="text-sm font-semibold text-gray-900">{lead.name}</p>
                            <p className="text-xs text-gray-400">
                              Last activity: {lead.last_activity ?? '—'}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        <p className="text-sm font-medium text-gray-800">{lead.company ?? '—'}</p>
                        <p className="text-xs text-gray-400">{lead.industry ?? ''}</p>
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <span className="text-sm font-semibold text-gray-900">
                          {lead.value ? `₹${lead.value.toLocaleString()}` : '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3.5">
                        <p className="text-xs text-gray-700">{lead.email ?? '—'}</p>
                        <p className="text-xs text-gray-400">{lead.phone}</p>
                      </td>
                      <td className="px-4 py-3.5 text-center">
                        <TempBadge category={lead.category} />
                      </td>
                      <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                        <button className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" /></svg>
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>

            {/* Pagination */}
            <div className="flex items-center justify-between px-5 py-3.5 border-t border-gray-100">
              <p className="text-xs text-gray-500">
                Showing {filtered.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length} {activeTab} leads
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6" /></svg>
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Conversion Momentum chart */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-800">Conversion Momentum</h2>
          <span className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="h-2 w-2 rounded-full bg-orange-500" />
            Leads Qualified
          </span>
        </div>
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart data={momentumData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id="momentumGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#C84B0C" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#C84B0C" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #E5E7EB' }}
              formatter={(v: number) => [v, 'Qualified']}
            />
            <Area
              type="monotone"
              dataKey="qualified"
              stroke="#C84B0C"
              strokeWidth={2}
              fill="url(#momentumGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
