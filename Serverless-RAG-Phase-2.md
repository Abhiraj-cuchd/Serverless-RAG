# Serverless RAG — Phase 2: Agentic AI Platform
### Development Plan — Start After Phase 1 is Fully Optimized

---

## Prerequisites Before Starting Phase 2

```
Phase 1 must be fully complete and stable:

✅ Hybrid search working (vector + keyword)
✅ Query expansion implemented
✅ Summary detection working
✅ Document selector UI in Streamlit
✅ FastAPI branch deployed on Railway
✅ All retrieval quality issues resolved
✅ README updated with live URLs
✅ INTERVIEW_PREP.md complete
✅ Everything pushed to GitHub
```

Do not start Phase 2 until every item above is checked.

---

## Vision

Transform the system from:

```
Phase 1 — Multi-user Document Q&A System
                    ↓
Phase 2 — Personal AI Task Execution Platform
```

Users will be able to:
- Upload documents and ask questions (existing)
- Assign open-ended tasks to an AI agent
- Watch the agent plan and execute steps live
- Confirm or revise plans before execution
- Download generated artifacts (PDFs, reports, plans)
- Resume interrupted workflows

---

## Agent Level — Level 3 (Full Agent)

This is NOT a fake agent with hardcoded if/else workflows.

```
Level 1 — Fake Agent (NOT building this)
→ Deterministic hardcoded steps
→ "Agent" is just a fancy function

Level 2 — Tool-Calling Agent (NOT building this)
→ LLM decides which tools to call
→ No reflection or replanning

Level 3 — Planning + Reflection Agent (BUILDING THIS)
→ LLM plans before acting
→ Executes tools dynamically
→ Reflects on tool outputs
→ Revises plan if output is insufficient
→ Confirmation loops with user
→ Persistent state across invocations
```

---

## Core Design Decision — RAG as a Tool

The existing Python RAG pipeline is exposed as one of the agent's tools.

```
Agent needs document context
        ↓
Calls rag_search_tool internally
        ↓
rag_search_tool calls existing Query Lambda
        ↓
Returns relevant chunks from pgvector
        ↓
Agent uses chunks in its reasoning
```

Zero duplication. The agent reuses the entire Phase 1 pipeline.

---

## Architecture

```
Streamlit UI
    |
    |---- Query Mode -----> API Gateway → Query Lambda (Phase 1, unchanged)
    |
    |---- Agent Mode -----> API Gateway → Agent Lambda (Phase 2, TypeScript)
                                              |
                                         LangGraph
                                         Orchestrator
                                              |
                              ┌───────────────┼───────────────┐
                              ↓               ↓               ↓
                         Planner Node    Tool Router     Reflection Node
                              |               |               |
                              └───────────────┼───────────────┘
                                              ↓
                                    ┌─────────────────┐
                                    │   Tool Registry  │
                                    ├─────────────────┤
                                    │ rag_tool         │ → calls pgvector
                                    │ pdf_tool         │ → generates PDF
                                    │ summary_tool     │ → summarizes chunks
                                    │ planner_tool     │ → structured plans
                                    │ web_search_tool  │ → Tavily API (free)
                                    └─────────────────┘
                                              ↓
                                       Supabase
                                    (agent state tables)
```

---

## Tech Stack — Agent Lambda

| Layer | Technology | Reason |
|---|---|---|
| Runtime | TypeScript (Node.js) | Developer already knows Node.js ecosystem |
| Agent Framework | LangGraph (JS SDK) | Level 3 agent support, stateful graphs |
| LLM | Sarvam AI | Free, consistent with Phase 1 |
| PDF Generation | pdfkit | Free, Node.js native |
| Web Search | Tavily API | Free tier, built for LLM agents |
| State Storage | Supabase PostgreSQL | Already in stack, zero extra cost |
| Artifact Storage | AWS S3 | Already in stack, free tier |
| Deploy | AWS SAM | Consistent with Phase 1 |

---

## LangGraph Flow

```
START
  ↓
[Intent Parser Node]
  → What does the user want?
  → What tools are needed?
  → What is the expected output format?
  ↓
[Planner Node]
  → Break task into concrete steps
  → Assign tools to each step
  → Define success criteria
  ↓
[Tool Router Node]
  → Execute next tool in the plan
  → Pass output to next node
  ↓
[Reflection Node]  ← What makes this Level 3
  → Was the tool output sufficient?
  → Does the plan need revision?
  → Is more context needed?
  → If yes → loop back to Tool Router
  → If no → proceed to output
  → Max reflection loops: 3 (prevents infinite loops)
  ↓
[Output Formatter Node]
  → Structure the final response
  → Generate artifact if needed
  ↓
[Confirmation Node]
  → Show plan/output to user
  → Wait for approval or revision request
  → If revision → loop back to Planner
  ↓
END
```

---

## Agent State Definition

```typescript
interface AgentState {
  // Identity
  userId: string
  sessionId: string
  runId: string

  // Task
  userMessage: string
  intent: string
  plan: PlanStep[]
  currentStepIndex: number

  // Execution
  toolOutputs: ToolOutput[]
  reflectionCount: number      // max 3 — prevents infinite loops
  needsMoreContext: boolean

  // Output
  finalAnswer: string
  artifactUrl: string | null

  // Control
  awaitingConfirmation: boolean
  isComplete: boolean
  error: string | null
}

interface PlanStep {
  stepIndex: number
  description: string
  toolName: string
  toolInput: Record<string, unknown>
  status: "pending" | "running" | "complete" | "failed"
  output: string | null
}
```

---

## Folder Structure

```
agent_lambda/
├── handler.ts                  # Lambda entry point
├── graph.ts                    # LangGraph graph definition
├── state.ts                    # AgentState type definitions
│
├── nodes/
│   ├── intentParser.ts         # parse and classify user intent
│   ├── planner.ts              # generate step-by-step execution plan
│   ├── toolRouter.ts           # decide which tool to call next
│   ├── reflection.ts           # evaluate output, decide to loop or proceed
│   └── outputFormatter.ts      # format final response + artifact
│
├── tools/
│   ├── ragTool.ts              # calls Phase 1 Query Lambda internally
│   ├── pdfTool.ts              # generates PDF using pdfkit
│   ├── summaryTool.ts          # summarizes retrieved document chunks
│   ├── plannerTool.ts          # generates structured plans/roadmaps
│   └── webSearchTool.ts        # Tavily web search for external context
│
└── utils/
    ├── supabase.ts             # agent state read/write
    ├── sarvam.ts               # Sarvam AI API calls
    └── logger.ts               # structured JSON logging
```

---

## New Supabase Tables

```sql
-- Run in Supabase SQL Editor when starting Phase 2

create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  session_id uuid,
  task text not null,
  status text default 'running',   -- running/paused/complete/failed
  state jsonb,                     -- full AgentState stored here
  created_at timestamp default now(),
  updated_at timestamp default now()
);

create table agent_steps (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references agent_runs(id) on delete cascade,
  step_index integer not null,
  tool_name text not null,
  tool_input jsonb,
  tool_output jsonb,
  reflection text,
  created_at timestamp default now()
);

create table agent_outputs (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references agent_runs(id) on delete cascade,
  output_type text not null,       -- text/pdf/json
  content text,
  s3_key text,                     -- for downloadable artifacts
  created_at timestamp default now()
);
```

---

## New API Endpoints

```
POST   /agent/run              → start a new agent task
GET    /agent/run/:id          → get current run status + steps
POST   /agent/run/:id/confirm  → user confirms or requests revision
GET    /agent/outputs/:id      → get/download generated artifact
```

---

## Tool Registry — Phase 1 Tools

```
rag_search_tool
→ Searches user's uploaded documents via pgvector
→ Accepts: question, optional document_ids
→ Returns: relevant text chunks

summary_tool
→ Summarizes a set of retrieved chunks
→ Accepts: chunks array
→ Returns: concise summary paragraph

planner_tool
→ Generates structured plans (study plans, roadmaps, routines)
→ Accepts: goal, duration, constraints
→ Returns: structured week-by-week plan

pdf_export_tool
→ Converts structured text/plan to downloadable PDF
→ Accepts: title, content sections
→ Returns: S3 presigned download URL

web_search_tool
→ Searches the web for external context (Tavily API)
→ Accepts: search query
→ Returns: top 3-5 relevant results
```

---

## Tool Registry — Phase 2 Tools (Future)

```
resume_improver_tool
meeting_notes_generator
email_drafting_tool
syllabus_breakdown_tool
multi_document_report_tool
calendar_planner_tool
```

---

## Streamlit UI Changes

```python
# Add to sidebar navigation
mode = st.sidebar.radio("Mode", ["💬 Chat", "🤖 Agent", "📁 Documents", "🕓 History"])

if mode == "🤖 Agent":
    st.title("🤖 AI Agent")
    st.caption("Assign tasks — the agent will plan and execute them.")

    task = st.text_area(
        "What would you like me to do?",
        placeholder="e.g. Build a 6-week AWS certification study plan from my notes"
    )

    if st.button("▶ Run Agent", use_container_width=True):

        # Show live progress
        with st.status("Agent working...", expanded=True) as status:
            st.write("🧠 Parsing your request...")
            st.write("📋 Building execution plan...")
            st.write("🛠️ Executing tools...")
            st.write("🔄 Reflecting on output...")
            status.update(label="Done!", state="complete")

        # Confirmation step
        if response["awaiting_confirmation"]:
            st.subheader("Here's my plan:")
            st.write(response["plan"])
            col1, col2 = st.columns(2)
            with col1:
                st.button("✅ Looks good, proceed")
            with col2:
                st.button("✏️ Revise this")

        # Download artifact if generated
        if response.get("artifact_url"):
            st.success("Your document is ready!")
            st.download_button(
                "📥 Download",
                response["artifact_url"],
                use_container_width=True
            )
```

---

## Example End-to-End Agent Interactions

### Example 1 — Study Plan from Documents
```
User: "Build a 6-week AWS certification study plan from my uploaded notes"

Agent:
→ Intent: study_plan_generation
→ Plan: [search_docs, extract_topics, generate_weekly_plan, export_pdf]
→ Calls rag_search_tool → retrieves AWS notes content
→ Reflects → "enough context, proceeding"
→ Calls planner_tool → generates 6-week plan
→ Calls pdf_export_tool → generates PDF
→ Returns download link
```

### Example 2 — Multi-document Report
```
User: "Summarize all my uploaded documents into one report"

Agent:
→ Intent: multi_document_summary
→ Plan: [search_all_docs, summarize_each, combine, export_pdf]
→ Calls rag_search_tool multiple times (once per document)
→ Reflects → "need more chunks for doc 2"
→ Calls rag_search_tool again with different query
→ Calls summary_tool → combines into report
→ Calls pdf_export_tool → exports
→ Returns download link
```

### Example 3 — External Research + Document Comparison
```
User: "Compare my notes on machine learning with current industry practices"

Agent:
→ Intent: research_comparison
→ Plan: [search_user_docs, web_search, compare, format_report]
→ Calls rag_search_tool → gets user's ML notes
→ Calls web_search_tool → gets current industry info
→ Reflects → "good coverage, proceeding"
→ Formats comparison report
→ Returns structured answer
```

---

## Build Order — 6 Weeks

```
Week 1 — Foundation
→ Set up agent_lambda/ TypeScript project
→ Install LangGraph JS SDK
→ Define AgentState types
→ Create Supabase agent tables
→ Write basic handler.ts with health check

Week 2 — Core Nodes
→ Intent Parser Node
→ Planner Node
→ Basic Tool Router Node

Week 3 — Tools
→ RAG Tool (calls Phase 1 Query Lambda)
→ Summary Tool
→ Planner Tool

Week 4 — Level 3 Features
→ Reflection Node (loops back when output insufficient)
→ Confirmation loop
→ Max reflection count guard (prevents infinite loops)

Week 5 — Artifacts + Integration
→ PDF Export Tool (pdfkit)
→ Web Search Tool (Tavily)
→ Connect to API Gateway
→ Update Streamlit UI

Week 6 — Polish + Deploy
→ Error handling for all nodes
→ Agent step logging to Supabase
→ End to end testing with real tasks
→ Deploy via SAM
→ Demo preparation
```

---

## Cost Impact

```
LangGraph JS SDK       → free (open source)
Tavily web search      → free tier (1000 searches/month)
pdfkit PDF generation  → free (npm package)
Agent Lambda           → AWS free tier (1M requests/month)
Supabase agent tables  → free tier (existing 500MB)
S3 artifact storage    → free tier (existing 5GB)
──────────────────────────────────────────────
Extra monthly cost     → $0
```

---

## Resume Impact After Phase 2

```
Before Phase 2:
"Built a serverless RAG system with multi-user document Q&A"

After Phase 2:
"Built a serverless agentic AI platform with LangGraph orchestration,
dynamic tool routing, planning + reflection loops, RAG as a tool,
artifact generation, and persistent workflow state"
```

Roles this targets:
```
→ AI Engineer
→ Backend Engineer
→ Platform Engineer
→ GenAI Engineer
→ Solutions Architect
```

---

## Interview Talking Points for Phase 2

**On the agent architecture:**
*"The agent uses a planning node to break tasks into steps, a tool router
that dynamically selects tools, and a reflection node that evaluates output
quality and loops back if more context is needed. I set a max reflection
count of 3 to prevent infinite loops."*

**On RAG as a tool:**
*"Rather than duplicating the RAG pipeline, the agent calls the existing
Query Lambda as an internal API. This means the agent gets full document
search capability with zero code duplication."*

**On state persistence:**
*"Lambda is stateless but agent workflows are multi-step. I persist the
full AgentState as JSONB in Supabase between invocations. This also enables
user confirmation loops — the agent can pause, wait for user input, and
resume exactly where it left off."*

**On why TypeScript for this Lambda:**
*"The agent Lambda uses TypeScript because LangGraph's JS SDK has excellent
TypeScript support and I'm comfortable in the Node.js ecosystem. The Python
Lambdas handle RAG and the TypeScript Lambda handles orchestration —
each language plays to its strengths."*

---

## Key Risks to Watch

```
Risk 1 — Lambda timeout on long agent runs
→ Set max reflection loops to 3
→ Keep individual tool calls under 30 seconds
→ If workflow exceeds 15 minutes → consider AWS Step Functions

Risk 2 — Sarvam AI rate limiting during multi-tool runs
→ Agent makes multiple LLM calls per task
→ Rate limiter from Phase 1 applies here too
→ Add exponential backoff between reflection loops

Risk 3 — Agent hallucinates tool calls
→ Use strict Zod schemas for all tool inputs
→ Validate tool inputs before execution
→ Log all tool calls to agent_steps table

Risk 4 — Cost creep from web search
→ Tavily free tier = 1000 searches/month
→ Only call web_search_tool when rag_tool returns insufficient results
→ Reflection node should prefer rag_tool over web_search_tool
```

---

*Phase 2 development starts after Phase 1 is fully stable and deployed.*
*All Phase 1 code remains unchanged — agent mode is purely additive.*