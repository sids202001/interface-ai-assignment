import json
from artifact import CapabilityArtifact

def generate_playwright_script(artifact_path: str, output_path: str):
    """
    Generates a standalone, runnable Python Playwright test file from a CapabilityArtifact.
    (Optional Stretch Goal: Code Generation).
    """
    with open(artifact_path, "r") as f:
        data = json.load(f)
    artifact = CapabilityArtifact(**data)

    code_lines = [
        '"""',
        f'Auto-generated standalone Playwright test script for capability: {artifact.name}',
        f'Description: {artifact.description}',
        f'Generated from: {artifact_path}',
        '"""',
        'import sys',
        'from playwright.sync_api import sync_playwright',
        '',
        f'def run_flow(url: str, inputs: dict):',
        f'    print("Starting automated execution of {artifact.name}...")',
        '    with sync_playwright() as p:',
        '        browser = p.chromium.launch(headless=True)',
        '        page = browser.new_page()',
        '        page.goto(url)',
        '        outputs = {}',
        ''
    ]

    for i, step in enumerate(artifact.steps):
        code_lines.append(f'        # Step {i+1}: {step.description}')
        val_str = step.value or ""
        selector = step.target.selector if step.target else ""
        
        if "{{" in val_str:
            # Param replacement
            for inp in artifact.inputs:
                if f"{{{{{inp.name}}}}}" in val_str:
                    val_str = f'inputs.get("{inp.name}", "")'
                    break
        else:
            val_str = f'"{val_str}"'

        if step.step_type == "fill":
            code_lines.append(f'        page.fill("{selector}", {val_str}, timeout={step.timeout_ms or 5000})')
        elif step.step_type == "click":
            code_lines.append(f'        page.click("{selector}", timeout={step.timeout_ms or 5000})')
        elif step.step_type == "select":
            code_lines.append(f'        page.select_option("{selector}", {val_str}, timeout={step.timeout_ms or 5000})')
        elif step.step_type == "read":
            code_lines.append(f'        outputs["{step.extract_key}"] = page.inner_text("{selector}", timeout={step.timeout_ms or 5000}).strip()')
        elif step.step_type == "navigate":
            code_lines.append(f'        page.goto({val_str})')
        
        code_lines.append('        page.wait_for_timeout(350)')
        code_lines.append('')

    # Checkpoint
    cp = artifact.success_checkpoint
    code_lines.append('        # Success Checkpoint Verification')
    if cp.condition_type == "element_visible" and cp.target:
        code_lines.append(f'        assert page.is_visible("{cp.target.selector}", timeout={cp.timeout_ms or 5000}), "Checkpoint element not visible"')
    elif cp.condition_type == "text_present" and cp.value:
        code_lines.append(f'        assert page.get_by_text("{cp.value}").is_visible(timeout={cp.timeout_ms or 5000}), "Checkpoint text missing"')

    code_lines.extend([
        '        print("✅ Execution completed successfully. Outputs:", outputs)',
        '        browser.close()',
        '        return outputs',
        '',
        'if __name__ == "__main__":',
        '    import sys, json',
        '    target_url = sys.argv[1] if len(sys.argv) > 1 else "file:///Users/siddheshsawant/interface-ai-assignment/demo_site/index.html"',
        '    test_inputs = {"member_id": "12345"}',
        '    run_flow(target_url, test_inputs)'
    ])

    generated_code = "\n".join(code_lines)
    with open(output_path, "w") as out:
        out.write(generated_code)
    print(f"Generated standalone Playwright test script saved to: {output_path}")
