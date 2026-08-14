import json
from typing import Dict, Any, List
from artifact import CapabilityArtifact
from replay import run_replay

class CapabilityCatalog:
    """
    Exposes saved capability artifacts as a catalog of callable tools/functions
    for AI agents (compatible with OpenAI / LiteLLM / Anthropic tool calling).
    """
    def __init__(self):
        self._capabilities: Dict[str, CapabilityArtifact] = {}
        self._artifact_paths: Dict[str, str] = {}

    def register_artifact(self, artifact_path: str) -> CapabilityArtifact:
        with open(artifact_path, "r") as f:
            data = json.load(f)
        artifact = CapabilityArtifact(**data)
        self._capabilities[artifact.name] = artifact
        self._artifact_paths[artifact.name] = artifact_path
        return artifact

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Exports registered capabilities as standard OpenAI Function Calling tool schemas."""
        tools = []
        for name, art in self._capabilities.items():
            properties = {}
            required = []
            for inp in art.inputs:
                properties[inp.name] = {
                    "type": inp.type,
                    "description": inp.description
                }
                if inp.required:
                    required.append(inp.name)

            tool_schema = {
                "type": "function",
                "function": {
                    "name": art.name,
                    "description": art.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            }
            tools.append(tool_schema)
        return tools

    def invoke_tool(self, capability_name: str, arguments: Dict[str, Any], url: str) -> Dict[str, Any]:
        """Invokes a capability directly using arguments passed from an AI agent's tool call."""
        if capability_name not in self._capabilities:
            return {"status": "error", "message": f"Capability '{capability_name}' not found in catalog."}
        
        artifact_path = self._artifact_paths[capability_name]
        return run_replay(artifact_path, arguments, url)
