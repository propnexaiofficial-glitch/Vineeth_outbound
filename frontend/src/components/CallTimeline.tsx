import React, { useState } from 'react';

interface CallEvent {
  id: number;
  type: string;
  summary?: string;
  occurred_at: string;
  metadata?: Record<string, unknown>;
}

interface CallTimelineProps {
  events: CallEvent[];
  leadId: string;
}

function TypeIcon({ type }: { type: string }) {
  switch (type.toLowerCase()) {
    case 'call':
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
        </svg>
      );
    case 'note':
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
        </svg>
      );
    case 'email':
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      );
    default:
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
  }
}

function EventItem({ event }: { event: CallEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasTranscript = !!event.summary;

  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-50 text-blue-600 ring-2 ring-white">
          <TypeIcon type={event.type} />
        </div>
        <div className="mt-1 flex-1 w-px bg-gray-200" />
      </div>

      <div className="pb-4 flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium capitalize text-gray-800">{event.type}</span>
          <time className="text-xs text-gray-400 whitespace-nowrap">
            {new Date(event.occurred_at).toLocaleString()}
          </time>
        </div>

        {hasTranscript && (
          <>
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-xs text-blue-600 hover:underline focus:outline-none"
            >
              {expanded ? 'Hide transcript' : 'Show transcript'}
            </button>
            {expanded && (
              <p className="mt-1 rounded-md bg-gray-50 p-2 text-xs text-gray-600 leading-relaxed border border-gray-100">
                {event.summary}
              </p>
            )}
          </>
        )}
      </div>
    </li>
  );
}

export function CallTimeline({ events, leadId }: CallTimelineProps) {
  if (!events || events.length === 0) {
    return (
      <p className="text-sm text-gray-400 py-4">No call history for lead {leadId}.</p>
    );
  }

  const sorted = [...events].sort(
    (a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime()
  );

  return (
    <ul className="space-y-0" aria-label={`Call timeline for lead ${leadId}`}>
      {sorted.map((event) => (
        <EventItem key={event.id} event={event} />
      ))}
    </ul>
  );
}
