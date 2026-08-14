import os
import json
import time
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright, Page
from artifact import (
    CapabilityArtifact,
    Action,
    Locator,
    Checkpoint,
    CapabilityInput,
    CapabilityOutput,
    SafetyPolicy,
    BusinessOutcomeRule
)
from guardrails import validate_action_safety, detect_irreversible_action, redact_sensitive_payload

MODEL = os.getenv("LLM_MODEL", "gpt-4o")

class AgentRun:
    def __init__(self, page: Page, goal: str, safety_policy: Optional[SafetyPolicy] = None):
        self.page = page
        self.goal = goal
        self.safety_policy = safety_policy or SafetyPolicy()
        self.history: List[Dict[str, Any]] = []
        self.recorded_steps: List[Action] = []
        self.inputs_identified: List[CapabilityInput] = []
        self.outputs_identified: List[CapabilityOutput] = []

    def get_surface_state(self) -> str:
        """
        Extracts a compact semantic representation of the interactive surface,
        combining DOM elements, accessibility roles, and visible text.
        Works against legacy markup with nested tables or non-semantic structures.
        """
        return self.page.evaluate('''() => {
            let elements = [];
            const interactiveSelectors = 'input, button, select, textarea, [role="button"], h1, h2, h3, span[id], strong[id], div.error, .success-box';
            document.querySelectorAll(interactiveSelectors).forEach(el => {
                // Ignore hidden containers
                if (el.closest('.hidden') || el.offsetParent === null) return;
                
                const id = el.id || '';
                const tag = el.tagName.toLowerCase();
                const text = (el.innerText || el.placeholder || el.value || '').trim();
                const type = el.type || el.getAttribute('role') || '';
                
                elements.push({
                    tag: tag,
                    id: id,
                    text: text.substring(0, 100),
                    type: type,
                    classes: el.className || ''
                });
            });
            return JSON.stringify(elements);
        }''')

    def run(self) -> CapabilityArtifact:
        print(f"\n[Discovery Engine] Goal: \"{self.goal}\"")
        print(f"[Discovery Engine] Target Surface: {self.page.url}")

        prompt_template = """
You are a computer-use discovery agent mapping legacy core banking software.
Your job is to accomplish the goal by interacting with the UI and emit a parameterized, reusable artifact.

Goal: {goal}

Current Surface State (Semantic Elements):
{state}

Action History:
{history}

Decide the next action. Respond ONLY with a valid JSON object matching this schema:
{{
    "thought": "Reasoning about what to do next based on the observed state",
    "action": "click" | "fill" | "select" | "read" | "done",
    "target_selector": "CSS selector or element id",
    "strategy": "css" | "text" | "role" | "xpath",
    "locator_reasoning": "Why this selector is resilient to UI shifts",
    "value": "Value to input/select or variable name",
    "is_input_parameter": true/false,
    "parameter_name": "name of parameter (e.g. member_id) if dynamic",
    "extract_output_key": "key name if action is read (e.g. new_account_id)"
}}
"""
        max_steps = 10
        has_api_key = bool(
            os.getenv("OPENAI_API_KEY") or 
            os.getenv("ANTHROPIC_API_KEY") or 
            os.getenv("GEMINI_API_KEY")
        )

        for step in range(max_steps):
            state = self.get_surface_state()
            action_json = None

            if has_api_key:
                try:
                    import litellm
                    litellm.suppress_debug_info = True
                    prompt = prompt_template.format(
                        goal=self.goal,
                        state=state,
                        history=json.dumps(self.history)
                    )
                    response = litellm.completion(
                        model=MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        response_format={"type": "json_object"}
                    )
                    action_json = json.loads(response.choices[0].message.content)
                except Exception as e:
                    print(f"[Discovery Engine] LLM invocation notice: {e}. Utilizing fallback discovery sequence.")
                    action_json = None

            if not action_json:
                action_json = self._simulate_discovery_step(step)

            thought = action_json.get("thought", "")
            act = action_json.get("action", "done")
            target_selector = action_json.get("target_selector", "")
            val = action_json.get("value")
            reasoning = action_json.get("locator_reasoning", "Stable unique element locator")
            strategy = action_json.get("strategy", "css")

            print(f"  Step {step + 1}: [{act.upper()}] {target_selector or ''} (Thought: {thought})")
            self.history.append(action_json)

            if act == "done":
                print("[Discovery Engine] Goal achieved. Compiling capability artifact...")
                break

            # Format selector
            if target_selector and not target_selector.startswith(("#", ".", "//", "xpath")):
                selector = f"#{target_selector}"
            else:
                selector = target_selector

            # Create action model
            action_model = Action(
                step_number=step + 1,
                step_type=act,
                target=Locator(
                    selector=selector,
                    strategy=strategy,
                    reasoning=reasoning,
                    fallback_selectors=[f"[id='{target_selector.replace('#', '')}']"] if selector.startswith("#") else []
                ),
                description=f"{act.capitalize()} on {selector}" if not val else f"{act.capitalize()} {selector} with '{val}'",
                is_risky=detect_irreversible_action(Action(step_type=act, description=thought, target=Locator(selector=selector, reasoning=reasoning)))
            )

            # Safety check
            validate_action_safety(action_model, self.safety_policy, self.page.url)

            # Execute action on live browser
            if act == "click":
                self.page.click(selector, timeout=5000)
                self.recorded_steps.append(action_model)
            elif act == "fill":
                self.page.fill(selector, val, timeout=5000)
                rec_val = val
                if action_json.get("is_input_parameter"):
                    p_name = action_json.get("parameter_name", "input_var")
                    rec_val = f"{{{{{p_name}}}}}"
                    if not any(inp.name == p_name for inp in self.inputs_identified):
                        self.inputs_identified.append(CapabilityInput(
                            name=p_name,
                            type="string",
                            description=f"Input parameter for {target_selector}"
                        ))
                action_model.value = rec_val
                self.recorded_steps.append(action_model)
            elif act == "select":
                self.page.select_option(selector, val, timeout=5000)
                action_model.value = val
                self.recorded_steps.append(action_model)
            elif act == "read":
                extracted_text = self.page.inner_text(selector, timeout=5000).strip()
                out_key = action_json.get("extract_output_key", "extracted_value")
                action_model.extract_key = out_key
                self.outputs_identified.append(CapabilityOutput(
                    name=out_key,
                    type="string",
                    description=f"Extracted text from {selector}",
                    extract_key=out_key
                ))
                self.recorded_steps.append(action_model)

            self.page.wait_for_timeout(400)

        return self._build_artifact()

    def _simulate_discovery_step(self, step: int) -> Dict[str, Any]:
        """Realistic discovery flow for demo banking target when running offline/unkeyed."""
        plan = [
            {
                "thought": "Enter member identification number to look up profile",
                "action": "fill",
                "target_selector": "member-id",
                "strategy": "css",
                "locator_reasoning": "Unique input ID in core servicing portal",
                "value": "12345",
                "is_input_parameter": True,
                "parameter_name": "member_id"
            },
            {
                "thought": "Trigger search lookup query",
                "action": "click",
                "target_selector": "search-btn",
                "strategy": "css",
                "locator_reasoning": "Primary action button on search screen"
            },
            {
                "thought": "Initiate sub-account creation workflow for retrieved member",
                "action": "click",
                "target_selector": "open-sub-btn",
                "strategy": "css",
                "locator_reasoning": "Action button in member detail container"
            },
            {
                "thought": "Select High-Yield Savings product from dropdown",
                "action": "select",
                "target_selector": "account-type",
                "strategy": "css",
                "locator_reasoning": "Product select control in opening form",
                "value": "savings"
            },
            {
                "thought": "Confirm opening and submit request to core banking ledger",
                "action": "click",
                "target_selector": "submit-sub-btn",
                "strategy": "css",
                "locator_reasoning": "Confirmation button on sub-account form"
            },
            {
                "thought": "Read newly generated account ID from confirmation screen",
                "action": "read",
                "target_selector": "new-acct-id",
                "strategy": "css",
                "locator_reasoning": "Account confirmation badge element",
                "extract_output_key": "new_account_id"
            },
            {
                "thought": "Successfully reached confirmation receipt screen",
                "action": "done"
            }
        ]
        if step < len(plan):
            return plan[step]
        return {"action": "done", "thought": "Plan completed."}

    def _build_artifact(self) -> CapabilityArtifact:
        return CapabilityArtifact(
            version="1.0.0",
            name="open_savings_sub_account",
            description="Looks up a banking member and opens a new High-Yield Savings sub-account, returning the provisioned account ID.",
            category="account_servicing",
            safety_policy=SafetyPolicy(
                allowed_domains=["*"],
                allowed_actions=["click", "fill", "select", "read", "navigate", "wait"],
                requires_confirmation_on_risky=True,
                sensitive_fields=["member_id", "ssn"]
            ),
            inputs=self.inputs_identified or [
                CapabilityInput(name="member_id", type="string", description="Member identification number", required=True)
            ],
            outputs=self.outputs_identified or [
                CapabilityOutput(name="new_account_id", type="string", description="Generated sub-account ID", extract_key="new_account_id")
            ],
            steps=self.recorded_steps,
            success_checkpoint=Checkpoint(
                condition_type="element_visible",
                target=Locator(selector="#success-page", strategy="css", reasoning="Success confirmation container is displayed"),
                timeout_ms=5000
            ),
            business_outcome_rules=[
                BusinessOutcomeRule(
                    name="Member Not Found",
                    selector="#search-error:not(.hidden)",
                    outcome_type="MEMBER_NOT_FOUND",
                    description="Member ID was not found in core database"
                ),
                BusinessOutcomeRule(
                    name="Account Frozen",
                    selector="#search-error:not(.hidden)",
                    outcome_type="ACCOUNT_FROZEN",
                    description="Member profile is inactive or flagged"
                ),
                BusinessOutcomeRule(
                    name="Validation Error",
                    selector="#subaccount-error:not(.hidden)",
                    outcome_type="VALIDATION_ERROR",
                    description="Form input validation rejected by application"
                )
            ]
        )

def run_discovery(url: str, goal: str, output_path: str, headless: bool = True):
    print("=" * 65)
    print("🚀 [STARTING DISCOVERY ENGINE]")
    print(f"Goal   : {goal}")
    print(f"Target : {url}")
    print("=" * 65)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url)

        agent = AgentRun(page, goal)
        artifact = agent.run()

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(artifact.model_dump_json(indent=2))

        print(f"\n[Discovery Engine] Reusable capability artifact compiled and written to: {output_path}")
        browser.close()
