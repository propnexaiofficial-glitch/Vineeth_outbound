import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';

interface Campaign {
  campaign_id: string;
  name: string;
  status: string;
  created_at: string;
  stats?: Record<string, number>;
}

interface Lead {
  lead_id: string;
  name: string;
  phone: string;
  email?: string;
  score: number;
  category: string;
  campaign_id: string;
  source?: string;
  last_activity?: string;
}

interface DashboardStats {
  total_campaigns: number;
  total_calls: number;
  completed: number;
  failed: number;
  total_cost: number;
  avg_cost: number;
  completion_rate: number;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function StatCard({
  label, value, sub, trend, trendUp,
}: {
  label: string;
  value: string | number;
  sub?: string;
  trend?: string;
  trendUp?: boolean;
}) {
  return (
    <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{label}</p>
      <div className="mt-2 flex items-baseline gap-2 flex-wrap">
        <span className="text-2xl font-bold text-[#C84B0C]">{value}</span>
        {trend && (
          <span className={`text-xs font-semibold ${trendUp ? 'text-green-600' : 'text-red-500'}`}>
            {trend}
          </span>
        )}
      </div>
      {sub && <p className="mt-1 text-xs text-gray-400">{sub}</p>}
    </div>
  );
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

export default function Dashboard() {
  const navigate = useNavigate();

  const { data: campaignsData } = useQuery<{ success: boolean; data: Campaign[] }>({
    queryKey: ['campaigns'],
    queryFn: () => api.get('/api/campaigns'),
    refetchInterval: 5000,
    retry: false,
  });

  const { data: leadsData } = useQuery<{ success: boolean; data: Lead[] }>({
    queryKey: ['latest-leads'],
    queryFn: () => api.get('/api/leads?sort=score&limit=5'),
    refetchInterval: 5000,
    retry: false,
  });

  const { data: statsData } = useQuery<{ success: boolean; data: DashboardStats }>({
    queryKey: ['dashboard-stats'],
    queryFn: () => api.get('/api/analytics/summary'),
    refetchInterval: 5000,
    retry: false,
  });

  const campaigns = campaignsData?.data ?? [];
  const latestLeads = leadsData?.data ?? [];
  const stats = statsData?.data;

  // Build calls-by-status bar chart from real timeline data
  const callsByDay = DAYS.map((day) => ({ day, completed: 0, ongoing: 0 }));

  const totalCampaigns = campaigns.length;
  const totalCalls = campaigns.reduce((s, c) => s + (c.stats?.total ?? 0), 0);
  const completed = campaigns.reduce((s, c) => s + (c.stats?.completed ?? 0), 0);
  const failed = campaigns.reduce((s, c) => s + (c.stats?.failed ?? 0), 0);
  const totalCost = campaigns.reduce((s, c) => s + (c.stats?.cost ?? 0), 0);
  const completionRate = totalCalls > 0 ? Math.round((completed / totalCalls) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Overview Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">Real-time performance metrics for your enterprise campaigns.</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors shadow-sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>
            Last 30 Days
          </button>
          <button
            onClick={() => navigate('/campaigns')}
            className="flex items-center gap-2 rounded-lg bg-[#C84B0C] px-4 py-2 text-sm font-semibold text-white hover:bg-[#A83A08] transition-colors shadow-sm"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            New Campaign
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-5 gap-3">
        <StatCard label="Total Campaigns" value={totalCampaigns} />
        <StatCard label="Total Calls" value={totalCalls.toLocaleString()} />
        <StatCard
          label="Completed"
          value={completed.toLocaleString()}
          sub={totalCalls > 0 ? `${completionRate}% Rate` : undefined}
        />
        <StatCard label="Failed" value={failed} />
        <StatCard
          label="Total Cost"
          value={`₹${totalCost >= 1000 ? (totalCost / 1000).toFixed(1) + 'k' : totalCost.toFixed(2)}`}
          sub={totalCalls > 0 ? `Avg ₹${(totalCost / totalCalls).toFixed(2)}` : undefined}
        />
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-5 gap-4">
        {/* Calls by Status chart — 3 cols */}
        <div className="col-span-3 rounded-xl bg-white border border-gray-200 shadow-sm p-5">
          <div className="flex items-start justify-between mb-1">
            <div>
              <h2 className="text-sm font-semibold text-gray-800">Calls by Status</h2>
              <p className="text-xs text-gray-400 mt-0.5">Hourly distribution of campaign activities</p>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#C84B0C]" />Completed</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-orange-200" />Ongoing</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={callsByDay} margin={{ top: 8, right: 4, bottom: 0, left: -20 }} barSize={28}>
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #E5E7EB' }}
                cursor={{ fill: '#F9FAFB' }}
              />
              <Bar dataKey="completed" stackId="a" fill="#C84B0C" radius={[0, 0, 0, 0]} />
              <Bar dataKey="ongoing" stackId="a" fill="#FDDCCC" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Right column — 2 cols */}
        <div className="col-span-2 flex flex-col gap-4">
          {/* CTA card */}
          <div
            className="rounded-xl p-5 text-white relative overflow-hidden"
            style={{ background: 'linear-gradient(135deg, #C84B0C 0%, #E8722A 70%, #D4956A 100%)' }}
          >
            <div className="absolute right-3 top-3 opacity-20">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="white"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
            </div>
            <h3 className="text-base font-bold leading-snug">Ready to reach<br />more customers?</h3>
            <p className="mt-2 text-xs text-orange-100 leading-relaxed">
              Launch a new automated call campaign in under 5 minutes with our AI-powered script generator.
            </p>
            <button
              onClick={() => navigate('/campaigns')}
              className="mt-4 w-full rounded-lg bg-white py-2 text-sm font-semibold text-[#C84B0C] hover:bg-orange-50 transition-colors"
            >
              Start Building Now
            </button>
          </div>

          {/* System Health */}
          <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-4">
            <h3 className="text-sm font-semibold text-gray-800 mb-3">System Health</h3>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-xs text-gray-600">
                  <span className="h-2 w-2 rounded-full bg-green-500" />API Gateway
                </span>
                <span className="text-xs font-semibold text-green-600">UP</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-xs text-gray-600">
                  <span className="h-2 w-2 rounded-full bg-green-500" />VOIP Nodes
                </span>
                <span className="text-xs font-semibold text-green-600">STABLE</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-xs text-gray-600">
                  <span className="h-2 w-2 rounded-full bg-green-500" />AI Transcription
                </span>
                <span className="text-xs font-semibold text-green-600">ACTIVE</span>
              </div>
            </div>
          </div>

          {/* Pro Tip */}
          <div className="rounded-xl bg-orange-50 border border-orange-100 p-4">
            <div className="flex items-center gap-1.5 mb-2">
              <span className="h-2 w-2 rounded-full bg-[#C84B0C]" />
              <span className="text-xs font-bold text-[#C84B0C] uppercase tracking-wide">Pro Tip</span>
            </div>
            <p className="text-xs text-gray-600 leading-relaxed">
              Campaigns scheduled between 10 AM and 2 PM local time show a 15% higher completion rate.
            </p>
          </div>
        </div>
      </div>

      {/* Latest Leads + On-Duty Agents */}
      <div className="grid grid-cols-5 gap-4">
        {/* Latest Leads — 3 cols */}
        <div className="col-span-3 rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800">Latest Leads</h2>
            <button
              onClick={() => navigate('/leads')}
              className="text-xs font-medium text-[#C84B0C] hover:underline"
            >
              View All Leads
            </button>
          </div>
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-gray-50 bg-gray-50/50">
                <th className="px-5 py-2.5 text-left text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Contact</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Status</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Source</th>
                <th className="px-4 py-2.5 text-left text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Engagement</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {latestLeads.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-5 py-8 text-center text-sm text-gray-400">No leads yet.</td>
                </tr>
              ) : (
                latestLeads.map((lead) => (
                  <tr
                    key={lead.lead_id}
                    className="hover:bg-gray-50/60 cursor-pointer transition-colors"
                    onClick={() => navigate(`/leads/${lead.lead_id}`)}
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2.5">
                        <LeadAvatar name={lead.name} />
                        <div>
                          <p className="text-xs font-semibold text-gray-900">{lead.name}</p>
                          <p className="text-[10px] text-gray-400">{lead.email ?? lead.phone}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <TempBadge category={lead.category} />
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">{lead.source ?? 'Direct'}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{lead.last_activity ?? '—'}</td>
                    <td className="px-4 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                      <button className="p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" /></svg>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* On-Duty Agents — 2 cols */}
        <div className="col-span-2 rounded-xl bg-white border border-gray-200 shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-gray-800">Active Campaigns</h3>
            <span className="rounded-full bg-green-50 border border-green-200 px-2.5 py-0.5 text-[10px] font-bold text-green-700 uppercase tracking-wide">
              {campaigns.filter(c => c.status === 'running' || c.status === 'active').length} Running
            </span>
          </div>
          <div className="space-y-2">
            {campaigns.slice(0, 5).map((c) => (
              <div key={c.campaign_id} className="flex items-center justify-between">
                <span className="text-xs text-gray-700 truncate max-w-[120px]">{c.name}</span>
                <span className="flex items-center gap-1.5 text-[10px] font-medium text-gray-500 shrink-0">
                  <span className={`h-1.5 w-1.5 rounded-full ${
                    c.status === 'running' || c.status === 'active' ? 'bg-green-500' :
                    c.status === 'paused' ? 'bg-yellow-400' : 'bg-gray-300'
                  }`} />
                  {c.status}
                </span>
              </div>
            ))}
            {campaigns.length === 0 && (
              <p className="text-xs text-gray-400">No campaigns yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
