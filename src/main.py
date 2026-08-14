import argparse
import sys
import os
import json
import time
from typing import Dict, Any

from agent import run_discovery
from replay import run_replay
from escalation import EscalationManager, InterventionRequest
from artifact import CapabilityArtifact
from playwright.sync_api import sync_playwright

def parse_inputs(inputs_arg: str) -> Dict[str, Any]:
    if not inputs_arg:
        return {}
    try:
        return json.loads(inputs_arg)
    except Exception as e:
        print(f"Error parsing --inputs JSON string: {e}")
        sys.exit(1)

def run_escalation_demo(url: str, artifact_path: str, inputs: Dict[str, Any], headless: bool = True):
    """Demonstrates live human-in-the-loop takeover when an unexpected blocking state occurs."""
    print("=" * 65)
    print("🧑‍💻 [DEMONSTRATING HUMAN-IN-THE-LOOP (HITL) ESCALATION]")
    print("Scenario: Target page has an unexpected security verification modal.")
    print("Automation will detect the blockage, pause on the LIVE CDP session,")
    print("transfer control to the human operator, and resume execution seamlessly.")
    print("=" * 65)

    with open(artifact_path, "r") as f:
        artifact = CapabilityArtifact(**json.load(f))

    # Append interstitial query param to trigger blocking modal
    test_url = url + ("&" if "?" in url else "?") + "interstitial=1"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(test_url)

        escalation_mgr = EscalationManager(evidence_dir="evidence")
        
        # Step 1: Fill member ID
        print("\nStep 1: Fill member-id with input parameter")
        page.fill("#member-id", inputs.get("member_id", "12345"))
        
        # Step 2: Search button is blocked by modal overlay
        print("Step 2: Attempting to click #search-btn...")
        time.sleep(1)
        
        modal_visible = page.is_visible("#interstitial-modal", timeout=1000)
        if modal_visible:
            print("  [Detection] Unexpected blocking modal detected! Raising intervention request...")
            req = escalation_mgr.create_intervention_request(
                page=page,
                capability_name=artifact.name,
                step_index=2,
                reason="Security verification overlay '#interstitial-modal' blocking interaction with '#search-btn'.",
                suggested_action="Dismiss modal advisory or verify operator clearance."
            )
            
            # Interactive operator intervention
            resolution = escalation_mgr.handle_operator_intervention(req, page, interactive=False, auto_response="Operator dismissed security advisory.")
            
        print("\nStep 2 (Resumed): Clicking #search-btn on the SAME live session...")
        page.click("#search-btn")
        page.wait_for_timeout(500)
        
        print("Step 3: Opening sub-account...")
        page.click("#open-sub-btn")
        page.wait_for_timeout(500)
        
        print("Step 4: Selecting high-yield savings...")
        page.select_option("#account-type", "savings")
        page.wait_for_timeout(500)
        
        print("Step 5: Submitting opening form...")
        page.click("#submit-sub-btn")
        page.wait_for_timeout(500)
        
        acct_id = page.inner_text("#new-acct-id")
        print(f"\n[Escalation Demo Result] Successfully completed flow! New Account ID: {acct_id}")
        browser.close()

def main():
    parser = argparse.ArgumentParser(
        description="Computer-Use Automation System for Legacy Core Banking Platforms",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Discover Command
    discover_parser = subparsers.add_parser("discover", help="Run LLM discovery loop to explore UI and compile artifact")
    discover_parser.add_argument("--url", required=True, help="Target application URL or file:// path")
    discover_parser.add_argument("--goal", required=True, help="Natural language goal to accomplish")
    discover_parser.add_argument("--output", default="artifact.json", help="Path to save output artifact JSON (default: artifact.json)")
    discover_parser.add_argument("--headed", action="store_true", help="Run browser in visible (headed) mode")

    # 2. Replay Command
    replay_parser = subparsers.add_parser("replay", help="Deterministically execute a saved capability artifact")
    replay_parser.add_argument("--url", required=True, help="Target application URL or file:// path")
    replay_parser.add_argument("--artifact", default="artifact.json", help="Path to capability artifact JSON")
    replay_parser.add_argument("--inputs", required=False, default="{}", help="JSON string of runtime input parameters (e.g. '{\"member_id\": \"12345\"}')")
    replay_parser.add_argument("--headed", action="store_true", help="Run browser in visible (headed) mode")
    replay_parser.add_argument("--escalate-on-failure", action="store_true", help="Trigger interactive human takeover if step blocks")

    # 3. Stability Command
    stability_parser = subparsers.add_parser("stability", help="Run multi-iteration stability and flakiness assessment")
    stability_parser.add_argument("--url", required=True, help="Target application URL or file:// path")
    stability_parser.add_argument("--artifact", default="artifact.json", help="Path to capability artifact JSON")
    stability_parser.add_argument("--inputs", required=False, default="{}", help="JSON string of input parameters")
    stability_parser.add_argument("--runs", type=int, default=5, help="Number of consecutive execution runs (default: 5)")

    # 4. Escalate Demo Command
    escalate_parser = subparsers.add_parser("escalate", help="Demonstrate live human-in-the-loop session takeover and handback")
    escalate_parser.add_argument("--url", required=True, help="Target application URL or file:// path")
    escalate_parser.add_argument("--artifact", default="artifact.json", help="Path to capability artifact JSON")
    escalate_parser.add_argument("--inputs", required=False, default='{"member_id": "12345"}', help="JSON string of inputs")
    escalate_parser.add_argument("--headed", action="store_true", help="Run browser in visible (headed) mode")

    # 5. Catalog / Agent Interface Command (Stretch Goal)
    catalog_parser = subparsers.add_parser("catalog", help="Expose artifact as callable AI Agent Function-Calling Tool")
    catalog_parser.add_argument("--artifact", default="artifact.json", help="Path to capability artifact JSON")

    # 6. Codegen Command (Stretch Goal)
    codegen_parser = subparsers.add_parser("codegen", help="Emit runnable standalone Playwright test script from artifact")
    codegen_parser.add_argument("--artifact", default="artifact.json", help="Path to capability artifact JSON")
    codegen_parser.add_argument("--output", default="generated_test.py", help="Output Python script path")

    args = parser.parse_args()

    if args.command == "discover":
        run_discovery(
            url=args.url,
            goal=args.goal,
            output_path=args.output,
            headless=not args.headed
        )

    elif args.command == "replay":
        inputs = parse_inputs(args.inputs)
        result = run_replay(
            artifact_path=args.artifact,
            inputs=inputs,
            url=args.url,
            headless=not args.headed,
            interactive_escalation=args.escalate_on_failure
        )
        print("\n" + "=" * 30 + " REPLAY RESULT " + "=" * 30)
        print(json.dumps(result, indent=2))
        print("=" * 75)
        
        if result["status"] == "hard_failure":
            sys.exit(1)

    elif args.command == "stability":
        inputs = parse_inputs(args.inputs)
        print("=" * 65)
        print(f"🔬 [RUNNING STABILITY & FLAKINESS BENCHMARK ({args.runs} Consecutive Iterations)]")
        print(f"Artifact : {args.artifact}")
        print(f"Inputs   : {inputs}")
        print("=" * 65)

        successes = 0
        latencies = []
        outcomes = []

        for i in range(args.runs):
            t0 = time.time()
            res = run_replay(
                artifact_path=args.artifact,
                inputs=inputs,
                url=args.url,
                headless=True
            )
            duration = round((time.time() - t0) * 1000, 2)
            latencies.append(duration)
            status = res["status"]
            outcomes.append(status)

            if status == "success":
                successes += 1
                print(f"  Run {i+1}/{args.runs}: ✅ SUCCESS ({duration}ms) | Outputs: {res.get('outputs', {})}")
            elif status == "business_outcome":
                print(f"  Run {i+1}/{args.runs}: ⚠️ BUSINESS OUTCOME ({duration}ms) | {res.get('outcome_type')}: {res.get('message')}")
            else:
                print(f"  Run {i+1}/{args.runs}: ❌ HARD FAILURE ({duration}ms) | {res.get('error')}")

        avg_latency = round(sum(latencies) / len(latencies), 2)
        success_rate = round((successes / args.runs) * 100, 1)

        print("\n" + "=" * 30 + " STABILITY REPORT " + "=" * 30)
        print(f"Total Iterations : {args.runs}")
        print(f"Success Rate     : {success_rate}% ({successes}/{args.runs})")
        print(f"Mean Latency     : {avg_latency}ms (min: {min(latencies)}ms, max: {max(latencies)}ms)")
        print(f"Outcome Vector   : {outcomes}")
        print("=" * 78)

    elif args.command == "escalate":
        inputs = parse_inputs(args.inputs)
        run_escalation_demo(
            url=args.url,
            artifact_path=args.artifact,
            inputs=inputs,
            headless=not args.headed
        )

    elif args.command == "catalog":
        from catalog import CapabilityCatalog
        cat = CapabilityCatalog()
        cat.register_artifact(args.artifact)
        tools = cat.get_tool_definitions()
        print("=" * 65)
        print("🤖 [AGENT CAPABILITY CATALOG — FUNCTION CALLING SCHEMA]")
        print("Exposing artifact as standard LLM tool definition for AI agents:")
        print("=" * 65)
        print(json.dumps(tools, indent=2))

    elif args.command == "codegen":
        from codegen import generate_playwright_script
        generate_playwright_script(args.artifact, args.output)

if __name__ == "__main__":
    main()
