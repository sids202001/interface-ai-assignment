import re
from typing import Dict, Any, List
from urllib.parse import urlparse
from artifact import Action, SafetyPolicy

class PolicyViolationError(Exception):
    """Raised when an automation action violates safety constraints."""
    pass

def is_domain_allowed(target_url: str, allowed_patterns: List[str]) -> bool:
    """Verifies target URL matches the configured domain allowlist."""
    if not allowed_patterns or "*" in allowed_patterns:
        return True
    
    parsed = urlparse(target_url)
    hostname = parsed.hostname or ""
    
    if target_url.startswith("file://"):
        return True # Local test files
        
    for pattern in allowed_patterns:
        if pattern == "*" or pattern == hostname:
            return True
        if pattern.startswith("*.") and hostname.endswith(pattern[1:]):
            return True
    return False

def validate_action_safety(action: Action, policy: SafetyPolicy, current_url: str):
    """Validates an action against safety and domain policies."""
    # 1. Action type validation
    if action.step_type not in policy.allowed_actions:
        raise PolicyViolationError(
            f"Action '{action.step_type}' is forbidden by safety policy. Allowed: {policy.allowed_actions}"
        )
    
    # 2. Domain check on navigate
    if action.step_type == "navigate" and action.value:
        if not is_domain_allowed(action.value, policy.allowed_domains):
            raise PolicyViolationError(
                f"Navigation to '{action.value}' violates domain allowlist ({policy.allowed_domains})"
            )

def detect_irreversible_action(action: Action) -> bool:
    """Detects if an action performs an irreversible or sensitive financial transaction."""
    if action.is_risky:
        return True
    
    risky_keywords = ["confirm", "submit", "transfer", "issue", "delete", "revoke", "wire", "finalize"]
    desc_lower = (action.description or "").lower()
    target_selector = (action.target.selector if action.target else "").lower()
    
    for kw in risky_keywords:
        if kw in desc_lower or kw in target_selector:
            return True
    return False

def redact_sensitive_payload(data: Any, sensitive_keys: List[str] = None) -> Any:
    """Recursively redacts sensitive PII / credential values from logs and outputs."""
    default_sensitive = {"password", "pin", "ssn", "secret", "token", "cvv", "card_number", "auth"}
    keys_to_redact = set(sensitive_keys or []).union(default_sensitive)
    
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if any(sens in k.lower() for sens in keys_to_redact):
                redacted[k] = "[REDACTED_PII]"
            else:
                redacted[k] = redact_sensitive_payload(v, sensitive_keys)
        return redacted
    elif isinstance(data, list):
        return [redact_sensitive_payload(item, sensitive_keys) for item in data]
    elif isinstance(data, str):
        # SSN pattern mask (###-##-####)
        redacted_str = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '***-**-****', data)
        return redacted_str
    return data
