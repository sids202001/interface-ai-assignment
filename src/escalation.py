import os
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from playwright.sync_api import Page

class InterventionRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"INT-{uuid.uuid4().hex[:8]}")
    capability_name: str
    step_index: int
    reason: str
    current_url: str
    screenshot_path: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    suggested_action: Optional[str] = None

class InterventionResolution(BaseModel):
    request_id: str
    status: str # 'resolved', 'aborted', 'skipped'
    operator_id: str = "operator-01"
    notes: str
    actions_performed: List[str] = Field(default_factory=list)
    resolved_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class EscalationManager:
    """
    Manages human-in-the-loop control transfer seams.
    Preserves the live browser CDP session, routes intervention context,
    and resumes deterministic automation without session tearing.
    """
    def __init__(self, evidence_dir: str = "evidence"):
        self.evidence_dir = evidence_dir
        os.makedirs(evidence_dir, exist_ok=True)
        self.audit_log: List[Dict[str, Any]] = []

    def create_intervention_request(
        self,
        page: Page,
        capability_name: str,
        step_index: int,
        reason: str,
        suggested_action: Optional[str] = "Inspect UI, resolve blocking state, or confirm step."
    ) -> InterventionRequest:
        timestamp = int(time.time())
        screenshot_name = f"escalation_{step_index}_{timestamp}.png"
        screenshot_path = os.path.join(self.evidence_dir, screenshot_name)
        
        try:
            page.screenshot(path=screenshot_path)
        except Exception:
            screenshot_path = None

        request = InterventionRequest(
            capability_name=capability_name,
            step_index=step_index,
            reason=reason,
            current_url=page.url,
            screenshot_path=screenshot_path,
            suggested_action=suggested_action
        )
        return request

    def handle_operator_intervention(
        self,
        request: InterventionRequest,
        page: Page,
        interactive: bool = True,
        auto_response: Optional[str] = None
    ) -> InterventionResolution:
        print("\n" + "=" * 65)
        print("🚨 [HUMAN-IN-THE-LOOP INTERVENTION TRIGGERED]")
        print(f"Request ID   : {request.request_id}")
        print(f"Capability   : {request.capability_name}")
        print(f"Failed Step  : Step {request.step_index}")
        print(f"Reason       : {request.reason}")
        print(f"Live URL     : {request.current_url}")
        if request.screenshot_path:
            print(f"Snapshot     : {request.screenshot_path}")
        print(f"Suggested    : {request.suggested_action}")
        print("=" * 65)

        if not interactive or auto_response:
            # Headless or programmatic resolution
            print(f"[Operator Console] Auto-resolving intervention via policy: '{auto_response or 'resume'}'")
            time.sleep(1) # Simulated operator response latency
            
            # If an interstitial modal exists, auto-dismiss in the live session
            try:
                dismiss_btn = page.locator("#dismiss-interstitial-btn")
                if dismiss_btn.is_visible(timeout=1000):
                    dismiss_btn.click()
                    print("[Operator Action] Dismissed blocking interstitial modal in live session.")
            except Exception:
                pass

            resolution = InterventionResolution(
                request_id=request.request_id,
                status="resolved",
                notes=f"Automated operator simulation: {auto_response or 'Dismissed dialog and resumed.'}",
                actions_performed=["dismiss_interstitial", "resume_automation"]
            )
        else:
            print("\n>>> LIVE SESSION PAUSED FOR OPERATOR TAKEOVER <<<")
            print("The live browser session is active. Take manual action if needed.")
            print("Commands:")
            print("  [r] Resume automation on current page state")
            print("  [d] Dismiss interstitial modal in browser & resume")
            print("  [s] Skip current step")
            print("  [a] Abort execution")
            
            choice = input("Enter operator decision [r/d/s/a] (default: r): ").strip().lower()
            if not choice:
                choice = "r"
                
            if choice == "d":
                try:
                    page.locator("#dismiss-interstitial-btn").click()
                    print("Operator dismissed modal.")
                except Exception as e:
                    print(f"Could not click dismiss: {e}")
                status = "resolved"
                notes = "Operator dismissed security modal manually."
                actions = ["dismiss_modal", "resume"]
            elif choice == "s":
                status = "skipped"
                notes = "Operator chose to skip blocked step."
                actions = ["skip_step"]
            elif choice == "a":
                status = "aborted"
                notes = "Operator aborted workflow."
                actions = ["abort"]
            else:
                status = "resolved"
                notes = "Operator inspected session and signaled resume."
                actions = ["manual_inspection", "resume"]

            resolution = InterventionResolution(
                request_id=request.request_id,
                status=status,
                notes=notes,
                actions_performed=actions
            )

        self.audit_log.append({
            "request": request.model_dump(),
            "resolution": resolution.model_dump()
        })
        
        print(f"[Operator Console] Control handed back to automation engine ({resolution.status}).\n")
        return resolution
