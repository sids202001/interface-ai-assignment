"""
Auto-generated standalone Playwright test script for capability: open_savings_sub_account
Description: Looks up a banking member and opens a new High-Yield Savings sub-account, returning the provisioned account ID.
Generated from: artifact.json
"""
import sys
from playwright.sync_api import sync_playwright

def run_flow(url: str, inputs: dict):
    print("Starting automated execution of open_savings_sub_account...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        outputs = {}

        # Step 1: Fill #member-id with '12345'
        page.fill("#member-id", inputs.get("member_id", ""), timeout=5000)
        page.wait_for_timeout(350)

        # Step 2: Click on #search-btn
        page.click("#search-btn", timeout=5000)
        page.wait_for_timeout(350)

        # Step 3: Click on #open-sub-btn
        page.click("#open-sub-btn", timeout=5000)
        page.wait_for_timeout(350)

        # Step 4: Select #account-type with 'savings'
        page.select_option("#account-type", "savings", timeout=5000)
        page.wait_for_timeout(350)

        # Step 5: Click on #submit-sub-btn
        page.click("#submit-sub-btn", timeout=5000)
        page.wait_for_timeout(350)

        # Step 6: Read on #new-acct-id
        outputs["new_account_id"] = page.inner_text("#new-acct-id", timeout=5000).strip()
        page.wait_for_timeout(350)

        # Success Checkpoint Verification
        assert page.is_visible("#success-page", timeout=5000), "Checkpoint element not visible"
        print("✅ Execution completed successfully. Outputs:", outputs)
        browser.close()
        return outputs

if __name__ == "__main__":
    import sys, json
    target_url = sys.argv[1] if len(sys.argv) > 1 else "file:///Users/siddheshsawant/interface-ai-assignment/demo_site/index.html"
    test_inputs = {"member_id": "12345"}
    run_flow(target_url, test_inputs)