from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class Locator(BaseModel):
    selector: str = Field(..., description="The selector to identify the element (e.g. CSS, text, XPath, test-id).")
    strategy: str = Field("css", description="The strategy used (e.g. 'css', 'text', 'role', 'xpath', 'accessibility').")
    reasoning: str = Field(..., description="Why this locator is robust against layout drift or legacy markup.")
    fallback_selectors: List[str] = Field(default_factory=list, description="Alternative selectors to try if primary fails.")

class Action(BaseModel):
    step_number: Optional[int] = Field(None, description="1-indexed sequence number of the action.")
    step_type: str = Field(..., description="The type of action: 'click', 'fill', 'select', 'read', 'navigate', 'wait'.")
    target: Optional[Locator] = Field(None, description="The element to act upon.")
    value: Optional[str] = Field(None, description="The value to input or select (can be parameterized like {{member_id}}).")
    extract_key: Optional[str] = Field(None, description="If step_type is 'read', the key to store the extracted data.")
    description: str = Field(..., description="Human readable description of the step.")
    is_risky: bool = Field(False, description="Flag indicating if the step performs an irreversible or sensitive operation.")
    timeout_ms: int = Field(5000, description="Step execution timeout in milliseconds.")

class Checkpoint(BaseModel):
    condition_type: str = Field(..., description="'element_visible', 'text_present', 'url_matches', 'element_text_matches'")
    target: Optional[Locator] = None
    value: Optional[str] = None
    timeout_ms: int = Field(5000, description="Verification timeout in milliseconds.")

class CapabilityInput(BaseModel):
    name: str
    type: str = "string"
    description: str
    required: bool = True
    default: Optional[str] = None
    is_sensitive: bool = False

class CapabilityOutput(BaseModel):
    name: str
    type: str = "string"
    description: str
    extract_key: Optional[str] = None

class SafetyPolicy(BaseModel):
    allowed_domains: List[str] = Field(default_factory=lambda: ["*"], description="Domain allowlist patterns.")
    allowed_actions: List[str] = Field(default_factory=lambda: ["click", "fill", "select", "read", "navigate", "wait"])
    requires_confirmation_on_risky: bool = True
    sensitive_fields: List[str] = Field(default_factory=lambda: ["ssn", "password", "pin", "card_number", "cvv"])

class BusinessOutcomeRule(BaseModel):
    name: str
    selector: str
    pattern: Optional[str] = None
    outcome_type: str = "BUSINESS_ERROR"
    description: str = "Known business outcome condition"

class CapabilityArtifact(BaseModel):
    version: str = "1.0.0"
    name: str = Field(..., description="Unique machine-readable name of the capability.")
    description: str = Field(..., description="Human and agent-readable capability description.")
    category: str = Field("core_banking", description="Operational category of the capability.")
    safety_policy: SafetyPolicy = Field(default_factory=SafetyPolicy)
    inputs: List[CapabilityInput] = Field(default_factory=list)
    outputs: List[CapabilityOutput] = Field(default_factory=list)
    steps: List[Action] = Field(default_factory=list)
    success_checkpoint: Checkpoint = Field(..., description="Condition to verify successful execution.")
    business_outcome_rules: List[BusinessOutcomeRule] = Field(default_factory=list, description="Rules to catch non-crash business outcomes.")
