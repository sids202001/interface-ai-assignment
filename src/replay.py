import os
import json
import time
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError
from artifact import CapabilityArtifact, Action, Checkpoint
from guardrails import validate_action_safety, detect_irreversible_action, redact_sensitive_payload
from escalation import EscalationManager

class ReplayExecutionError(Exception):
    """Raised when a non-recoverable structural or timing failure occurs during replay."""
    pass

class BusinessOutcomeDetected(Exception):
    """Raised when an expected non-fatal business result (e.g., Member Not Found) is reached."""
    def __init__(self, outcome_type: str, message: str, step_index: int):
        self.outcome_type = outcome_type
        self.message = message
        self.step_index = step_index
        super().__init__(message)

def _handle_recoverable_interstitials(page: Page) -> bool:
    """Detects and dismisses known transient interstitials or system banners."""
    try:
        modal_dismiss = page.locator("#dismiss-interstitial-btn")
        if modal_dismiss.count() > 0 and modal_dismiss.is_visible(timeout=500):
            print("  [Auto-Recovery] Detected transient interstitial advisory. Auto-dismissing...")
            modal_dismiss.click()
            page.wait_for_timeout(300)
            return True
    except Exception:
        pass
    return False

def _check_business_outcome_rules(artifact: CapabilityArtifact, page: Page, step_index: int):
    """Checks page state against defined business outcome rules."""
    for rule in artifact.business_outcome_rules:
        try:
            loc = page.locator(rule.selector)
            if loc.count() > 0 and loc.first.is_visible(timeout=300):
                text = loc.first.inner_text().strip()
                if not rule.pattern or rule.pattern.lower() in text.lower():
                    raise BusinessOutcomeDetected(
                        outcome_type=rule.outcome_type,
                        message=text,
                        step_index=step_index
                    )
        except BusinessOutcomeDetected:
            raise
        except Exception:
            continue

def execute_replay_steps(
    artifact: CapabilityArtifact,
    inputs: Dict[str, Any],
    page: Page,
    escalation_mgr: Optional[EscalationManager] = None,
    interactive_escalation: bool = False
) -> Dict[str, Any]:
    print(f"\n[Replay Engine] Executing Capability: \"{artifact.name}\" (v{artifact.version})")
    print(f"[Replay Engine] Sanitized Inputs: {redact_sensitive_payload(inputs, artifact.safety_policy.sensitive_fields)}")
    
    extracted_outputs: Dict[str, Any] = {}

    for i, step in enumerate(artifact.steps):
        step_num = step.step_number or (i + 1)
        print(f"  Step {step_num}: {step.description}")

        # Check for recoverable interstitials before acting
        _handle_recoverable_interstitials(page)

        # Validate step against safety policies
        validate_action_safety(step, artifact.safety_policy, page.url)

        # Hydrate dynamic value template
        hydrated_value = step.value
        if hydrated_value:
            for key, val in inputs.items():
                hydrated_value = hydrated_value.replace(f"{{{{{key}}}}}", str(val))

        target_selector = step.target.selector if step.target else None
        timeout = step.timeout_ms or 5000

        try:
            # Check for business outcomes prior to executing step if error element is already active
            _check_business_outcome_rules(artifact, page, step_num)

            if step.step_type == "click" and target_selector:
                # Try primary selector with fallback
                try:
                    page.click(target_selector, timeout=timeout)
                except PlaywrightTimeoutError:
                    if step.target.fallback_selectors:
                        for fb in step.target.fallback_selectors:
                            try:
                                page.click(fb, timeout=2000)
                                break
                            except Exception:
                                pass
                        else:
                            raise
                    else:
                        raise

            elif step.step_type == "fill" and target_selector:
                page.fill(target_selector, hydrated_value or "", timeout=timeout)

            elif step.step_type == "select" and target_selector:
                page.select_option(target_selector, hydrated_value or "", timeout=timeout)

            elif step.step_type == "read" and target_selector:
                text = page.inner_text(target_selector, timeout=timeout).strip()
                out_key = step.extract_key or f"output_{step_num}"
                extracted_outputs[out_key] = text
                print(f"    -> Extracted [{out_key}]: {text}")

            elif step.step_type == "navigate" and hydrated_value:
                page.goto(hydrated_value, timeout=timeout)

            elif step.step_type == "wait":
                page.wait_for_timeout(int(hydrated_value or 500))

            # Settle wait
            page.wait_for_timeout(350)

            # Check for business outcomes that appeared immediately after step execution
            _check_business_outcome_rules(artifact, page, step_num)

        except BusinessOutcomeDetected:
            raise

        except PlaywrightTimeoutError as e:
            # Check if this timeout was actually caused by a business outcome error message on screen
            _check_business_outcome_rules(artifact, page, step_num)

            # If escalation is enabled, offer operator takeover before crashing
            if escalation_mgr and interactive_escalation:
                req = escalation_mgr.create_intervention_request(
                    page=page,
                    capability_name=artifact.name,
                    step_index=step_num,
                    reason=f"Timeout waiting for locator '{target_selector}' on step {step_num} ({step.description}).",
                    suggested_action="Check if modal/interstitial is blocking or UI state diverged."
                )
                resolution = escalation_mgr.handle_operator_intervention(req, page, interactive=True)
                if resolution.status == "resolved":
                    print(f"  [Replay Engine] Operator intervention resolved step {step_num}. Continuing...")
                    continue
                elif resolution.status == "skipped":
                    print(f"  [Replay Engine] Step {step_num} skipped by operator.")
                    continue
                else:
                    raise ReplayExecutionError(f"Step {step_num} aborted by operator: {resolution.notes}")

            raise ReplayExecutionError(
                f"Hard Failure on Step {step_num} ({step.description}): Locator '{target_selector}' timed out after {timeout}ms."
            )

        except Exception as e:
            raise ReplayExecutionError(f"Unexpected error executing step {step_num}: {e}")

    # Checkpoint Verification
    print("  [Replay Engine] Verifying success checkpoint condition...")
    cp = artifact.success_checkpoint
    cp_timeout = cp.timeout_ms or 5000

    try:
        if cp.condition_type == "element_visible" and cp.target:
            if not page.is_visible(cp.target.selector, timeout=cp_timeout):
                raise ReplayExecutionError(f"Success Checkpoint Failed: Element '{cp.target.selector}' is not visible.")
        elif cp.condition_type == "text_present" and cp.value:
            if not page.get_by_text(cp.value).is_visible(timeout=cp_timeout):
                raise ReplayExecutionError(f"Success Checkpoint Failed: Expected text '{cp.value}' not present.")
    except Exception as e:
        raise ReplayExecutionError(f"Checkpoint verification failed: {e}")

    print("[Replay Engine] Replay completed successfully.")
    return extracted_outputs

def run_replay(
    artifact_path: str,
    inputs: Dict[str, Any],
    url: str,
    headless: bool = True,
    interactive_escalation: bool = False,
    evidence_dir: str = "evidence"
) -> Dict[str, Any]:
    os.makedirs(evidence_dir, exist_ok=True)
    escalation_mgr = EscalationManager(evidence_dir=evidence_dir)

    with open(artifact_path, "r") as f:
        artifact_dict = json.load(f)
    artifact = CapabilityArtifact(**artifact_dict)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url)

        try:
            outputs = execute_replay_steps(
                artifact=artifact,
                inputs=inputs,
                page=page,
                escalation_mgr=escalation_mgr,
                interactive_escalation=interactive_escalation
            )
            result = {
                "status": "success",
                "capability": artifact.name,
                "version": artifact.version,
                "outputs": outputs,
                "sanitized_inputs": redact_sensitive_payload(inputs, artifact.safety_policy.sensitive_fields)
            }
            return result

        except BusinessOutcomeDetected as bo:
            print(f"\n[Business Outcome Reached] Type: {bo.outcome_type} | Message: \"{bo.message}\" (Step {bo.step_index})")
            return {
                "status": "business_outcome",
                "capability": artifact.name,
                "outcome_type": bo.outcome_type,
                "message": bo.message,
                "step_index": bo.step_index
            }

        except ReplayExecutionError as re:
            timestamp = int(time.time())
            screenshot_path = os.path.join(evidence_dir, f"failure_screenshot_{timestamp}.png")
            dom_dump_path = os.path.join(evidence_dir, f"failure_dom_{timestamp}.html")
            
            try:
                page.screenshot(path=screenshot_path)
                with open(dom_dump_path, "w") as dom_file:
                    dom_file.write(page.content())
            except Exception:
                pass

            print(f"\n[Hard Failure] {re}")
            print(f"  -> Evidence captured: Screenshot: {screenshot_path}, DOM: {dom_dump_path}")
            return {
                "status": "hard_failure",
                "capability": artifact.name,
                "error": str(re),
                "evidence": {
                    "screenshot": screenshot_path,
                    "dom_dump": dom_dump_path
                }
            }

        except Exception as e:
            return {
                "status": "hard_failure",
                "capability": artifact.name,
                "error": f"Unhandled exception: {e}"
            }
        finally:
            browser.close()
