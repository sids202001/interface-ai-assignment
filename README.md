# Computer-Use Automation System (Core Banking Integration)

A reliable backend integration system designed to give AI agents "hands" inside legacy core banking applications that lack modern APIs.

### The Core Concept (In Layman's Terms)
> **"Reason once with an AI scout, replay millions of times with a fast robot."**
> 
> Old bank back-office systems don't have APIs, forcing human tellers to manually click through multiple screens to do routine work. This system solves that:
> 1. **Discovery (The AI Scout)**: An LLM explores the legacy banking UI, figures out what buttons to click and fields to fill, and writes down a structured, reusable blueprint (`artifact.json`).
> 2. **Replay (The Fast Robot)**: In production, we don't use the slow/expensive AI. A fast, non-AI robot takes the blueprint, hydrates customer variables (like `member_id`), and runs the flow in under 2 seconds.
> 3. **Smart Handling & Human Backup**: If a member doesn't exist, it calmly returns a structured `"Member Not Found"` business result instead of crashing. If an unexpected security popup appears, it pauses the live browser session, alerts a human operator to approve it, and resumes on that exact same screen.

---

## Architecture Overview

```
                      [ Discovery Phase ]
    Goal / Prompt ──> LLM Agent Loop (Observe ─> Decide ─> Act)
                            │
                            ▼
               Structured Capability Artifact
                 (artifact.json: Typed Contract)
                            │
                            ▼
                      [ Replay Phase ]
    Inputs ─────────> Deterministic Replay Engine ──> Success + Outputs
    (e.g. member_id)        │                      ├──> Business Outcome
                            │                      └──> Hard Failure + Evidence
                            │
               [ Escalation / Human Handoff ]
               Live CDP Session Takeover & Resume
```

---

## Getting Started

### Prerequisites
- Python 3.9+
- Chromium browser binaries (installed via Playwright)

### Installation

```bash
# 1. Clone repository and navigate to directory
cd interface-ai-assignment

# 2. Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser binaries
playwright install chromium
```

### Environment Configuration (Optional)
The system supports live LLMs via `litellm` (OpenAI, Anthropic, Gemini, Azure, Ollama). If an API key is not configured, the Discovery Engine gracefully falls back to an offline exploration planner to demo artifact compilation without external service dependencies.

```bash
# Optional: Set your preferred LLM provider key
export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Demo Walkthrough

A standalone legacy core banking portal fixture is provided in `demo_site/index.html` (simulating member search, account servicing, and sub-account issuance).

### 1. Goal Discovery Run
Runs the discovery loop to map the UI flow and compile a reusable capability artifact.

```bash
export PYTHONPATH=src
python3 src/main.py discover \
  --url "file://$(pwd)/demo_site/index.html" \
  --goal "Open a high-yield savings sub-account for member 12345" \
  --output artifact.json
```

### 2. Deterministic Replay (Happy Path)
Executes the recorded flow with dynamic parameter hydration and extracts the newly generated account ID.

```bash
python3 src/main.py replay \
  --url "file://$(pwd)/demo_site/index.html" \
  --artifact artifact.json \
  --inputs '{"member_id": "12345"}'
```

### 3. Business Outcome Handling (Non-Happy Path)
Demonstrates taxonomy separation: searching for an invalid member (`00000`) or frozen member (`55555`) yields a structured `business_outcome` result rather than an unhandled crash.

```bash
python3 src/main.py replay \
  --url "file://$(pwd)/demo_site/index.html" \
  --artifact artifact.json \
  --inputs '{"member_id": "00000"}'
```

### 4. Human-in-the-Loop (HITL) Escalation & Session Handoff
Demonstrates live session takeover: when an unexpected modal blocks execution, the system pauses on the live browser session, routes an intervention request with rich context, transfers control to the operator, and seamlessly resumes to completion on the same session.

```bash
python3 src/main.py escalate \
  --url "file://$(pwd)/demo_site/index.html" \
  --artifact artifact.json
```

### 5. Stability & Flakiness Benchmark
Runs repeated consecutive replays and outputs a latency distribution and flakiness scorecard.

```bash
python3 src/main.py stability \
  --url "file://$(pwd)/demo_site/index.html" \
  --artifact artifact.json \
  --inputs '{"member_id": "12345"}' \
  --runs 5
```

---

## Project Structure

```
.
├── demo_site/
│   └── index.html          # Local mock legacy banking application fixture
├── evidence/
│   ├── artifact.json       # Sample compiled capability artifact
│   ├── discovery_run.log   # Execution log from LLM discovery
│   ├── replay_success.log  # Successful replay run with extracted outputs
│   ├── replay_business_outcome.log # Business outcome detection log
│   ├── replay_hard_failure.log     # Hard failure diagnostic log with evidence pointers
│   ├── escalation_handoff.log      # HITL intervention audit log
│   └── failure_screenshot_*.png    # Automated visual failure capture
├── src/
│   ├── agent.py            # LLM discovery loop and semantic DOM parser
│   ├── artifact.py         # Pydantic capability contract schemas
│   ├── escalation.py       # Human-in-the-loop intervention manager
│   ├── guardrails.py       # Safety policies, allowlists & PII redaction
│   ├── main.py             # CLI entrypoint
│   └── replay.py           # Zero-LLM deterministic replay engine
├── REPORT.md               # Detailed engineering design write-up
└── requirements.txt        # Python package dependencies
```
