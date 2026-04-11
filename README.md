# Serverless RAG Knowledge Assistant

A multi-user, serverless AI-powered document question-and-answer system.
Upload documents, ask questions, get answers grounded in your own private document index.

---

## What It Does

1. **Sign up / log in** — every user gets a private isolated workspace
2. **Upload** a PDF or TXT document
3. System **extracts, chunks, and embeds** the text automatically in the background
4. **Ask questions** about your documents via Streamlit UI or API
5. Get **accurate answers** grounded only in your documents — not someone else's
6. **Chat history** is saved per session so you can scroll back anytime

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   USER FACING                        │
│                                                      │
│   Streamlit App              FastAPI Docs            │
│   (streamlit.io — free)      (Railway — free)        │
│   → visual chat UI           → /docs swagger UI      │
│                              → developers test API   │
└──────────────┬───────────────────┬──────────────────┘
               │                   │
               ▼                   ▼
┌─────────────────────────────────────────────────────┐
│                AWS API GATEWAY                       │
│   /auth/register    /auth/login                      │
│   /ingest/upload    /ingest/documents                │
│   /query            /query/history                   │
└──────────────┬───────────────────┬──────────────────┘
               │                   │
               ▼                   ▼
┌─────────────────────┐   ┌───────────────────────────┐
│   INGESTION FLOW    │   │      QUERY FLOW            │
│                     │   │                            │
│  S3 upload          │   │  Query Lambda              │
│       ↓             │   │  → embed question          │
│  SQS Queue          │   │  → pgvector search         │
│       ↓ (x3 retry)  │   │  → Sarvam AI answer        │
│  DLQ (on failure)   │   │  → save to chat_messages   │
│       ↓             │   │  → return response         │
│  Ingestion Lambda   │   └───────────────────────────┘
│  → extract text     │
│  → chunk text       │
│  → Titan embeddings │
│  → store pgvector   │
└─────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│                   SUPABASE                           │
│   users          → auth + profile                   │
│   documents      → metadata + upload status         │
│   sessions       → conversation groups              │
│   chat_messages  → full Q&A history                 │
│   embeddings     → pgvector per user (private)      │
└─────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer         | Technology                  | Purpose                       |
| ------------- | --------------------------- | ----------------------------- |
| Frontend      | Streamlit                   | Visual chat UI                |
| API Docs      | FastAPI on Railway          | Developer-facing swagger UI   |
| Compute       | AWS Lambda (x2)             | Ingestion + Query             |
| Queue         | AWS SQS + DLQ               | Reliable background ingestion |
| File Storage  | AWS S3                      | Raw uploaded documents only   |
| Embeddings    | Amazon Titan V1 via Bedrock | Text → vectors               |
| Vector Search | pgvector on Supabase        | Semantic similarity search    |
| LLM           | Sarvam AI                   | Generates final answers       |
| Database      | Supabase PostgreSQL         | Users, docs, chat, vectors    |
| Auth          | JWT tokens                  | Scoped per user               |
| IaC           | AWS SAM                     | Deploy AWS infra as code      |

---

## Database Schema

```
users
├── id              UUID (primary key)
├── email           TEXT unique
├── hashed_password TEXT
└── created_at      TIMESTAMP

documents
├── id              UUID (primary key)
├── user_id         UUID (FK → users)
├── filename        TEXT
├── s3_key          TEXT
├── status          TEXT (processing / ready / failed)
└── uploaded_at     TIMESTAMP

sessions
├── id              UUID (primary key)
├── user_id         UUID (FK → users)
├── title           TEXT (auto set from first question)
└── created_at      TIMESTAMP

chat_messages
├── id              UUID (primary key)
├── session_id      UUID (FK → sessions)
├── user_id         UUID (FK → users)
├── question        TEXT
├── answer          TEXT
├── sources         JSON (list of filenames used)
└── created_at      TIMESTAMP

embeddings
├── id              UUID (primary key)
├── user_id         UUID (FK → users)
├── document_id     UUID (FK → documents)
├── chunk_text      TEXT
├── chunk_index     INTEGER
└── embedding       VECTOR(1536)
```

---

## API Endpoints

```
POST   /auth/register        → create account
POST   /auth/login           → returns JWT token

POST   /ingest/upload        → upload document (auth required)
GET    /ingest/documents     → list my documents (auth required)

POST   /query                → ask a question (auth required)
GET    /query/history        → get session chat history (auth required)
```

---

## Project Structure

```
serverless-rag/
├── .env
├── .gitignore
├── README.md
├── CLAUDE.md
├── template.yaml                 # SAM — deploys all AWS infra
│
├── services/                     # core logic — shared by lambdas + fastapi branch
│   ├── __init__.py
│   ├── extractor.py              # extract text from PDF/TXT
│   ├── chunker.py                # split text into overlapping chunks
│   ├── embedder.py               # call Titan for embeddings
│   ├── vector_store.py           # pgvector insert + search
│   └── llm.py                    # call Sarvam AI for answers
│
├── ingestion_lambda/
│   ├── handler.py                # entry point — orchestrates ingestion
│   └── requirements.txt
│
├── query_lambda/
│   ├── handler.py                # entry point — orchestrates query
│   └── requirements.txt
│
└── streamlit_app/
    └── app.py
```

---

## Git Branch Strategy

```
main branch
└── Lambda + SQS + Streamlit (live on AWS + Streamlit Cloud)

fastapi branch
└── FastAPI wrapping same services/ logic
└── Deployed on Railway (free)
└── Same Supabase DB — zero data changes
```

---

## Cost Estimate

| Service                        | Free Tier                      | Est. Monthly Cost      |
| ------------------------------ | ------------------------------ | ---------------------- |
| AWS Lambda                     | 1M requests FREE               | $0                     |
| AWS S3                         | 5 GB FREE                      | $0                     |
| AWS SQS + DLQ                  | 1M requests FREE               | $0                     |
| AWS API Gateway                | 1M calls FREE (12 months)      | $0                     |
| Supabase PostgreSQL + pgvector | 500 MB FREE                    | $0                     |
| Streamlit Cloud                | FREE                           | $0                     |
| Railway (FastAPI branch)       | $5 free credit/month      | $0 |                        |
| Titan Embeddings               | No free tier                   | ~$0.05                 |
| Sarvam AI                      | FREE                           | $0                     |
| **Total**                |                                | **~$0.05/month** |

---

## Build Order

```
Phase 1 — Services Layer (core logic)
→ extractor, chunker, embedder, vector_store, llm

Phase 2 — Lambda Pipeline + AWS
→ ingestion_lambda, query_lambda, SQS, API Gateway, SAM deploy

Phase 3 — Streamlit Frontend
→ connect to API Gateway URL, deploy to Streamlit Cloud

Phase 4 — FastAPI Branch
→ new git branch, wrap services/ in FastAPI, deploy to Railway
```

---

## Key Design Decisions

**Why pgvector over FAISS?**
FAISS requires saving/loading an index file from S3 on every Lambda cold start.
pgvector lives in Supabase — Lambda queries it like a regular database.
Simpler, no cold start penalty, supports concurrent users cleanly.

**Why SQS between S3 and Lambda?**
Direct S3 → Lambda invocation loses the event silently on failure.
SQS retries automatically up to 3 times. Failed messages go to DLQ for inspection.

**Why per-user vector scoping?**
All embeddings have a user_id column. Every pgvector search filters by user_id.
User A can never see User B's documents or chat history.

**Why stateful chat context?**
Query Lambda passes the last 3 messages from the session to Sarvam AI.
Follow-up questions work naturally without complex tree data structures.

**Why two UIs?**
Streamlit → non-technical users, clean chat experience.
FastAPI /docs → developers and interviewers can test every endpoint live in browser.

---

## Production Upgrade Path

* Replace Supabase free tier with dedicated PostgreSQL for scale
* Add CloudWatch alarms on DLQ message count and Lambda error rate
* Add X-Ray tracing for end-to-end request visibility
* Replace Sarvam AI with Claude Sonnet for higher quality answers
* Add document deletion with cascade vector cleanup
