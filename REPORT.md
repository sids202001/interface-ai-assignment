# Design Write-Up: Computer-Use Automation System

**Author:** Siddhesh Sawant  
**Role:** Software Engineer Candidate — interface.ai  
**Scope:** Backend integration layer automating legacy bank & credit union servicing applications.

---

## 1. Architecture

The core insight behind this system is an asymmetric execution model: **reason once with an expensive LLM, execute millions of times with a fast, deterministic robot.**

```
[ Natural Language Goal ]
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│ 1. Discovery Engine (agent.py)                          │
│    • Observe: Semantic DOM & accessibility tree parse   │
│    • Decide: LLM (via LiteLLM) or simulated planner     │
│    • Act: Playwright live session interaction           │
│    • Parameterize: Detect dynamic variables & outputs   │
└───────────────────────────┬─────────────────────────────┘
                            │ Compiles
                            ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Structured Capability Artifact (artifact.py)         │
│    • Typed Inputs & Outputs                             │
│    • Resilient Locators with Fallbacks & Reasoning      │
│    • Safety Policy & Checkpoints                        │
│    • Business Outcome Rules                             │
└───────────────────────────┬─────────────────────────────┘
                            │ Ingests
                            ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Deterministic Replay Engine (replay.py)              │
│    • Zero LLM inference in production path              │
│    • Parameter hydration (e.g. {{member_id}})           │
│    • Multi-tier error classification                    │
│    • Automatic recovery for transient modals            │
│    • Live CDP Human Escalation Seam (escalation.py)     │
└─────────────────────────────────────────────────────────┘
```

### Key Decisions & Trade-offs
- **Language & Runtime (Python 3.9+ / Playwright)**: Selected Playwright over raw HTTP or Selenium because legacy core banking applications frequently rely on framesets, asynchronous postbacks, and dynamically rendered JS where standard DOM inspection fails. Playwright gives direct access to the Chrome DevTools Protocol (CDP), allowing live session pausing, screenshot capture, and resilient auto-waiting.
- **Decoupled Artifact Contract**: The discovery loop outputs a standalone Pydantic JSON artifact. The Replay Engine has zero dependency on LLM packages or network access to model providers, achieving sub-second execution speeds, predictable cost, and complete determinism.
- **Synchronous CDP Session Control**: Replay and discovery operate on a live browser context, enabling instant human takeover without session tearing or credential re-authentication.

---

## 2. Artifact Schema

The artifact schema (`src/artifact.py`) acts as a strongly typed capability contract between discovery and runtime callers:

```json
{
  "version": "1.0.0",
  "name": "open_savings_sub_account",
  "description": "Looks up a banking member and opens a High-Yield Savings sub-account.",
  "category": "account_servicing",
  "safety_policy": {
    "allowed_domains": ["*"],
    "allowed_actions": ["click", "fill", "select", "read", "navigate", "wait"],
    "requires_confirmation_on_risky": true,
    "sensitive_fields": ["member_id", "ssn"]
  },
  "inputs": [
    { "name": "member_id", "type": "string", "description": "Member identification number", "required": true }
  ],
  "outputs": [
    { "name": "new_account_id", "type": "string", "description": "Generated sub-account ID", "extract_key": "new_account_id" }
  ],
  "steps": [
    {
      "step_number": 1,
      "step_type": "fill",
      "target": {
        "selector": "#member-id",
        "strategy": "css",
        "reasoning": "Unique input ID in core servicing portal",
        "fallback_selectors": ["[id='member-id']"]
      },
      "value": "{{member_id}}",
      "description": "Fill #member-id with '12345'",
      "is_risky": false,
      "timeout_ms": 5000
    }
  ],
  "success_checkpoint": {
    "condition_type": "element_visible",
    "target": { "selector": "#success-page", "strategy": "css", "reasoning": "Success confirmation container" }
  },
  "business_outcome_rules": [
    {
      "name": "Member Not Found",
      "selector": "#search-error:not(.hidden)",
      "outcome_type": "MEMBER_NOT_FOUND"
    }
  ]
}
```

### Design Rationale
1. **Parameterized Templating (`{{variable}}`)**: Inputs are abstracted from concrete discovery values. At replay time, variable interpolation hydrates the actions safely without hardcoding runtime values in the artifact.
2. **First-Class Output Extraction (`read` steps)**: Replay is not merely click-and-forget; calling agents need data returned (e.g. provisioned `account_id` or retrieved `balance`). The schema declares typed outputs that are bound during step execution.
3. **Multi-Strategy Locators with Explicit Reasoning**: Each target records the selector, strategy, human-readable stability reasoning, and an array of fallback locators to mitigate minor markup churn.
4. **Explicit Business Outcome Rules**: Embedded pattern matchers allow the replay engine to categorize expected business domain states rather than treating them as unhandled script failures.

---

## 3. Determinism & Error Handling

In enterprise banking automation, UI layouts change infrequently, but runtime conditions vary wildly. The Replay Engine implements a rigorous **Three-Tier Error Taxonomy**:

```
                              Replay Action
                                    │
                  ┌─────────────────┼─────────────────┐
                  ▼                 ▼                 ▼
          [ Business Outcome ] [ Recoverable ]  [ Hard Failure ]
          • Member Not Found   • Transient Modal • Missing Locator
          • Account Frozen     • Loading Delay   • Checkpoint Mismatch
          • Validation Error   • Session Banner  • Policy Violation
                  │                 │                 │
                  ▼                 ▼                 ▼
             Return Clean     Auto-Dismiss /     Capture Visual & DOM
            Outcome Payload    Auto-Wait / Retry   Evidence / Escalate
```

1. **Expected Business Outcomes**: When an input triggers a domain error (e.g. Member ID `00000` producing `"Error: Member not found in core system"`), the engine matches defined rules and returns a structured outcome `{status: "business_outcome", outcome_type: "MEMBER_NOT_FOUND", message: "..."}`. The caller gets actionable business intelligence without an exception trace.
2. **Recoverable Conditions**: Transient system advisories, security interstitials, or slow server responses are resolved automatically via built-in interstitial dismissers and Playwright implicit auto-waiting.
3. **Hard Failures**: Structural breaks, timeout expirations, or checkpoint assertion failures immediately halt execution. The engine writes a failure screenshot (`evidence/failure_screenshot_<timestamp>.png`) and a full DOM snapshot (`evidence/failure_dom_<timestamp>.html`), returning a precise debug trace with step index and expected vs observed state.

---

## 4. Heterogeneity & Multi-tenant

### Surface Abstraction
The system's core abstraction decouples **perception and actuation** from **flow definition**:
$$\text{Action} \longrightarrow \text{Target (Locator)} \longrightarrow \text{Value / Operation}$$

- **Legacy Web Apps (Framesets / No Clean DOM)**: Playwright evaluates the rendered page and accessible DOM tree across iframe boundaries, targeting controls by text, ARIA roles, or position heuristics rather than brittle CSS IDs.
- **Desktop Windows Apps (Core Banking Fat Clients)**: The same `CapabilityArtifact` schema extends to native desktop surfaces by swapping the Playwright driver for an OS automation driver (e.g. `pywinauto` or Microsoft UI Automation / Accessibility Tree API) without modifying the high-level step sequencing or replay contract.

### Multi-Tenant Reuse & Drift Management
Hundreds of credit unions run identical vendor core software (e.g. Jack Henry Symitar, Fiserv DNA, FIS Horizon) with minor tenant-specific branding, field rearrangements, or custom skins:
1. **Base Artifact Inheritance**: A canonical base capability artifact defines the workflow graph.
2. **Tenant Overrides (`tenant_overrides.json`)**: Specific institutions supply overlay locators or custom route parameters that override base selectors at runtime without re-recording the flow.
3. **Drift Detection**: When a tenant-specific replay fails a locator or checkpoint assertion while other tenants succeed, the system flags **Tenant UI Drift**, automatically queuing that tenant's capability for LLM rediscovery.

---

## 5. Escalation & Handoff

When an unexpected blocker or high-risk transaction occurs, the system triggers human-in-the-loop escalation (`src/escalation.py`) via live CDP session preservation:

```
Automated Replay ──> [Blocker / Risky Step] ──> Freeze Live CDP Session
                                                        │
                                                        ▼
                                             Create Intervention Request
                                             (Context, Reason, Live URL, Snapshot)
                                                        │
                                                        ▼
                                             Operator Manual Action
                                             (Dismiss Modal / Confirm Step)
                                                        │
                                                        ▼
Automated Replay ◄── Resume on SAME Session ◄── Operator Handback Signal
```

1. **Detection & Routing**: The engine catches blocking overlays or unresolvable timeouts, immediately freezing the live page state and emitting a structured `InterventionRequest` containing the capability name, step number, live URL, diagnostic snapshot, and suggested action.
2. **Live Session Takeover**: Rather than aborting and forcing a human to restart a fresh session, the automation cedes control on the **exact same browser instance**. The operator inspects the live page, dismisses unexpected dialogs, or performs multi-factor authorization.
3. **Control Handback & Audit**: The operator signals resumption through the CLI console. The engine verifies the updated page state, logs the operator's actions to the audit trail, and seamlessly resumes automated execution to completion.

---

## 6. Safety & Guardrails

Financial back-office automation requires strict guardrails (`src/guardrails.py`):

1. **Domain & Route Allowlists**: Navigation is restricted to explicitly whitelisted domains (e.g. `*.corebank.internal`). Arbitrary external redirects are blocked prior to navigation.
2. **Action Allowlist & Irreversible Step Flagging**: Permitted step types are restricted to safe operations (`click`, `fill`, `select`, `read`, `navigate`, `wait`). High-risk actions (e.g. fund transfers, account issuance, record deletion) are tagged `is_risky: true` and require operator confirmation when safety policies dictate.
3. **Regulated Data & PII Redaction**: Sensitive parameter keys (`member_id`, `ssn`, `pin`, `password`) and SSN regex patterns (`\d{3}-\d{2}-\d{4}`) are automatically masked as `[REDACTED_PII]` across all standard output streams, execution logs, and committed artifacts.

---

## 7. Cuts & Next Steps

To deliver a working, high-depth vertical slice within a reasonable scope, the following intentional cuts were made:

### What Was Cut
1. **Web-Based Operator Co-Browsing Console**: Real-time multi-user WebSocket video streaming was omitted in favor of a clean CDP-level CLI intervention seam that proves session preservation and control transfer.
2. **Desktop OS Automation Driver**: Implemented against a real browser surface with an architecture designed to drop in an OS accessibility tree driver (`pywinauto`/UIA).
3. **Automated Multi-Tenant Drift Self-Healing**: Drift is currently detected and surfaced via checkpoint errors rather than triggering automatic real-time LLM re-recording in the background.

### Next Steps for Production
1. **Accessibility-Tree First Locators**: Upgrade the discovery locator generator to prioritize computed accessibility paths (`role` + `name`) over CSS selectors for maximum layout resilience.
2. **Postgres Capability Registry**: Store versioned artifacts in a centralized database with role-based access control (RBAC) and draft/approved lifecycle staging.
3. **Bounded LLM Replay Fallback**: On step failure, permit a single-step, policy-constrained LLM recovery attempt before escalating to a human operator.
