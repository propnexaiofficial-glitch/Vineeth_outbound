import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { api } from '../api/client';
import { useCredits, usePurchaseCredits } from '../hooks/useCredits';

interface EstimateData {
  num_contacts: number;
  avg_duration_min: number;
  estimated_credits: number;
  price_per_credit: number;
  estimated_cost_inr: number;
}

// Group ledger entries by date for the usage chart (credits = minutes, decimal)
function buildDailyUsageChart(entries: Array<{ transaction_type: string; amount: number; created_at: string }>) {
  const map: Record<string, number> = {};
  for (const e of entries) {
    if (e.transaction_type !== 'deduction') continue;
    const date = e.created_at.slice(0, 10);
    map[date] = (map[date] ?? 0) + Math.abs(Number(e.amount));
  }
  return Object.entries(map)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => ({ label, value: Math.round(value * 100) / 100 }));
}

export default function Billing() {
  const [leadsSlider, setLeadsSlider] = useState(100);
  const [avgDuration, setAvgDuration] = useState(2); // minutes
  const [showMore, setShowMore] = useState(false);
  const [purchaseAmount, setPurchaseAmount] = useState('');
  const [purchaseSuccess, setPurchaseSuccess] = useState(false);
  const [purchaseError, setPurchaseError] = useState('');

  const { balance: creditsBalance, ledger: creditsLedger, pricing } = useCredits();
  const purchaseMutation = usePurchaseCredits();

  const { data: estimateData } = useQuery<{ success: boolean; data: EstimateData }>({
    queryKey: ['billing-estimate', leadsSlider, avgDuration],
    queryFn: () =>
      api.post('/api/billing/estimate', { num_contacts: leadsSlider, avg_duration_min: avgDuration }),
    enabled: leadsSlider > 0,
  });

  const creditBalance = creditsBalance.data?.balance ?? 0;
  const pricePerCredit = pricing.data?.price_per_credit ?? 10;
  const ledgerEntries = creditsLedger.data?.entries ?? [];
  const chartData = buildDailyUsageChart(ledgerEntries);

  const estimate = estimateData?.data;

  function handlePurchase(e: React.FormEvent) {
    e.preventDefault();
    const amount = parseInt(purchaseAmount, 10);
    if (!amount || amount <= 0) {
      setPurchaseError('Please enter a positive integer amount.');
      return;
    }
    setPurchaseError('');
    setPurchaseSuccess(false);
    purchaseMutation.mutate(
      { amount },
      {
        onSuccess: () => {
          setPurchaseSuccess(true);
          setPurchaseAmount('');
        },
        onError: (err) => {
          setPurchaseError(err.message || 'Purchase failed. Please try again.');
        },
      },
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Credits &amp; Usage</h1>
        <p className="mt-1 text-sm text-gray-500">
          1 credit = 1 minute of call time.
        </p>
      </div>

      {/* Balance warning banners */}
      {creditBalance === 0 && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 flex items-center gap-3">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#DC2626" strokeWidth="2" className="shrink-0">
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <p className="text-sm font-medium text-red-700">
            You have no credits remaining. Calls are blocked until you add credits.
          </p>
        </div>
      )}
      {creditBalance > 0 && creditBalance < 10 && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 flex items-center gap-3">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" className="shrink-0">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <p className="text-sm font-medium text-amber-700">
            Low balance: only {creditBalance.toFixed(4)} credit{creditBalance !== 1 ? 's' : ''} remaining (~{(creditBalance * 60).toFixed(0)} second{creditBalance !== 1 ? 's' : ''} of calls).
          </p>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl bg-white border border-gray-200 p-6 shadow-sm">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Credit Balance</p>
          <p className="mt-2 text-4xl font-bold text-gray-900">
            {creditsBalance.isLoading ? '…' : creditBalance.toLocaleString()}
          </p>
          <p className="mt-1 text-xs text-gray-400">credits available</p>
        </div>

        <div className="rounded-xl bg-white border border-gray-200 p-6 shadow-sm">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Price per Credit</p>
          <p className="mt-2 text-4xl font-bold text-[#C84B0C]">
            {pricing.isLoading ? '…' : `₹${pricePerCredit.toFixed(2)}`}
          </p>
          <p className="mt-1 text-xs text-gray-400">1 credit = 1 minute of call time</p>
        </div>

        <div className="rounded-xl bg-white border border-gray-200 p-6 shadow-sm">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Balance Value</p>
          <p className="mt-2 text-4xl font-bold text-gray-900">
            {pricing.isLoading || creditsBalance.isLoading
              ? '…'
              : `₹${(creditBalance * pricePerCredit).toFixed(2)}`}
          </p>
          <p className="mt-1 text-xs text-gray-400">at your current rate</p>
        </div>
      </div>

      {/* Daily usage chart + Purchase form */}
      <div className="grid grid-cols-5 gap-4">
        {/* Daily usage chart — 3 cols */}
        <div className="col-span-3 rounded-xl bg-white border border-gray-200 shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">Daily Credit Usage</h2>
          {creditsLedger.isLoading ? (
            <div className="h-40 flex items-center justify-center text-sm text-gray-400">Loading…</div>
          ) : chartData.length === 0 ? (
            <div className="h-40 flex items-center justify-center text-sm text-gray-400">No usage data yet.</div>
          ) : (
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -28 }} barSize={14}>
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 10, fill: '#9CA3AF' }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: 10, fill: '#9CA3AF' }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #E5E7EB' }}
                  cursor={{ fill: '#F9FAFB' }}
                  formatter={(v: number) => [`${v} credits`, 'Used']}
                />
                <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={i === chartData.length - 1 ? '#C84B0C' : '#FDDCCC'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Purchase form — 2 cols */}
        <div className="col-span-2 rounded-xl bg-white border border-gray-200 shadow-sm p-6 flex flex-col justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-800 mb-1">Add Credits</h2>
            <p className="text-xs text-gray-400 mb-5">
              Each credit = 1 minute of call time at ₹{pricePerCredit.toFixed(2)}/credit.
            </p>
            <form onSubmit={handlePurchase} className="space-y-3">
              <div>
                <label htmlFor="credit-amount" className="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
                  Credits to add
                </label>
                <input
                  id="credit-amount"
                  type="number"
                  min={1}
                  step={1}
                  value={purchaseAmount}
                  onChange={(e) => {
                    setPurchaseAmount(e.target.value);
                    setPurchaseSuccess(false);
                    setPurchaseError('');
                  }}
                  placeholder="e.g. 500"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#C84B0C]/30 focus:border-[#C84B0C]"
                />
              </div>
              {purchaseAmount && parseInt(purchaseAmount, 10) > 0 && (
                <p className="text-xs text-gray-500">
                  Cost: ₹{(parseInt(purchaseAmount, 10) * pricePerCredit).toFixed(2)}
                </p>
              )}
              <button
                type="submit"
                disabled={purchaseMutation.isPending}
                className="w-full rounded-lg bg-[#C84B0C] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#A83A08] transition-colors shadow-sm disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {purchaseMutation.isPending ? 'Adding…' : 'Add Credits'}
              </button>
            </form>
          </div>
          {purchaseSuccess && (
            <p className="mt-3 text-sm font-medium text-green-600">Credits added successfully.</p>
          )}
          {purchaseError && (
            <p className="mt-3 text-sm font-medium text-red-600">{purchaseError}</p>
          )}
        </div>
      </div>

      {/* Credit Estimator */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-800 mb-5">Credit Estimator</h2>
        <div className="grid grid-cols-2 gap-8">
          <div>
            <div className="mb-5">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Number of Contacts</p>
                <p className="text-sm font-bold text-[#C84B0C]">{leadsSlider.toLocaleString()}</p>
              </div>
              <input
                type="range"
                min={10}
                max={10000}
                step={10}
                value={leadsSlider}
                onChange={(e) => setLeadsSlider(Number(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                style={{
                  background: `linear-gradient(to right, #C84B0C ${(leadsSlider / 10000) * 100}%, #FDE8D8 ${(leadsSlider / 10000) * 100}%)`,
                }}
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Avg Call Duration (min)</p>
                <p className="text-sm font-bold text-[#C84B0C]">{avgDuration}</p>
              </div>
              <input
                type="range"
                min={0.5}
                max={15}
                step={0.5}
                value={avgDuration}
                onChange={(e) => setAvgDuration(Number(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                style={{
                  background: `linear-gradient(to right, #C84B0C ${(avgDuration / 15) * 100}%, #FDE8D8 ${(avgDuration / 15) * 100}%)`,
                }}
              />
            </div>
          </div>

          <div className="space-y-3">
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 flex items-center justify-between">
              <p className="text-sm text-gray-600">Credits needed</p>
              <p className="text-sm font-bold text-gray-800">
                {estimate ? estimate.estimated_credits.toLocaleString(undefined, { maximumFractionDigits: 1 }) : '—'}
              </p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 flex items-center justify-between">
              <p className="text-sm text-gray-600">Estimated cost</p>
              <p className="text-sm font-bold text-[#C84B0C]">
                {estimate ? `₹${estimate.estimated_cost_inr.toFixed(2)}` : '—'}
              </p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 flex items-center justify-between">
              <p className="text-sm text-gray-600">Your balance covers</p>
              <p className={`text-sm font-bold ${estimate && creditBalance >= estimate.estimated_credits ? 'text-green-600' : 'text-red-600'}`}>
                {estimate
                  ? creditBalance >= estimate.estimated_credits
                    ? '✓ Yes'
                    : `Need ${(estimate.estimated_credits - creditBalance).toLocaleString(undefined, { maximumFractionDigits: 1 })} more`
                  : '—'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Transaction History */}
      <div className="rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800">Transaction History</h2>
          <p className="mt-0.5 text-xs text-gray-400">Most recent 50 entries</p>
        </div>
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/50">
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Date</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Type</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Credits</th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {creditsLedger.isLoading ? (
              <tr><td colSpan={4} className="px-6 py-8 text-center text-sm text-gray-400">Loading…</td></tr>
            ) : ledgerEntries.length === 0 ? (
              <tr><td colSpan={4} className="px-6 py-8 text-center text-sm text-gray-400">No transactions yet.</td></tr>
            ) : (
              (showMore ? ledgerEntries : ledgerEntries.slice(0, 20)).map((entry) => (
                <tr key={entry.id} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-6 py-3 text-xs text-gray-500 whitespace-nowrap">
                    {new Date(entry.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      entry.transaction_type === 'purchase'    ? 'bg-green-50 text-green-700' :
                      entry.transaction_type === 'deduction'   ? 'bg-red-50 text-red-700' :
                      entry.transaction_type === 'reservation' ? 'bg-blue-50 text-blue-700' :
                      entry.transaction_type === 'release'     ? 'bg-gray-100 text-gray-600' :
                                                                  'bg-amber-50 text-amber-700'
                    }`}>
                      {entry.transaction_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-gray-800">
                    {entry.transaction_type === 'purchase' || entry.transaction_type === 'release'
                      ? `+${Number(entry.amount).toFixed(3)}`
                      : entry.transaction_type === 'deduction' || entry.transaction_type === 'reservation'
                      ? `-${Number(entry.amount).toFixed(3)}`
                      : Number(entry.amount) > 0 ? `+${Number(entry.amount).toFixed(3)}` : Number(entry.amount).toFixed(3)}
                  </td>
                  <td className="px-6 py-3 text-sm text-gray-500">
                    {entry.description ?? (entry.call_sid ? `Call ${entry.call_sid}` : '—')}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {ledgerEntries.length > 20 && (
          <div className="border-t border-gray-100 px-6 py-3 text-center">
            <button
              onClick={() => setShowMore((v) => !v)}
              className="flex items-center gap-1.5 mx-auto text-xs font-medium text-gray-500 hover:text-gray-700 transition-colors"
            >
              {showMore ? 'Show Less' : `Show All (${ledgerEntries.length - 20} more)`}
              <svg
                width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                className={`transition-transform ${showMore ? 'rotate-180' : ''}`}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
