# Sales Voice Agent

An AI-powered outbound calling platform that uses Google Gemini Live for real-time voice conversations, Exotel for telephony, and a React dashboard for campaign management.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     React Frontend                       │
│  Dashboard · Campaigns · Analytics · Leads · Credits    │
└────────────────────────┬────────────────────────────────┘
                         │ REST + SSE
┌────────────────────────▼────────────────────────────────┐
│                  FastAPI Backend (main.py)               │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │  Exotel WS   │  │  Campaign    │  │  Credits API  │ │
│  │  Handler     │  │  Orchestrator│  │  (prepaid)    │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘ │
│         │                 │                             │
│  ┌──────▼─────────────────▼──────────────────────────┐  │
│  │              Gemini Live Bridge                    │  │
│  │   Real-time audio ↔ transcript ↔ lead extraction  │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │                          │
┌────────▼────────┐      ┌──────────▼──────────┐
│   PostgreSQL    │      │      MongoDB         │
│  (Neon/Supabase)│      │  (Atlas)             │
│  campaigns      │      │  call_insights       │
│  contacts       │      │  lead_info           │
│  credit_ledger  │      └─────────────────────┘
│  api_keys       │
└─────────────────┘
```

---

## Features

- **Outbound calling** via Exotel with real-time Gemini Live voice AI
- **Campaign management** — upload CSV/PDF/image of leads, set concurrency, run bulk campaigns
- **Live transcription** — full call transcript captured in real time
- **AI insights** — post-call Gemini analysis: sentiment, buying intent, lead scoring, objections
- **Prepaid credits** — 1 credit = 1 minute; decimal usage (65s = 1.0833 credits)
- **Multi-tenant** — API key auth, per-tenant credit balances and rate limits
- **SSE streaming** — real-time campaign events pushed to the frontend
- **OCR support** — extract contacts from scanned PDFs and images via Tesseract

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (Neon recommended)
- MongoDB (Atlas recommended)
- Exotel account with a voicebot app configured
- Google Gemini API key (or Vertex AI project)

### 1. Clone and configure

```bash
git clone <repo>
cd voice_agent
cp .env.example .env   # fill in your keys
```

### 2. Backend

```bash
pip install -r requirements.txt
python main.py
# Server starts at http://localhost:8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
# UI starts at http://localhost:5173
```

---

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `GEMINI_MODEL` | Model name (default: `models/gemini-3.1-flash-live-preview`) | No |
| `USE_VERTEX_AI` | Use Vertex AI instead of API key (`true`/`false`) | No |
| `VERTEX_PROJECT_ID` | GCP project ID (if Vertex AI) | Vertex only |
| `VERTEX_LOCATION` | GCP region (default: `us-central1`) | No |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON | Vertex only |
| `EXOTEL_API_KEY` | Exotel API key | Yes |
| `EXOTEL_API_TOKEN` | Exotel API token | Yes |
| `EXOTEL_SID` | Exotel account SID | Yes |
| `EXOTEL_CALLER_ID` | Virtual number for outbound calls | Yes |
| `EXOTEL_SUBDOMAIN` | Exotel API subdomain (default: `api.in.exotel.com`) | No |
| `EXOTEL_APP_ID` | Exotel voicebot app ID | Yes |
| `MONGODB_URI` | MongoDB connection string | Yes |
| `DATABASE_URL` | PostgreSQL connection string (Neon) | Yes |
| `CLIENT_ID` | Tenant identifier for this deployment | Yes |
| `PUBLIC_URL` | Publicly accessible URL of this server | Yes |
| `AGENT_NAME` | AI agent's name (default: `Riya`) | No |
| `COMPANY_NAME` | Company name shown in UI | No |
| `PRODUCT_NAME` | Product name used in prompts | No |
| `AGENT_LANGUAGE` | BCP-47 language tag (default: `hi-IN`) | No |
| `GEMINI_VOICE` | Gemini voice name (default: `Sadachbia`) | No |
| `GEMINI_SPEAKING_RATE` | Speaking rate 0.25–2.0 (default: `1.0`) | No |
| `ALLOWED_ORIGINS` | CORS origins, comma-separated or `*` | No |
| `SERVER_PORT` | HTTP port (default: `8000`) | No |
| `MIN_CONNECTION_RATE` | Auto-pause threshold (default: `0.3`) | No |
| `CALLING_WINDOW_START` | Calling window start time (default: `09:00`) | No |
| `CALLING_WINDOW_END` | Calling window end time (default: `18:00`) | No |
| `CALLING_WINDOW_TZ` | Calling window timezone (default: `Asia/Kolkata`) | No |
| `USE_LIVEKIT` | Enable LiveKit mode (default: `false`) | No |
| `LIVEKIT_URL` | LiveKit server URL | LiveKit only |
| `LIVEKIT_API_KEY` | LiveKit API key | LiveKit only |
| `LIVEKIT_API_SECRET` | LiveKit API secret | LiveKit only |

---

## API Reference

### Health
```
GET /health
```

### Campaigns
```
POST /campaign/upload          Upload CSV/PDF/image of leads
POST /campaign/start           Start a campaign
POST /campaign/pause           Pause active campaign
POST /campaign/resume          Resume paused campaign
POST /campaign/stop            Stop and cancel remaining leads
GET  /campaign/status          Campaign status + per-lead data
GET  /campaign/results         Download results as CSV
```

### Credits
```
GET  /api/credits/balance      Current credit balance
GET  /api/credits/pricing      Price per credit for this tenant
GET  /api/credits/ledger       Paginated transaction history
POST /api/credits/purchase     Add credits
POST /api/billing/estimate     Estimate credits for a batch of calls
```

### Insights & Analytics
```
GET  /api/insights/dashboard          Aggregate dashboard summary
GET  /api/insights/campaign/{id}      Insights for a campaign
GET  /api/insights/lead/{id}          Insight detail for a lead
GET  /api/insights/leads/{category}   Leads by category (hot/warm/cold)
GET  /api/analytics                   Campaign analytics summary
GET  /api/analytics/timeline          Daily call counts
```

### Outbound
```
POST /outbound                 Trigger a single outbound call
```

### Settings & Auth
```
GET  /api/settings             Get agent/company settings
PUT  /api/settings             Update settings
POST /api/auth/login           Validate API key, get tenant info
GET  /api/events/stream        SSE real-time event stream
```

---

## Credit System

Credits are prepaid and consumed per call:

- **1 credit = 1 minute** of call time
- Usage is **decimal** — a 65-second call costs `65/60 ≈ 1.0833` credits
- **1 credit is reserved** when a call starts; the remainder is deducted when the call ends
- If a call has zero duration (no answer), the reserved credit is refunded
- Balance can never go negative (row-level DB lock on deduction)

---

## Docker

```bash
# Build and run backend + frontend (requires built frontend dist/)
cd frontend && npm run build && cd ..
docker compose up

# With local MongoDB
docker compose --profile local up
```

---

## Project Structure

```
voice_agent/
├── main.py                    FastAPI app, all routes
├── config.py                  Environment variable loading
├── pg_db.py                   PostgreSQL schema + queries
├── db.py                      MongoDB connection
│
├── campaign_orchestrator_pg.py  Campaign dispatch loop
├── campaign_models.py           Pydantic/dataclass models
├── credit_service.py            Prepaid credit logic
│
├── exotel_handler.py            Exotel WebSocket call handler
├── gemini_bridge.py             Gemini Live audio bridge
├── outbound.py                  Exotel Make-a-Call API
├── audio_utils.py               PCM resampling utilities
├── call_store.py                In-memory call param store
│
├── classifier.py                Transcript classification
├── insights_analyzer.py         Gemini post-call analysis
├── call_insights.py             MongoDB insights storage
├── lead_info.py                 MongoDB live lead data
├── lead_scorer.py               Lead scoring (0–100)
├── extractor.py                 Real-time info extraction
│
├── ocr_parser.py                PDF/image OCR contact extraction
├── csv_parser.py                CSV contact parsing
├── file_processor.py            Unified file processing pipeline
│
├── auth_middleware.py           API key authentication
├── rate_limiter.py              Sliding window rate limiter
├── event_bus.py                 In-process SSE event bus
├── scheduler.py                 Calling window checker
├── prompts.py                   Gemini system prompts
│
├── livekit_handler.py           LiveKit alternative handler
├── terminal_test.py             CLI test harness
│
├── frontend/                    React + Vite + Tailwind UI
│   └── src/
│       ├── pages/               Dashboard, Campaigns, Analytics, etc.
│       ├── components/          Reusable UI components
│       ├── hooks/               React Query hooks
│       └── api/                 API client
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Development Notes

- The backend uses **structlog** for structured JSON logging
- All DB operations use **psycopg2** connection pooling via `pg_db.get_connection()`
- The Gemini session is **pre-started** at `/exoml` time (before the customer picks up) to eliminate cold-start latency
- Barge-in detection drains the audio queue when Gemini detects the customer is speaking
- The `[[HANGUP]]` token in Gemini's response triggers a graceful call end
