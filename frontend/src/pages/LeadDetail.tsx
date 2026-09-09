import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { CallTimeline, LeadScoreBar, SentimentBadge } from '../components';
import { api } from '../api/client';

interface LeadData {
  lead_id: string;
  name: string;
  phone: string;
  score: number;
  category: string;
  sentiment?: string;
  campaign_id: string;
  score_breakdown?: Record<string, number>;
  follow_up_at?: string;
  notes?: string;
}

interface CallEvent {
  id: number;
  type: string;
  summary?: string;
  occurred_at: string;
  metadata?: Record<string, unknown>;
}

export default function LeadDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [followUpDate, setFollowUpDate] = useState('');
  const [followUpNote, setFollowUpNote] = useState('');
  const [saved, setSaved] = useState(false);

  const { data: leadData, isLoading } = useQuery<{ success: boolean; data: LeadData }>({
    queryKey: ['lead', id],
    queryFn: () => api.get(`/api/leads/${id}`),
    enabled: !!id,
  });

  const { data: eventsData } = useQuery<{ success: boolean; data: CallEvent[] }>({
    queryKey: ['lead-events', id],
    queryFn: () => api.get(`/api/leads/${id}/events`),
    enabled: !!id,
  });

  const followUpMutation = useMutation({
    mutationFn: () =>
      api.post(`/api/leads/${id}/follow-up`, {
        follow_up_at: followUpDate,
        notes: followUpNote,
      }),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    },
  });

  const lead = leadData?.data;
  const events = eventsData?.data ?? [];

  if (isLoading) return <p className="text-sm text-gray-400">Loading lead...</p>;
  if (!lead) return <p className="text-sm text-red-500">Lead not found.</p>;

  const breakdown = lead.score_breakdown ?? {};

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-sm text-gray-400 hover:text-gray-600">
          ← Back
        </button>
        <h1 className="text-2xl font-bold text-gray-900">{lead.name}</h1>
      </div>

      {/* Lead Info */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Phone</p>
          <p className="mt-1 text-sm font-medium text-gray-900">{lead.phone}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Category</p>
          <p className="mt-1 text-sm font-medium capitalize text-gray-900">{lead.category}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Score</p>
          <div className="mt-2">
            <LeadScoreBar score={lead.score} />
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Sentiment</p>
          <div className="mt-2">
            {lead.sentiment ? (
              <SentimentBadge sentiment={lead.sentiment} />
            ) : (
              <span className="text-xs text-gray-300">—</span>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Call Timeline */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500">Call History</h2>
          <CallTimeline events={events} leadId={id!} />
        </div>

        <div className="space-y-6">
          {/* Score Breakdown */}
          {Object.keys(breakdown).length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500">Score Breakdown</h2>
              <div className="space-y-3">
                {Object.entries(breakdown).map(([key, value]) => (
                  <div key={key}>
                    <div className="mb-1 flex justify-between text-xs text-gray-500">
                      <span className="capitalize">{key.replace(/_/g, ' ')}</span>
                      <span className="font-medium">{value}</span>
                    </div>
                    <LeadScoreBar score={value} showLabel={false} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Follow-up Scheduling */}
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500">Schedule Follow-up</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Follow-up Date & Time</label>
                <input
                  type="datetime-local"
                  value={followUpDate}
                  onChange={(e) => setFollowUpDate(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Notes</label>
                <textarea
                  value={followUpNote}
                  onChange={(e) => setFollowUpNote(e.target.value)}
                  rows={3}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Add follow-up notes..."
                />
              </div>
              <button
                onClick={() => followUpMutation.mutate()}
                disabled={!followUpDate || followUpMutation.isPending}
                className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {followUpMutation.isPending ? 'Saving...' : 'Save Follow-up'}
              </button>
              {saved && (
                <p className="text-center text-xs text-green-600">✓ Follow-up scheduled</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
