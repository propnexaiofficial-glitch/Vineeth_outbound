import React from 'react';

interface StatsGridProps {
  stats: {
    total?: number;
    hot?: number;
    warm?: number;
    cold?: number;
    in_progress?: number;
    completed?: number;
    pending?: number;
    failed?: number;
    not_picked?: number;
  };
}

interface MetricCardProps {
  label: string;
  value: number;
  colorClass: string;
  bgClass: string;
}

function MetricCard({ label, value, colorClass, bgClass }: MetricCardProps) {
  return (
    <div
      className={`rounded-xl p-4 shadow-sm border transition-all duration-300 hover:shadow-md hover:-translate-y-0.5 ${bgClass}`}
    >
      <p className={`text-xs font-semibold uppercase tracking-wide ${colorClass}`}>{label}</p>
      <p className={`mt-1 text-3xl font-bold ${colorClass}`}>{value}</p>
    </div>
  );
}

export function StatsGrid({ stats }: StatsGridProps) {
  const cards: MetricCardProps[] = [
    {
      label: 'Total',
      value: stats.total ?? 0,
      colorClass: 'text-gray-700',
      bgClass: 'bg-gray-50 border-gray-200',
    },
    {
      label: 'Hot',
      value: stats.hot ?? 0,
      colorClass: 'text-red-700',
      bgClass: 'bg-red-50 border-red-200',
    },
    {
      label: 'Warm',
      value: stats.warm ?? 0,
      colorClass: 'text-orange-700',
      bgClass: 'bg-orange-50 border-orange-200',
    },
    {
      label: 'Cold',
      value: stats.cold ?? 0,
      colorClass: 'text-blue-700',
      bgClass: 'bg-blue-50 border-blue-200',
    },
    {
      label: 'In Progress',
      value: stats.in_progress ?? 0,
      colorClass: 'text-purple-700',
      bgClass: 'bg-purple-50 border-purple-200',
    },
    {
      label: 'Completed',
      value: stats.completed ?? 0,
      colorClass: 'text-green-700',
      bgClass: 'bg-green-50 border-green-200',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {cards.map((card) => (
        <MetricCard key={card.label} {...card} />
      ))}
    </div>
  );
}
