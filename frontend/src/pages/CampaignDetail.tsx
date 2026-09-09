import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { LeadScoreBar, SentimentBadge, StatsGrid } from '../components';
import { useCampaign } from '../hooks/useCampaign';
import { api } from '../api/client';

interface Lead {
  lead_id: string;
  name: string;
  phone: string;
  score: number;
  category: string;
  sentiment?: string;
  campaign_id: string;
}

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: campaignData, isLoading: campaignLoading } = useCampaign(id!);
  const { data: leadsData, isLoading: leadsLoading } = useQuery<{ success: boolean; data: Lead[] }>({
    queryKey: ['campaign-leads', id],
    queryFn: () => api.get(`/api/leads?campaign_id=${id}`),
    refetchInterval: 3000,
    enabled: !!id,
  });

  const campaign = campaignData?.data;
  const leads = leadsData?.data ?? [];

  if (campaignLoading) {
    return <p className="text-sm text-gray-400">Loading campaign...</p>;
  }

  if (!campaign) {
    return <p className="text-sm text-red-500">Campaign not found.</p>;
  }

  const stats = campaign.stats ?? {};

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/campaigns')}
          className="text-sm text-gray-400 hover:text-gray-600"
        >
          ← Campaigns
        </button>
        <h1 className="text-2xl font-bold text-gray-900">{campaign.name}</h1>
        <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium capitalize text-gray-600">
          {campaign.status}
        </span>
      </div>

      <StatsGrid stats={stats} />

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">Leads</h2>
        {leadsLoading ? (
          <p className="text-sm text-gray-400">Loading leads...</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Phone</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Score</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Category</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Sentiment</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {leads.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">No leads found.</td>
                    </tr>
                  ) : (
                    leads.map((lead) => (
                      <tr
                        key={lead.lead_id}
                        onClick={() => navigate(`/leads/${lead.lead_id}`)}
                        className="cursor-pointer hover:bg-gray-50 transition-colors"
                      >
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">{lead.name}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{lead.phone}</td>
                        <td className="px-4 py-3 w-32">
                          <LeadScoreBar score={lead.score} />
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 capitalize">{lead.category}</td>
                        <td className="px-4 py-3">
                          {lead.sentiment ? (
                            <SentimentBadge sentiment={lead.sentiment} />
                          ) : (
                            <span className="text-xs text-gray-300">—</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
