import React from 'react';

interface LeadScoreBarProps {
  score: number;
  showLabel?: boolean;
}

function getColorClass(score: number): string {
  if (score >= 80) return 'bg-green-500';
  if (score >= 60) return 'bg-yellow-400';
  if (score >= 30) return 'bg-orange-400';
  return 'bg-red-500';
}

function getTextColorClass(score: number): string {
  if (score >= 80) return 'text-green-700';
  if (score >= 60) return 'text-yellow-700';
  if (score >= 30) return 'text-orange-700';
  return 'text-red-700';
}

export function LeadScoreBar({ score, showLabel = true }: LeadScoreBarProps) {
  const clamped = Math.min(100, Math.max(0, score));
  const barColor = getColorClass(clamped);
  const textColor = getTextColorClass(clamped);

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 overflow-hidden rounded-full bg-gray-100 h-2">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${clamped}%` }}
          role="progressbar"
          aria-valuenow={clamped}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {showLabel && (
        <span className={`w-8 text-right text-xs font-semibold tabular-nums ${textColor}`}>
          {clamped}
        </span>
      )}
    </div>
  );
}
