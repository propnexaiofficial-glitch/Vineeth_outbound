import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from 'recharts';

interface FunnelData {
  stage: string;
  count: number;
}

interface FunnelChartProps {
  data: FunnelData[];
}

const STAGE_COLORS: Record<string, string> = {
  Total: '#6366f1',
  Completed: '#22c55e',
  Hot: '#ef4444',
  Warm: '#f97316',
  Cold: '#3b82f6',
  Pending: '#a855f7',
};

function getColor(stage: string): string {
  return STAGE_COLORS[stage] ?? '#94a3b8';
}

export function FunnelChart({ data }: FunnelChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-gray-400">
        No funnel data available.
      </div>
    );
  }

  const sorted = [...data].sort((a, b) => b.count - a.count);

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart
        data={sorted}
        layout="vertical"
        margin={{ top: 4, right: 24, bottom: 4, left: 16 }}
      >
        <XAxis type="number" tick={{ fontSize: 12 }} />
        <YAxis
          type="category"
          dataKey="stage"
          width={80}
          tick={{ fontSize: 12 }}
        />
        <Tooltip
          formatter={(value: number) => [value, 'Count']}
          contentStyle={{ fontSize: 12 }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {sorted.map((entry) => (
            <Cell key={entry.stage} fill={getColor(entry.stage)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
