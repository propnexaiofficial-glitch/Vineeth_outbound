import React from 'react';

type Sentiment = 'positive' | 'neutral' | 'negative';

interface SentimentBadgeProps {
  sentiment: Sentiment | string;
}

const STYLES: Record<string, string> = {
  positive: 'bg-green-100 text-green-800',
  neutral: 'bg-gray-100 text-gray-700',
  negative: 'bg-red-100 text-red-800',
};

const ICONS: Record<string, string> = {
  positive: '😊',
  neutral: '😐',
  negative: '😞',
};

export function SentimentBadge({ sentiment }: SentimentBadgeProps) {
  const key = sentiment?.toLowerCase() ?? 'neutral';
  const style = STYLES[key] ?? STYLES.neutral;
  const icon = ICONS[key] ?? '';

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}
    >
      <span aria-hidden="true">{icon}</span>
      {key}
    </span>
  );
}
