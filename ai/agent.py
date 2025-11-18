# ai/agent.py
import json
import asyncio
import os
import logging
from typing import Dict, Any
from mcp.server import LocalMCP, list_tools
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration constants
MAX_CONVERSATION_STEPS = int(os.getenv("MAX_CONVERSATION_STEPS", "6"))
MAX_RESPONSE_LENGTH = 50000
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Enhanced system prompt with YAML generation capability
SYSTEM_PROMPT = """You are a Kubernetes SRE assistant that helps diagnose cluster issues, retrieve YAML manifests, and edit deployments.

CRITICAL: You MUST respond with ONLY valid JSON. No markdown, no explanations, ONLY JSON.

Three response formats:

1) To call a tool:
{{"tool_call": {{"name": "TOOL_NAME", "args": {{}}}}}}

2) To present data directly (pod names, lists, etc):
{{"data_response": {{"summary": "...", "items": [...], "format": "list"}}}}

3) To give final answer:
{{"final_response": {{"analysis": "...", "recommendation": "...", "kubectl": "...", "yaml": "...", "confidence": 0.9, "post_checks": [...]}}}}

Available tools: {tools}

CRITICAL PARAMETER NAMES - Use these EXACT names when calling tools:
- get_pod_logs: Use "pod_name" (accepts "pod" as alias)
- get_pod_details: Use "pod_name" (accepts "pod" as alias)
- get_pod_metrics: Use "pod_name" (accepts "pod" as alias)
- check_pod_config_references: Use "pod_name" (accepts "pod" as alias)
- test_dns_from_pod: Use "pod_name" (accepts "pod" as alias)
- test_connectivity_from_pod: Use "source_pod" (accepts "pod" as alias)

NEW YAML RETRIEVAL TOOLS:
- get_deployment_yaml(deployment_name, namespace): Get ACTUAL deployment YAML from cluster
- get_pod_yaml(pod_name, namespace): Get ACTUAL pod YAML from cluster
- get_service_yaml(service_name, namespace): Get ACTUAL service YAML from cluster

NEW EDITING TOOLS:
- patch_deployment_command(deployment_name, container_name, new_command, namespace): Update container command
- patch_deployment_replicas(deployment_name, replicas, namespace): Scale deployment

ENHANCED TROUBLESHOOTING METHODOLOGY:

**Step 1: Get Overview**
- Use get_cluster_health_summary() first for high-level cluster status

**Step 2: Diagnose by Problem Type**

A) POD ISSUES (crash, restart, OOM):
   1. get_pods() → identify failing pods
   2. get_pod_logs(pod_name="...", namespace="...") → find error messages
   3. get_pod_metrics(pod_name="...", namespace="...") → check resource usage
   4. get_cluster_events() → check OOMKilled, ImagePull failures
   5. check_pod_config_references(pod_name="...", namespace="...") → verify configs exist

B) NETWORKING ISSUES (connection refused, timeout, DNS):
   1. get_services() → verify service exists
   2. get_endpoints() → CHECK IF SERVICE HAS BACKING PODS (critical!)
   3. get_network_policies() → check for traffic blocking rules
   4. get_ingresses() → check external access configuration

C) STORAGE ISSUES (pending PVC, volume mount failures):
   1. get_persistent_volume_claims() → check PVC status
   2. get_persistent_volumes() → check PV availability

D) CONFIGURATION ISSUES (ConfigMap/Secret not found):
   1. get_configmaps() → verify ConfigMap exists
   2. get_secrets() → verify Secret exists (shows keys only)
   3. check_pod_config_references(pod_name="...", namespace="...") → find which configs are missing

E) SCHEDULING/RESOURCE ISSUES (pod pending, nodes full):
   1. get_node_details() → check node capacity and conditions
   2. get_resource_quotas() → check if quotas are maxed out

F) PERMISSION ISSUES (Forbidden, Unauthorized):
   1. check_service_account_permissions() → verify RBAC setup
   2. get_cluster_events() → look for permission denied events

**YAML RETRIEVAL vs GENERATION:**
- User asks "return/show/get YAML for existing resource" → Use get_deployment_yaml() / get_pod_yaml() / get_service_yaml()
- User asks "create/generate YAML for new resource" → Generate new YAML from scratch

**EDITING DEPLOYMENTS:**
- User asks to "fix/update/change command" → Use get_deployment_yaml() first, then patch_deployment_command()
- User asks to "scale/change replicas" → Use patch_deployment_replicas()

**DATA PRESENTATION:**
When user asks to "list pod names" or "show me the pods" or "what are the pod names":
1. Call get_pods()
2. Extract just the names from the result
3. Return using data_response format with items as a simple list

Example:
User: "list pod names from kube-system"
Step 1: {{"tool_call": {{"name": "get_pods", "args": {{"namespace": "kube-system"}}}}}}
Step 2: {{"data_response": {{"summary": "Found 12 pods in kube-system namespace", "items": ["coredns-1234", "kube-proxy-5678", ...], "format": "list"}}}}

**FIXING CRASHING PODS:**
When user asks to fix a crashing pod:
1. get_pod_logs() → identify error
2. get_deployment_yaml() → see current config
3. Analyze the issue (e.g., bad command)
4. patch_deployment_command() → fix it
5. Return success message

Example:
User: "fix the crash-demo deployment, the command is wrong"
Step 1: get_pod_logs(pod_name="crash-demo-xxx", namespace="default")
Step 2: get_deployment_yaml(deployment_name="crash-demo", namespace="default")
Step 3: Identify bad command: ["nonexistent-command"]
Step 4: patch_deployment_command(deployment_name="crash-demo", container_name="crash-container", new_command=["sh", "-c", "sleep 3600"], namespace="default")
Step 5: {{"final_response": {{"analysis": "Found issue: command 'nonexistent-command' does not exist", "recommendation": "Updated command to 'sleep 3600' - pods will restart automatically", "kubectl": "kubectl get pods -n default -w", "confidence": 0.95, "post_checks": ["Wait for new pods to become Ready", "Check logs: kubectl logs <new-pod>"]}}}}

**kubectl Command Guidelines:**
- Include namespace: -n <namespace>
- Prefer diagnostic commands: describe, logs, get, top
- Avoid destructive: delete, apply (except for generated YAML)
- Format for copy-paste: single line, executable

Remember: ONLY output JSON, nothing else."""

mcp_client = LocalMCP()


class AIAgent:
    def __init__(self, adapter):
        self.adapter = adapter
        self.tools = list_tools()
    
    def _get_system_prompt(self):
        tools_str = ", ".join(self.tools.keys())
        return SYSTEM_PROMPT.format(tools=tools_str)
    
    def _invoke_tool_sync(self, name: str, args: Dict[str, Any]):
        """Synchronous wrapper for tool invocation"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(mcp_client.invoke(name, args))
            return result
        finally:
            loop.close()
    
    def _clean_json_response(self, reply: str) -> str:
        """Clean up AI response to extract valid JSON"""
        reply = reply.strip()
        
        # Remove markdown code blocks
        if reply.startswith("```json"):
            reply = reply[7:]
        elif reply.startswith("```"):
            reply = reply[3:]
        
        if reply.endswith("```"):
            reply = reply[:-3]
        
        return reply.strip()
    
    def _handle_tool_error(self, tool_name: str, tool_args: Dict[str, Any], error: Exception, conversation_context: list) -> Dict[str, Any]:
        """Handle tool invocation errors and provide recovery hints"""
        error_msg = str(error)
        
        # Check if it's a parameter name issue
        if "missing 1 required positional argument" in error_msg:
            hint = ""
            if "pod_name" in error_msg:
                hint = f"Tool '{tool_name}' requires 'pod_name' parameter. You used: {list(tool_args.keys())}. Try using 'pod_name' instead of 'pod'."
            
            error_info = {
                "tool": tool_name,
                "args": tool_args,
                "error": f"Parameter mismatch: {error_msg}",
                "hint": hint,
                "recovery": "Retry with correct parameter names"
            }
            conversation_context.append(error_info)
            return error_info
        
        # Generic error
        error_info = {
            "tool": tool_name,
            "args": tool_args,
            "error": str(error)
        }
        conversation_context.append(error_info)
        return error_info
    
    def _format_data_response(self, resp: Dict[str, Any]) -> str:
        """Format data_response (for listing items)"""
        output = []
        
        if resp.get("summary"):
            output.append(f"## 📋 {resp['summary']}")
            output.append("")
        
        items = resp.get("items", [])
        if items:
            if resp.get("format") == "list":
                # Simple list format
                for item in items:
                    output.append(f"- {item}")
            elif resp.get("format") == "table":
                # Table format (if items are dicts)
                for item in items:
                    if isinstance(item, dict):
                        for key, value in item.items():
                            output.append(f"**{key}**: {value}")
                        output.append("")
            else:
                # Default: just list items
                for item in items:
                    output.append(f"- {item}")
        
        return "\n".join(output)
    
    def process_input(self, user_question: str, max_steps: int = MAX_CONVERSATION_STEPS):
        """Main dialog loop with the AI agent"""
        conversation_context = []
        user_msg = json.dumps({"user_question": user_question})
        
        for step in range(max_steps):
            if DEBUG:
                logger.debug(f"\n[DEBUG] Step {step + 1}/{max_steps}")
                logger.debug(f"[DEBUG] Sending to AI: {user_msg[:200]}...")
            
            # Get AI response
            try:
                reply = self.adapter.chat(self._get_system_prompt(), user_msg)
            except Exception as e:
                logger.error(f"AI adapter error: {e}")
                return f"❌ Error: Failed to get AI response: {e}"
            
            if DEBUG:
                logger.debug(f"[DEBUG] AI raw response: {reply}")
            
            # Clean up response
            reply = self._clean_json_response(reply)
            
            if DEBUG:
                logger.debug(f"[DEBUG] AI cleaned response: {reply}")
            
            # Parse JSON
            try:
                parsed = json.loads(reply)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Raw response: {reply}")
                
                # Try to provide helpful feedback
                error_msg = f"❌ Error: AI returned invalid JSON. This usually means:\n"
                error_msg += f"1. The AI model is struggling with the complex prompt\n"
                error_msg += f"2. Token limit was exceeded\n"
                error_msg += f"3. The response was truncated\n\n"
                error_msg += f"Raw response (first 500 chars):\n{reply[:500]}\n\n"
                error_msg += f"Error: {e}"
                return error_msg
            
            # Check if this is a tool call
            if "tool_call" in parsed:
                tool_info = parsed["tool_call"]
                tool_name = tool_info.get("name")
                tool_args = tool_info.get("args", {})
                
                if DEBUG:
                    logger.debug(f"[DEBUG] Tool call: {tool_name} with args {tool_args}")
                
                if tool_name not in self.tools:
                    return f"❌ Error: AI requested unknown tool '{tool_name}'. Available: {list(self.tools.keys())}"
                
                # Invoke the tool
                try:
                    result = self._invoke_tool_sync(tool_name, tool_args)
                    if DEBUG:
                        logger.debug(f"[DEBUG] Tool result: {str(result)[:200]}...")
                    
                    conversation_context.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": result
                    })
                    
                except Exception as e:
                    logger.error(f"Tool invocation error: {e}")
                    error_info = self._handle_tool_error(tool_name, tool_args, e, conversation_context)
                    
                    # Don't return error immediately - let AI try to recover
                    if DEBUG:
                        logger.debug(f"[DEBUG] Tool error handled, allowing AI to retry")
                
                # Update user message with conversation history
                user_msg = json.dumps({
                    "user_question": user_question,
                    "conversation": conversation_context
                })
            
            # Check if this is a data response (for listing items)
            elif "data_response" in parsed:
                resp = parsed["data_response"]
                return self._format_data_response(resp)
            
            # Check if this is a final response
            elif "final_response" in parsed:
                resp = parsed["final_response"]
                
                if DEBUG:
                    logger.debug(f"[DEBUG] Final response received")
                
                # Format the response nicely
                output = []
                output.append("## 🔍 Analysis")
                output.append(resp.get("analysis", "N/A"))
                output.append("\n## 💡 Recommendation")
                output.append(resp.get("recommendation", "N/A"))
                
                # Handle YAML output if present
                if resp.get("yaml"):
                    output.append("\n## 📄 Generated YAML")
                    yaml_content = resp.get("yaml", "")
                    # Unescape newlines
                    yaml_content = yaml_content.replace("\\n", "\n")
                    output.append(f"```yaml\n{yaml_content}\n```")
                
                if resp.get("kubectl"):
                    output.append("\n## 🔧 Suggested Command")
                    output.append(f"```bash\n{resp.get('kubectl')}\n```")
                
                if resp.get("post_checks"):
                    output.append("\n## ✅ Post-Checks")
                    for check in resp["post_checks"]:
                        output.append(f"- {check}")
                
                output.append(f"\n*Confidence: {resp.get('confidence', 0.0):.0%}*")
                
                return "\n".join(output)
            
            else:
                logger.error(f"Unexpected response format: {parsed}")
                return f"❌ Error: AI returned unexpected format:\n{json.dumps(parsed, indent=2)}"
        
        return f"❌ Error: Reached maximum conversation steps ({max_steps}) without a final response. The AI may be stuck in a loop or the problem is too complex for the current configuration."