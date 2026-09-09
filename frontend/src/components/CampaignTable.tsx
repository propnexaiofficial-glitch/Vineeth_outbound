import React, { useState, useMemo } from 'react';

interface Campaign {
  campaign_id: string;
  name: string;
  status: string;
  created_at: string;
  stats?: Record<string, number>;
}

interface CampaignTableProps {
  campaigns: Campaign[];
  onView?: (id: string) => void;
  onClone?: (id: string) => void;
}

type SortKey = 'name' | 'status' | 'created_at';
type SortDir = 'asc' | 'desc';

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  paused: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
  draft: 'bg-gray-100 text-gray-700',
  failed: 'bg-red-100 text-red-800',
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status.toLowerCase()] ?? 'bg-gray-100 text-gray-700';
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}>
      {status}
    </span>
  );
}

export function CampaignTable({ campaigns, onView, onClone }: CampaignTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const statuses = useMemo(() => {
    const unique = Array.from(new Set(campaigns.map((c) => c.status)));
    return ['all', ...unique];
  }, [campaigns]);

  const sorted = useMemo(() => {
    const filtered =
      statusFilter === 'all' ? campaigns : campaigns.filter((c) => c.status === statusFilter);

    return [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [campaigns, sortKey, sortDir, statusFilter]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span className="ml-1 text-gray-300">↕</span>;
    return <span className="ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-3">
        <label className="text-sm text-gray-600">Status:</label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-200 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s === 'all' ? 'All' : s}
            </option>
          ))}
        </select>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-100">
          <thead className="bg-gray-50">
            <tr>
              <th
                className="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700"
                onClick={() => toggleSort('name')}
              >
                Name <SortIcon col="name" />
              </th>
              <th
                className="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700"
                onClick={() => toggleSort('status')}
              >
                Status <SortIcon col="status" />
              </th>
              <th
                className="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700"
                onClick={() => toggleSort('created_at')}
              >
                Created <SortIcon col="created_at" />
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">
                  No campaigns found.
                </td>
              </tr>
            ) : (
              sorted.map((c) => (
                <tr key={c.campaign_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{c.name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(c.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      {onView && (
                        <button
                          onClick={() => onView(c.campaign_id)}
                          className="rounded-md bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          View
                        </button>
                      )}
                      {onClone && (
                        <button
                          onClick={() => onClone(c.campaign_id)}
                          className="rounded-md bg-gray-50 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100 transition-colors"
                        >
                          Clone
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
