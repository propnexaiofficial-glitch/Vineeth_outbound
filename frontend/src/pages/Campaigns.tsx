import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FileUploadZone } from '../components';
import { useCampaigns } from '../hooks/useCampaign';
import { api } from '../api/client';

interface CreateCampaignPayload {
  name: string;
  description?: string;
}

const PAGE_SIZE = 5;

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === 'running' || s === 'active') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700">
        <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
        Running
      </span>
    );
  }
  if (s === 'paused') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-yellow-50 px-2.5 py-1 text-xs font-medium text-yellow-700">
        <span className="h-1.5 w-1.5 rounded-full bg-yellow-400" />
        Paused
      </span>
    );
  }
  if (s === 'completed') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
        <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
        Completed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
      <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
      {status}
    </span>
  );
}

function CampaignAvatar({ name }: { name: string }) {
  const colors = [
    'bg-orange-100 text-orange-700',
    'bg-blue-100 text-blue-700',
    'bg-purple-100 text-purple-700',
    'bg-green-100 text-green-700',
    'bg-pink-100 text-pink-700',
  ];
  const idx = name.charCodeAt(0) % colors.length;
  return (
    <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold shrink-0 ${colors[idx]}`}>
      {name.charAt(0).toUpperCase()}
    </div>
  );
}

export default function Campaigns() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading } = useCampaigns();
  const campaigns = data?.data ?? [];

  const [page, setPage] = useState(1);
  const [showModal, setShowModal] = useState(false);
  const [campaignName, setCampaignName] = useState('');
  const [description, setDescription] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(campaigns.length / PAGE_SIZE));
  const paginated = campaigns.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Derived stats
  const activeCampaigns = campaigns.filter(
    (c) => c.status === 'running' || c.status === 'active'
  ).length;
  const totalContacts = campaigns.reduce((s, c) => s + (c.stats?.total ?? 0), 0);
  const totalSpend = campaigns.reduce((s, c) => s + (c.stats?.cost ?? 0), 0);

  const createMutation = useMutation({
    mutationFn: async (payload: CreateCampaignPayload) => {
      const campaign = await api.post<{ success: boolean; data: { campaign_id: string } }>(
        '/api/campaigns',
        payload
      );
      if (uploadedFile) {
        const formData = new FormData();
        formData.append('file', uploadedFile);
        await fetch('/campaign/upload', {
          method: 'POST',
          body: formData,
          headers: { 'X-API-Key': localStorage.getItem('voice_agent_api_key') || '' },
        });
      }
      return campaign;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      setShowModal(false);
      setCampaignName('');
      setDescription('');
      setUploadedFile(null);
      setCreateError(null);
    },
    onError: (err: Error) => setCreateError(err.message),
  });

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!campaignName.trim()) return;
    createMutation.mutate({ name: campaignName.trim(), description: description.trim() || undefined });
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
          <p className="mt-1 text-sm text-gray-500">Oversee and optimize your marketing performance across all channels.</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 rounded-lg bg-[#C84B0C] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#A83A08] transition-colors shadow-sm"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          New Campaign
        </button>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-3 gap-4">
        {/* Active Campaigns */}
        <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Active Campaigns</p>
              <p className="mt-2 text-3xl font-bold text-gray-900">{activeCampaigns}</p>
              <p className="mt-1 text-xs text-gray-400">{campaigns.length} total campaigns</p>
            </div>
            <span className="rounded-full bg-[#F5E6DC] px-2.5 py-1 text-[10px] font-bold text-[#C84B0C] uppercase tracking-wide">Active</span>
          </div>
        </div>

        {/* Total Contacts */}
        <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Total Contacts</p>
              <p className="mt-2 text-3xl font-bold text-[#C84B0C]">{totalContacts.toLocaleString()}</p>
              <p className="mt-1 text-xs text-gray-400">Across all campaigns</p>
            </div>
            <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[10px] font-bold text-gray-500 uppercase tracking-wide">Reach</span>
          </div>
        </div>

        {/* Total Spend */}
        <div className="rounded-xl bg-white border border-gray-200 p-5 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Total Spend</p>
              <p className="mt-2 text-3xl font-bold text-[#C84B0C]">₹{totalSpend.toFixed(2)}</p>
              <p className="mt-1 text-xs text-gray-400">All time</p>
            </div>
            <span className="rounded-full bg-red-50 px-2.5 py-1 text-[10px] font-bold text-red-500 uppercase tracking-wide">Budget</span>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800">Active Promotions</h2>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" /></svg>
              Filter
            </button>
            <button className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
              Export
            </button>
          </div>
        </div>

        {isLoading ? (
          <div className="px-5 py-12 text-center text-sm text-gray-400">Loading campaigns...</div>
        ) : (
          <>
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Campaign Name</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Contacts</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Completed</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Spend</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Created</th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-5 py-12 text-center text-sm text-gray-400">
                      No campaigns yet. Create your first one.
                    </td>
                  </tr>
                ) : (
                  paginated.map((campaign) => {
                    const stats = campaign.stats ?? {};
                    const cost = stats.cost ?? 0;
                    const total = stats.total ?? 0;
                    const completed = stats.completed ?? 0;
                    const createdDate = new Date(campaign.created_at).toLocaleDateString('en-US', {
                      month: 'numeric', day: 'numeric', year: 'numeric',
                    });
                    return (
                      <tr
                        key={campaign.campaign_id}
                        className="hover:bg-gray-50/60 transition-colors cursor-pointer"
                        onClick={() => navigate(`/campaigns/${campaign.campaign_id}`)}
                      >
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-3">
                            <CampaignAvatar name={campaign.name} />
                            <div>
                              <p className="text-sm font-semibold text-gray-900">{campaign.name}</p>
                              <p className="text-xs text-gray-400">Voice Campaign</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3.5">
                          <StatusBadge status={campaign.status} />
                        </td>
                        <td className="px-4 py-3.5 text-right text-sm text-gray-700">{total.toLocaleString()}</td>
                        <td className="px-4 py-3.5 text-right text-sm text-gray-700">{completed.toLocaleString()}</td>
                        <td className="px-4 py-3.5 text-right text-sm font-semibold text-[#C84B0C]">₹{cost.toFixed(2)}</td>
                        <td className="px-4 py-3.5 text-right text-sm text-gray-500">{createdDate}</td>
                        <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                          <button className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" /></svg>
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>

            {/* Pagination */}
            <div className="flex items-center justify-between px-5 py-3.5 border-t border-gray-100">
              <p className="text-xs text-gray-500">
                Showing {campaigns.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, campaigns.length)} of {campaigns.length} campaigns
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  aria-label="Previous page"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  aria-label="Next page"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6" /></svg>
                </button>
              </div>
            </div>
          </>
        )}
      </div>



      {/* Create Campaign Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">New Campaign</h2>
              <button
                onClick={() => setShowModal(false)}
                className="text-gray-400 hover:text-gray-600 p-1"
                aria-label="Close"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Campaign Name *</label>
                <input
                  type="text"
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  required
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#C84B0C]/30 focus:border-[#C84B0C]"
                  placeholder="e.g. Q1 Outreach"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Description</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#C84B0C]/30 focus:border-[#C84B0C]"
                  placeholder="Optional description"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Upload Leads (optional)</label>
                <FileUploadZone onUpload={(file) => setUploadedFile(file)} />
                {uploadedFile && (
                  <p className="mt-1 text-xs text-green-600">✓ {uploadedFile.name} ready to upload</p>
                )}
              </div>

              {createError && (
                <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{createError}</p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="rounded-lg bg-[#C84B0C] px-4 py-2 text-sm font-medium text-white hover:bg-[#A83A08] disabled:opacity-50 transition-colors"
                >
                  {createMutation.isPending ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
