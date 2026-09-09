import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  PieChart, Pie,
} from 'recharts';
import { api } from '../api/client';

interface AnalyticsData {
  funnel: { stage: string; count: number }[];
  sentiment_distribution: { sentiment: string; count: number }[];
  intent_breakdown: { intent: string; count: number }[];
  top_topics: { topic: string; count: number }[];
  total_calls?: number;
  answer_rate?: number;
  avg_duration?: number;
  completed?: number;
  hot?: number;
  warm?: number;
  cold?: number;
  total_leads?: number;
}

interface Lead {
  lead_id: string;
  name: string;
  phone: string;
  email?: string;
  category: string;
  company?: string;
  industry?: string;
  last_activity?: string;
}

function LeadAvatar({ name }: { name: string }) {
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
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${colors[idx]}`}>
      {initials}
    </div>
  );
}

function TempBadge({ category }: { category: string }) {
  const cat = category?.toLowerCase();
  if (cat === 'hot') return (
    <span className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-bold text-red-600 uppercase">HOT</span>
  );
  if (cat === 'warm') return (
    <span className="rounded-full border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-[10px] font-bold text-yellow-600 uppercase">WARM</span>
  );
  return (
    <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[10px] font-bold text-blue-600 uppercase">COLD</span>
  );
}

function InteractionIcon({ type }: { type: string }) {
  if (type === 'call') return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.61 3.4 2 2 0 0 1 3.6 1.22h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.82a16 16 0 0 0 6.29 6.29l.95-.95a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" /></svg>
  );
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
  );
}

export default function Analytics() {
  const navigate = useNavigate();

  const { data: analyticsData, isLoading } = useQuery<{ success: boolean; data: AnalyticsData }>({
    queryKey: ['analytics'],
    queryFn: () => api.get('/api/analytics'),
    refetchInterval: 5000,
  });

  const { data: leadsData } = useQuery<{ success: boolean; data: Lead[] }>({
    queryKey: ['recent-interactions'],
    queryFn: () => api.get('/api/leads?limit=5'),
    refetchInterval: 5000,
  });

  const { data: timelineData } = useQuery<{ success: boolean; data: { date: string; calls: number; cost: number }[] }>({
    queryKey: ['analytics-timeline'],
    queryFn: () => api.get('/api/analytics/timeline'),
    refetchInterval: 10000,
  });

  const analytics = analyticsData?.data;
  const recentLeads = leadsData?.data ?? [];
  const timeline = timelineData?.data ?? [];

  // All values from real API — no hardcoded fallbacks
  const totalCalls = analytics?.total_calls ?? 0;
  const answerRate = analytics?.answer_rate ?? 0;
  const avgDuration = analytics?.avg_duration ?? 0;

  const formatDuration = (secs: number) => {
    if (!secs) return '0m 0s';
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s}s`;
  };

  // Donut from real funnel data
  const hot = analytics?.hot ?? analytics?.funnel?.find((f) => f.stage.toLowerCase() === 'hot')?.count ?? 0;
  const warm = analytics?.warm ?? analytics?.funnel?.find((f) => f.stage.toLowerCase() === 'warm')?.count ?? 0;
  const cold = analytics?.cold ?? analytics?.funnel?.find((f) => f.stage.toLowerCase() === 'cold')?.count ?? 0;
  const totalLeads = analytics?.total_leads ?? (hot + warm + cold);
  const donutData = [
    { name: 'Hot Leads', value: hot, color: '#C84B0C' },
    { name: 'Warm Prospects', value: warm, color: '#93C5FD' },
    { name: 'Cold Outreach', value: cold, color: '#E5E7EB' },
  ];
  const hotPct = totalLeads > 0 ? Math.round((hot / totalLeads) * 100) : 0;
  const warmPct = totalLeads > 0 ? Math.round((warm / totalLeads) * 100) : 0;
  const coldPct = totalLeads > 0 ? Math.round((cold / totalLeads) * 100) : 0;

  // Build chart from real timeline data
  const trendData = timeline.map((d) => ({
    label: d.date,
    calls: d.calls,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Analytics Performance</h1>
          <p className="mt-1 text-sm text-gray-500">Real-time engagement and operational health monitoring.</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors shadow-sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>
            Last 30 Days
          </button>
          <button className="flex items-center gap-2 rounded-lg bg-[#C84B0C] px-4 py-2 text-sm font-semibold text-white hover:bg-[#A83A08] transition-colors shadow-sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
            Export Report
          </button>
        </div>
      </div>

      {/* Top row: 3 stat cards + Status Breakdown donut */}
      <div className="grid grid-cols-5 gap-4">
        {/* Stat cards — 3 cols */}
        <div className="col-span-3 grid grid-cols-3 gap-3">
          {/* Answer Rate */}
          <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="rounded-lg bg-orange-50 p-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C84B0C" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg>
              </div>
            </div>
            <p className="text-xs text-gray-400 font-medium">Answer Rate</p>
            <p className="mt-1 text-2xl font-bold text-[#C84B0C]">
              {answerRate > 0 ? `${answerRate}%` : '—'}
            </p>
            <div className="mt-2 h-1 rounded-full bg-gray-100 overflow-hidden">
              <div className="h-full rounded-full bg-[#C84B0C]" style={{ width: `${Math.min(answerRate, 100)}%` }} />
            </div>
          </div>

          {/* Avg Duration */}
          <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="rounded-lg bg-blue-50 p-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3B82F6" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
              </div>
            </div>
            <p className="text-xs text-gray-400 font-medium">Avg. Duration</p>
            <p className="mt-1 text-2xl font-bold text-gray-800">
              {avgDuration > 0 ? formatDuration(avgDuration) : '—'}
            </p>
          </div>

          {/* Total Calls */}
          <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="rounded-lg bg-purple-50 p-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8B5CF6" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12 19.79 19.79 0 0 1 1.61 3.4 2 2 0 0 1 3.6 1.22h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.82a16 16 0 0 0 6.29 6.29l.95-.95a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" /></svg>
              </div>
            </div>
            <p className="text-xs text-gray-400 font-medium">Total Calls</p>
            <p className="mt-1 text-2xl font-bold text-gray-800">{totalCalls.toLocaleString()}</p>
          </div>
        </div>

        {/* Status Breakdown donut — 2 cols */}
        <div className="col-span-2 rounded-xl bg-white border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">Status Breakdown</h2>
          {totalLeads === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">No lead data yet.</p>
          ) : (
            <div className="flex items-center gap-4">
              <div className="relative shrink-0">
                <PieChart width={120} height={120}>
                  <Pie
                    data={donutData}
                    cx={55}
                    cy={55}
                    innerRadius={38}
                    outerRadius={55}
                    dataKey="value"
                    startAngle={90}
                    endAngle={-270}
                    strokeWidth={0}
                  >
                    {donutData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span className="text-lg font-bold text-gray-900">
                    {totalLeads >= 1000 ? `${Math.round(totalLeads / 1000)}k` : totalLeads}
                  </span>
                  <span className="text-[9px] text-gray-400 uppercase tracking-widest">Leads</span>
                </div>
              </div>
              <div className="flex-1 space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs text-gray-600">
                    <span className="h-2 w-2 rounded-full bg-[#C84B0C]" />Hot Leads
                  </span>
                  <span className="text-xs font-bold text-gray-800">{hotPct}%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs text-gray-600">
                    <span className="h-2 w-2 rounded-full bg-blue-300" />Warm Prospects
                  </span>
                  <span className="text-xs font-bold text-gray-800">{warmPct}%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs text-gray-600">
                    <span className="h-2 w-2 rounded-full bg-gray-200" />Cold Outreach
                  </span>
                  <span className="text-xs font-bold text-gray-800">{coldPct}%</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Call Activity Trends chart */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-800">Call Activity Trends</h2>
          <span className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="h-2 w-2 rounded-full bg-[#C84B0C]" />Calls
          </span>
        </div>
        {trendData.length === 0 ? (
          <div className="h-40 flex items-center justify-center text-sm text-gray-400">
            No activity data yet.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={trendData} margin={{ top: 4, right: 4, bottom: 0, left: -24 }} barSize={20}>
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: '#9CA3AF' }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #E5E7EB' }}
                cursor={{ fill: '#F9FAFB' }}
              />
              <Bar dataKey="calls" radius={[3, 3, 0, 0]}>
                {trendData.map((_, i) => (
                  <Cell key={i} fill={i === trendData.length - 1 ? '#8B2500' : '#C84B0C'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Recent Interactions table */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800">Recent Interactions</h2>
          <button
            onClick={() => navigate('/leads')}
            className="text-xs font-medium text-[#C84B0C] hover:underline"
          >
            View All Leads
          </button>
        </div>

        {isLoading ? (
          <div className="px-5 py-10 text-center text-sm text-gray-400">Loading...</div>
        ) : recentLeads.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-gray-400">No interactions yet.</div>
        ) : (
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-gray-50 bg-gray-50/50">
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Lead Name</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Interaction Type</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Last Activity</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Status</th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-gray-400 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {recentLeads.map((lead) => (
                <tr
                  key={lead.lead_id}
                  className="hover:bg-gray-50/60 cursor-pointer transition-colors"
                  onClick={() => navigate(`/leads/${lead.lead_id}`)}
                >
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2.5">
                      <LeadAvatar name={lead.name} />
                      <div>
                        <p className="text-sm font-semibold text-gray-900">{lead.name}</p>
                        <p className="text-xs text-gray-400">{lead.company ?? lead.industry ?? '—'}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3.5">
                    <span className="flex items-center gap-2 text-sm text-gray-600">
                      <InteractionIcon type="call" />
                      Inbound Call
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-sm text-gray-600">
                    {lead.last_activity ?? '—'}
                  </td>
                  <td className="px-4 py-3.5">
                    <TempBadge category={lead.category} />
                  </td>
                  <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                    <button className="p-1.5 rounded-lg text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" /></svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* FAB */}
      <button
        onClick={() => navigate('/campaigns')}
        className="fixed bottom-8 right-8 w-12 h-12 rounded-full bg-[#C84B0C] shadow-lg flex items-center justify-center text-white hover:bg-[#A83A08] transition-colors z-40"
        aria-label="New campaign"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
      </button>
    </div>
  );
}
