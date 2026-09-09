import React, { useRef, useState, DragEvent, ChangeEvent } from 'react';

interface FileUploadZoneProps {
  onUpload: (file: File) => Promise<void>;
  accept?: string;
  maxSizeMB?: number;
}

type OcrMethod = 'native' | 'ocr' | null;

function getOcrMethod(file: File): OcrMethod {
  if (file.type === 'text/csv' || file.name.endsWith('.csv')) return 'native';
  if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) return 'ocr';
  if (file.type.startsWith('image/')) return 'ocr';
  return null;
}

export function FileUploadZone({
  onUpload,
  accept = '.csv,.pdf,.jpg,.jpeg,.png',
  maxSizeMB = 10,
}: FileUploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocrMethod, setOcrMethod] = useState<OcrMethod>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  function validateFile(file: File): string | null {
    const maxBytes = maxSizeMB * 1024 * 1024;
    if (file.size > maxBytes) {
      return `File exceeds ${maxSizeMB} MB limit (${(file.size / 1024 / 1024).toFixed(1)} MB).`;
    }
    return null;
  }

  async function handleFile(file: File) {
    setError(null);
    setOcrMethod(null);
    setProgress(null);

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setFileName(file.name);
    setProgress(0);

    // Simulate progress ticks while upload runs
    const interval = setInterval(() => {
      setProgress((p) => (p !== null && p < 90 ? p + 10 : p));
    }, 150);

    try {
      await onUpload(file);
      clearInterval(interval);
      setProgress(100);
      setOcrMethod(getOcrMethod(file));
    } catch (err) {
      clearInterval(interval);
      setProgress(null);
      setError(err instanceof Error ? err.message : 'Upload failed.');
    }
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(true);
  }

  function onDragLeave() {
    setDragging(false);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function onInputChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = '';
  }

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        aria-label="File upload zone"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors
          ${dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-gray-50 hover:border-blue-300 hover:bg-blue-50/40'}`}
      >
        <svg className="mb-3 h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
        </svg>
        <p className="text-sm font-medium text-gray-700">
          Drag &amp; drop a file here, or <span className="text-blue-600 underline">browse</span>
        </p>
        <p className="mt-1 text-xs text-gray-400">
          Accepted: {accept} &mdash; Max {maxSizeMB} MB
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={onInputChange}
          aria-hidden="true"
        />
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 border border-red-200">
          {error}
        </p>
      )}

      {progress !== null && (
        <div className="space-y-1">
          {fileName && (
            <p className="text-xs text-gray-500 truncate">{fileName}</p>
          )}
          <div className="overflow-hidden rounded-full bg-gray-100 h-2">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-300"
              style={{ width: `${progress}%` }}
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
          <p className="text-right text-xs text-gray-400">{progress}%</p>
        </div>
      )}

      {ocrMethod && (
        <div className="flex items-center gap-2 rounded-md bg-indigo-50 px-3 py-2 text-xs text-indigo-700 border border-indigo-100">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {ocrMethod === 'ocr'
            ? 'OCR extraction will be used for this file.'
            : 'Native CSV parsing will be used for this file.'}
        </div>
      )}
    </div>
  );
}
