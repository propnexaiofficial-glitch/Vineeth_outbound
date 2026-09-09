import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

const GEMINI_VOICES: { name: string; tone: string }[] = [
  { name: 'Puck',          tone: 'Upbeat' },
  { name: 'Aoede',         tone: 'Breezy' },
  { name: 'Kore',          tone: 'Firm' },
  { name: 'Charon',        tone: 'Informative' },
  { name: 'Fenrir',        tone: 'Excitable' },
  { name: 'Zephyr',        tone: 'Bright' },
  { name: 'Orus',          tone: 'Firm' },
  { name: 'Autonoe',       tone: 'Bright' },
  { name: 'Umbriel',       tone: 'Easy-going' },
  { name: 'Erinome',       tone: 'Clear' },
  { name: 'Laomedeia',     tone: 'Upbeat' },
  { name: 'Schedar',       tone: 'Even' },
  { name: 'Achird',        tone: 'Friendly' },
  { name: 'Sadachbia',     tone: 'Lively' },
  { name: 'Enceladus',     tone: 'Breathy' },
  { name: 'Algieba',       tone: 'Smooth' },
  { name: 'Algenib',       tone: 'Gravelly' },
  { name: 'Achernar',      tone: 'Soft' },
  { name: 'Gacrux',        tone: 'Mature' },
  { name: 'Zubenelgenubi', tone: 'Casual' },
  { name: 'Sadaltager',    tone: 'Knowledgeable' },
  { name: 'Leda',          tone: 'Youthful' },
  { name: 'Callirrhoe',    tone: 'Easy-going' },
  { name: 'Iapetus',       tone: 'Clear' },
  { name: 'Despina',       tone: 'Smooth' },
  { name: 'Rasalgethi',    tone: 'Informative' },
  { name: 'Alnilam',       tone: 'Firm' },
  { name: 'Pulcherrima',   tone: 'Forward' },
  { name: 'Vindemiatrix',  tone: 'Gentle' },
  { name: 'Sulafat',       tone: 'Warm' },
];

const LANGUAGES: { code: string; label: string }[] = [
  { code: 'en-IN', label: 'English (India)' },
  { code: 'hi-IN', label: 'Hindi (India)' },
  { code: 'en-US', label: 'English (US)' },
  { code: 'mr-IN', label: 'Marathi' },
  { code: 'ta-IN', label: 'Tamil' },
  { code: 'te-IN', label: 'Telugu' },
  { code: 'bn-BD', label: 'Bengali' },
  { code: 'ar-EG', label: 'Arabic (Egyptian)' },
  { code: 'de-DE', label: 'German' },
  { code: 'es-US', label: 'Spanish (US)' },
  { code: 'fr-FR', label: 'French' },
  { code: 'id-ID', label: 'Indonesian' },
  { code: 'it-IT', label: 'Italian' },
  { code: 'ja-JP', label: 'Japanese' },
  { code: 'ko-KR', label: 'Korean' },
  { code: 'pt-BR', label: 'Portuguese (Brazil)' },
  { code: 'ru-RU', label: 'Russian' },
  { code: 'nl-NL', label: 'Dutch' },
  { code: 'pl-PL', label: 'Polish' },
  { code: 'th-TH', label: 'Thai' },
  { code: 'tr-TR', label: 'Turkish' },
  { code: 'vi-VN', label: 'Vietnamese' },
];

interface SettingsData {
  agent_name: string;
  company_name: string;
  product_name: string;
  agent_language: string;
  gemini_voice: string;
  gemini_speaking_rate: number;
  affective_dialog: boolean;
}

const INPUT = 'w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-[#C84B0C]/30 focus:border-[#C84B0C] focus:bg-white transition-colors';
const SELECT = INPUT;

function Card({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-white border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-gray-400">{description}</p>}
      </div>
      <div className="px-6 py-5 space-y-5">{children}</div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">{label}</label>
      {children}
      {hint && <p className="mt-1.5 text-xs text-gray-400">{hint}</p>}
    </div>
  );
}

export default function Settings() {
  const queryClient = useQueryClient();

  const [agentName,       setAgentName]       = useState('');
  const [companyName,     setCompanyName]     = useState('');
  const [productName,     setProductName]     = useState('');
  const [agentLanguage,   setAgentLanguage]   = useState('en-IN');
  const [geminiVoice,     setGeminiVoice]     = useState('Aoede');
  const [speakingRate,    setSpeakingRate]    = useState(1.0);
  const [affectiveDialog, setAffectiveDialog] = useState(true);
  const [saved,           setSaved]           = useState(false);

  const { data, isLoading } = useQuery<{ success: boolean; data: SettingsData }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/settings'),
  });

  useEffect(() => {
    if (data?.data) {
      const d = data.data;
      setAgentName(d.agent_name ?? '');
      setCompanyName(d.company_name ?? '');
      setProductName(d.product_name ?? '');
      setAgentLanguage(d.agent_language ?? 'en-IN');
      setGeminiVoice(d.gemini_voice ?? 'Aoede');
      setSpeakingRate(d.gemini_speaking_rate ?? 1.0);
      setAffectiveDialog(d.affective_dialog ?? true);
    }
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put('/api/settings', {
        agent_name:           agentName,
        company_name:         companyName,
        product_name:         productName,
        agent_language:       agentLanguage,
        gemini_voice:         geminiVoice,
        gemini_speaking_rate: speakingRate,
        affective_dialog:     affectiveDialog,
      }),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
  });

  const selectedVoice = GEMINI_VOICES.find((v) => v.name === geminiVoice);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-sm text-gray-400">Loading settings...</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
          <p className="mt-1 text-sm text-gray-500">Configure your AI voice agent persona and behaviour.</p>
        </div>
        <div className="flex items-center gap-3">
          {saved && (
            <span className="flex items-center gap-1.5 text-sm text-green-600 font-medium">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
              Saved
            </span>
          )}
          {saveMutation.isError && (
            <span className="text-sm text-red-500">Failed to save.</span>
          )}
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="flex items-center gap-2 rounded-lg bg-[#C84B0C] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#A83A08] disabled:opacity-50 transition-colors shadow-sm"
          >
            {saveMutation.isPending ? (
              <>
                <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                Saving…
              </>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" /></svg>
                Save Settings
              </>
            )}
          </button>
        </div>
      </div>

      {/* Agent Persona */}
      <Card title="Agent Persona" description="How your AI agent identifies itself to callers.">
        <div className="grid grid-cols-2 gap-5">
          <Field label="Agent Name" hint="The name the agent uses when introducing itself.">
            <input
              type="text"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              className={INPUT}
              placeholder="e.g. Riya"
            />
          </Field>
          <Field label="Company Name" hint="Shown in the topbar and used in call scripts.">
            <input
              type="text"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              className={INPUT}
              placeholder="e.g. GrabYourCar"
            />
          </Field>
        </div>
        <Field label="Product / Service Name" hint="What the agent is selling or promoting.">
          <input
            type="text"
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            className={INPUT}
            placeholder="e.g. GrabYourCar Premium"
          />
        </Field>
      </Card>

      {/* Voice & Language */}
      <Card title="Voice & Language" description="Controls how the agent sounds and what language it speaks.">
        <div className="grid grid-cols-2 gap-5">
          <Field label="Gemini Voice">
            <select
              value={geminiVoice}
              onChange={(e) => setGeminiVoice(e.target.value)}
              className={SELECT}
            >
              {GEMINI_VOICES.map((v) => (
                <option key={v.name} value={v.name}>{v.name} — {v.tone}</option>
              ))}
            </select>
            {selectedVoice && (
              <p className="mt-1.5 text-xs text-gray-400">
                Tone: <span className="font-medium text-gray-600">{selectedVoice.tone}</span>
                {' · '}
                <a
                  href="https://cloud.google.com/text-to-speech/docs/chirp3-hd"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#C84B0C] hover:underline"
                >
                  Preview voices ↗
                </a>
              </p>
            )}
          </Field>
          <Field label="Response Language">
            <select
              value={agentLanguage}
              onChange={(e) => setAgentLanguage(e.target.value)}
              className={SELECT}
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </Field>
        </div>

        {/* Speaking Rate slider */}
        <Field label={`Speaking Rate — ${speakingRate.toFixed(2)}×`} hint="Lower values sound softer and more measured. Higher values are faster.">
          <div className="mt-1">
            <input
              type="range"
              min={0.5}
              max={1.5}
              step={0.05}
              value={speakingRate}
              onChange={(e) => setSpeakingRate(parseFloat(e.target.value))}
              className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
              style={{
                background: `linear-gradient(to right, #C84B0C ${((speakingRate - 0.5) / 1) * 100}%, #FDE8D8 ${((speakingRate - 0.5) / 1) * 100}%)`,
              }}
            />
            <div className="flex justify-between text-[10px] text-gray-400 mt-1.5">
              <span>0.5× Slower</span>
              <span>1.0× Normal</span>
              <span>1.5× Faster</span>
            </div>
          </div>
        </Field>
      </Card>

      {/* Advanced */}
      <Card title="Advanced" description="Experimental features — may require specific model versions.">
        <div className="flex items-start justify-between gap-6 rounded-lg bg-orange-50 border border-orange-100 px-4 py-4">
          <div className="flex-1">
            <p className="text-sm font-semibold text-gray-800">Affective Dialog</p>
            <p className="mt-1 text-xs text-gray-500 leading-relaxed">
              Agent reads the caller's emotional tone and adjusts its delivery — warmer when they're warm, gentler when they're upset.
            </p>
            <p className="mt-1.5 text-xs text-amber-600 font-medium">
              ⚠ Requires gemini-live-2.5-flash-native-audio model
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={affectiveDialog}
            disabled
            title="Not supported on current model"
            className="relative mt-0.5 inline-flex h-6 w-11 shrink-0 cursor-not-allowed rounded-full border-2 border-transparent bg-gray-200 opacity-40 transition-colors"
          >
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${affectiveDialog ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
        </div>
      </Card>

      {/* Danger zone */}
      <Card title="Danger Zone" description="Irreversible actions — proceed with caution.">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-800">Reset All Settings</p>
            <p className="text-xs text-gray-400 mt-0.5">Restore all settings to their default values from the .env file.</p>
          </div>
          <button
            onClick={() => {
              if (data?.data) {
                const d = data.data;
                setAgentName(d.agent_name);
                setCompanyName(d.company_name);
                setProductName(d.product_name);
                setAgentLanguage(d.agent_language);
                setGeminiVoice(d.gemini_voice);
                setSpeakingRate(d.gemini_speaking_rate);
                setAffectiveDialog(d.affective_dialog);
              }
            }}
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-xs font-semibold text-red-600 hover:bg-red-100 transition-colors"
          >
            Reset to Defaults
          </button>
        </div>
      </Card>
    </div>
  );
}
