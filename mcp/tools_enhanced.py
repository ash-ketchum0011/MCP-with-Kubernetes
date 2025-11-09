# mcp/tools_enhanced.py
# Additional tools for networking, storage, configuration, and advanced troubleshooting

from mcp.server import tool
from kubernetes import client, config
import base64
import subprocess
import json

# Initialize clients
v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()
networking_v1 = client.NetworkingV1Api()
storage_v1 = client.StorageV1Api()
rbac_v1 = client.RbacAuthorizationV1Api()


# ==========================================
# NETWORKING TOOLS
# ==========================================

@tool()
async def get_ingresses(namespace: str = "default"):
    """
    List all ingresses in a namespace.
    Helps diagnose external access issues.
    """
    try:
        ingresses = networking_v1.list_namespaced_ingress(namespace)
        out = []
        for ing in ingresses.items:
            rules = []
            if ing.spec.rules:
                for rule in ing.spec.rules:
                    host = rule.host or "*"
                    paths = []
                    if rule.http and rule.http.paths:
                        paths = [
                            {
                                "path": p.path,
                                "backend": f"{p.backend.service.name}:{p.backend.service.port.number if p.backend.service.port.number else p.backend.service.port.name}"
                            }
                            for p in rule.http.paths
                        ]
                    rules.append({"host": host, "paths": paths})
            
            out.append({
                "name": ing.metadata.name,
                "namespace": ing.metadata.namespace,
                "class": ing.spec.ingress_class_name,
                "rules": rules,
                "load_balancer": [lb.ip or lb.hostname for lb in (ing.status.load_balancer.ingress or [])]
            })
        return {"ingresses": out}
    except Exception as e:
        return {"error": f"failed to list ingresses: {e}"}


@tool()
async def get_endpoints(service_name: str, namespace: str = "default"):
    """
    Get endpoints for a service.
    Shows which pods are backing a service - crucial for connectivity debugging.
    
    If endpoints list is empty, service has no backing pods (major issue).
    """
    try:
        endpoints = v1.read_namespaced_endpoints(service_name, namespace)
        
        ready_addresses = []
        not_ready_addresses = []
        
        if endpoints.subsets:
            for subset in endpoints.subsets:
                # Ready endpoints
                if subset.addresses:
                    for addr in subset.addresses:
                        ready_addresses.append({
                            "ip": addr.ip,
                            "pod": addr.target_ref.name if addr.target_ref else None,
                            "node": addr.node_name
                        })
                
                # Not ready endpoints
                if subset.not_ready_addresses:
                    for addr in subset.not_ready_addresses:
                        not_ready_addresses.append({
                            "ip": addr.ip,
                            "pod": addr.target_ref.name if addr.target_ref else None,
                            "node": addr.node_name
                        })
        
        return {
            "service": service_name,
            "namespace": namespace,
            "ready_endpoints": ready_addresses,
            "not_ready_endpoints": not_ready_addresses,
            "total_ready": len(ready_addresses),
            "issue": "NO ENDPOINTS - Service has no backing pods!" if len(ready_addresses) == 0 else None
        }
    except Exception as e:
        return {"error": f"failed to get endpoints: {e}"}


@tool()
async def get_network_policies(namespace: str = "default"):
    """
    List network policies in a namespace.
    Network policies can block traffic - important for connectivity issues.
    """
    try:
        policies = networking_v1.list_namespaced_network_policy(namespace)
        out = []
        for policy in policies.items:
            pod_selector = dict(policy.spec.pod_selector.match_labels or {}) if policy.spec.pod_selector else {}
            
            ingress_rules = []
            if policy.spec.ingress:
                for rule in policy.spec.ingress:
                    ingress_rules.append({
                        "from": [str(f) for f in (rule._from or [])],
                        "ports": [{"port": p.port, "protocol": p.protocol} for p in (rule.ports or [])]
                    })
            
            egress_rules = []
            if policy.spec.egress:
                for rule in policy.spec.egress:
                    egress_rules.append({
                        "to": [str(t) for t in (rule.to or [])],
                        "ports": [{"port": p.port, "protocol": p.protocol} for p in (rule.ports or [])]
                    })
            
            out.append({
                "name": policy.metadata.name,
                "namespace": policy.metadata.namespace,
                "pod_selector": pod_selector,
                "policy_types": policy.spec.policy_types,
                "ingress_rules": ingress_rules,
                "egress_rules": egress_rules
            })
        
        return {"network_policies": out}
    except Exception as e:
        return {"error": f"failed to list network policies: {e}"}


@tool()
async def test_dns_from_pod(pod_name: str, namespace: str = "default", dns_name: str = "kubernetes.default.svc.cluster.local"):
    """
    Test DNS resolution from inside a pod.
    Uses kubectl exec to run nslookup/dig.
    
    CRITICAL for debugging "service not found" errors.
    """
    try:
        # Try to exec into pod and test DNS
        exec_command = [
            'kubectl', 'exec', '-n', namespace, pod_name, '--',
            'nslookup', dns_name
        ]
        
        result = subprocess.run(
            exec_command,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        return {
            "pod": pod_name,
            "dns_query": dns_name,
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None
        }
    except subprocess.TimeoutExpired:
        return {"error": "DNS test timed out - pod may be unresponsive"}
    except Exception as e:
        return {"error": f"failed to test DNS: {e}", "hint": "Ensure kubectl is available and pod has nslookup/dig"}


@tool()
async def test_connectivity_from_pod(
    source_pod: str,
    source_namespace: str,
    target: str,
    port: int = 80,
    timeout: int = 5
):
    """
    Test network connectivity from one pod to another service/pod.
    Uses kubectl exec to run curl/nc (netcat).
    
    Example: test if nginx pod can reach database:5432
    """
    try:
        # Try netcat first (most reliable for port testing)
        exec_command = [
            'kubectl', 'exec', '-n', source_namespace, source_pod, '--',
            'nc', '-zv', '-w', str(timeout), target, str(port)
        ]
        
        result = subprocess.run(
            exec_command,
            capture_output=True,
            text=True,
            timeout=timeout + 2
        )
        
        success = result.returncode == 0 or "succeeded" in result.stderr.lower()
        
        return {
            "source_pod": source_pod,
            "target": f"{target}:{port}",
            "connection": "SUCCESS" if success else "FAILED",
            "output": result.stdout + result.stderr,
            "diagnosis": "Network connectivity OK" if success else "Cannot reach target - check network policies, service exists, and pod is running"
        }
    except subprocess.TimeoutExpired:
        return {
            "source_pod": source_pod,
            "target": f"{target}:{port}",
            "connection": "TIMEOUT",
            "diagnosis": "Connection timed out - target may be down or network is very slow"
        }
    except Exception as e:
        return {"error": f"failed to test connectivity: {e}", "hint": "Ensure pod has nc (netcat) or curl installed"}


# ==========================================
# STORAGE TOOLS
# ==========================================

@tool()
async def get_persistent_volumes():
    """
    List all Persistent Volumes in cluster.
    Shows storage issues.
    """
    try:
        pvs = v1.list_persistent_volume()
        out = []
        for pv in pvs.items:
            out.append({
                "name": pv.metadata.name,
                "capacity": pv.spec.capacity.get("storage") if pv.spec.capacity else None,
                "access_modes": pv.spec.access_modes,
                "status": pv.status.phase,
                "claim": f"{pv.spec.claim_ref.namespace}/{pv.spec.claim_ref.name}" if pv.spec.claim_ref else "Available",
                "storage_class": pv.spec.storage_class_name
            })
        return {"persistent_volumes": out}
    except Exception as e:
        return {"error": f"failed to list PVs: {e}"}


@tool()
async def get_persistent_volume_claims(namespace: str = "default"):
    """
    List PVCs in namespace.
    If PVC is Pending, pod cannot start.
    """
    try:
        pvcs = v1.list_namespaced_persistent_volume_claim(namespace)
        out = []
        for pvc in pvcs.items:
            out.append({
                "name": pvc.metadata.name,
                "namespace": pvc.metadata.namespace,
                "status": pvc.status.phase,
                "volume": pvc.spec.volume_name,
                "capacity": pvc.status.capacity.get("storage") if pvc.status.capacity else None,
                "storage_class": pvc.spec.storage_class_name,
                "access_modes": pvc.spec.access_modes,
                "issue": "PVC is Pending - no PV available!" if pvc.status.phase == "Pending" else None
            })
        return {"pvcs": out}
    except Exception as e:
        return {"error": f"failed to list PVCs: {e}"}


# ==========================================
# CONFIGURATION TOOLS
# ==========================================

@tool()
async def get_configmaps(namespace: str = "default"):
    """
    List ConfigMaps in namespace.
    Missing ConfigMaps cause pod failures.
    """
    try:
        cms = v1.list_namespaced_config_map(namespace)
        out = []
        for cm in cms.items:
            out.append({
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "keys": list(cm.data.keys()) if cm.data else [],
                "size": len(str(cm.data)) if cm.data else 0
            })
        return {"configmaps": out}
    except Exception as e:
        return {"error": f"failed to list ConfigMaps: {e}"}


@tool()
async def get_secrets(namespace: str = "default"):
    """
    List Secrets in namespace (WITHOUT exposing values).
    Missing secrets cause pod failures.
    
    SECURITY: We only show secret names and keys, NOT the actual values.
    """
    try:
        secrets = v1.list_namespaced_secret(namespace)
        out = []
        for secret in secrets.items:
            out.append({
                "name": secret.metadata.name,
                "namespace": secret.metadata.namespace,
                "type": secret.type,
                "keys": list(secret.data.keys()) if secret.data else [],
                "note": "Values are hidden for security"
            })
        return {"secrets": out}
    except Exception as e:
        return {"error": f"failed to list Secrets: {e}"}


@tool()
async def check_pod_config_references(pod_name: str, namespace: str = "default"):
    """
    Check if a pod's ConfigMaps and Secrets actually exist.
    Critical for debugging "ConfigMap not found" errors.
    """
    try:
        pod = v1.read_namespaced_pod(pod_name, namespace)
        
        missing_configs = []
        missing_secrets = []
        
        # Check ConfigMap references
        for volume in (pod.spec.volumes or []):
            if volume.config_map:
                cm_name = volume.config_map.name
                try:
                    v1.read_namespaced_config_map(cm_name, namespace)
                except:
                    missing_configs.append(cm_name)
        
        # Check Secret references
        for volume in (pod.spec.volumes or []):
            if volume.secret:
                secret_name = volume.secret.secret_name
                try:
                    v1.read_namespaced_secret(secret_name, namespace)
                except:
                    missing_secrets.append(secret_name)
        
        # Check envFrom
        for container in pod.spec.containers:
            if container.env_from:
                for env_from in container.env_from:
                    if env_from.config_map_ref:
                        cm_name = env_from.config_map_ref.name
                        try:
                            v1.read_namespaced_config_map(cm_name, namespace)
                        except:
                            if cm_name not in missing_configs:
                                missing_configs.append(cm_name)
                    if env_from.secret_ref:
                        secret_name = env_from.secret_ref.name
                        try:
                            v1.read_namespaced_secret(secret_name, namespace)
                        except:
                            if secret_name not in missing_secrets:
                                missing_secrets.append(secret_name)
        
        return {
            "pod": pod_name,
            "missing_configmaps": missing_configs,
            "missing_secrets": missing_secrets,
            "issue": "CRITICAL: Pod references non-existent ConfigMaps/Secrets!" if (missing_configs or missing_secrets) else "All config references are valid"
        }
    except Exception as e:
        return {"error": f"failed to check config references: {e}"}


# ==========================================
# NODE & RESOURCE TOOLS
# ==========================================

@tool()
async def get_node_details(node_name: str = None):
    """
    Get detailed node information including capacity, allocatable, and conditions.
    """
    try:
        if node_name:
            nodes_list = [v1.read_node(node_name)]
        else:
            nodes_list = v1.list_node().items
        
        out = []
        for node in nodes_list:
            # Parse conditions
            conditions = {}
            for cond in (node.status.conditions or []):
                conditions[cond.type] = {
                    "status": cond.status,
                    "reason": cond.reason,
                    "message": cond.message
                }
            
            # Check for problems
            issues = []
            if conditions.get("Ready", {}).get("status") != "True":
                issues.append("Node is NOT Ready!")
            if conditions.get("MemoryPressure", {}).get("status") == "True":
                issues.append("Node has memory pressure")
            if conditions.get("DiskPressure", {}).get("status") == "True":
                issues.append("Node has disk pressure")
            if conditions.get("PIDPressure", {}).get("status") == "True":
                issues.append("Node has PID pressure (too many processes)")
            
            out.append({
                "name": node.metadata.name,
                "status": "Ready" if conditions.get("Ready", {}).get("status") == "True" else "NotReady",
                "capacity": {
                    "cpu": node.status.capacity.get("cpu"),
                    "memory": node.status.capacity.get("memory"),
                    "pods": node.status.capacity.get("pods")
                },
                "allocatable": {
                    "cpu": node.status.allocatable.get("cpu"),
                    "memory": node.status.allocatable.get("memory"),
                    "pods": node.status.allocatable.get("pods")
                },
                "conditions": conditions,
                "issues": issues if issues else None
            })
        
        return {"nodes": out}
    except Exception as e:
        return {"error": f"failed to get node details: {e}"}


@tool()
async def get_resource_quotas(namespace: str = "default"):
    """
    Check resource quotas in namespace.
    If quotas are maxed out, new pods cannot be created.
    """
    try:
        quotas = v1.list_namespaced_resource_quota(namespace)
        out = []
        for quota in quotas.items:
            hard = dict(quota.status.hard or {})
            used = dict(quota.status.used or {})
            
            at_limit = []
            for resource, limit in hard.items():
                if resource in used and used[resource] == limit:
                    at_limit.append(resource)
            
            out.append({
                "name": quota.metadata.name,
                "namespace": quota.metadata.namespace,
                "hard_limits": hard,
                "current_usage": used,
                "resources_at_limit": at_limit,
                "issue": f"QUOTA EXCEEDED for: {', '.join(at_limit)}" if at_limit else None
            })
        
        return {"resource_quotas": out}
    except Exception as e:
        return {"error": f"failed to get resource quotas: {e}"}


# ==========================================
# RBAC TOOLS
# ==========================================

@tool()
async def check_service_account_permissions(service_account: str, namespace: str = "default"):
    """
    Check what permissions a ServiceAccount has.
    Useful for debugging "Forbidden" errors.
    """
    try:
        # Get RoleBindings in namespace
        role_bindings = rbac_v1.list_namespaced_role_binding(namespace)
        cluster_role_bindings = rbac_v1.list_cluster_role_binding()
        
        roles_bound = []
        
        # Check namespace RoleBindings
        for rb in role_bindings.items:
            if rb.subjects:
                for subject in rb.subjects:
                    if subject.kind == "ServiceAccount" and subject.name == service_account:
                        roles_bound.append({
                            "type": "Role",
                            "name": rb.role_ref.name,
                            "namespace": namespace
                        })
        
        # Check ClusterRoleBindings
        for crb in cluster_role_bindings.items:
            if crb.subjects:
                for subject in crb.subjects:
                    if subject.kind == "ServiceAccount" and subject.name == service_account and subject.namespace == namespace:
                        roles_bound.append({
                            "type": "ClusterRole",
                            "name": crb.role_ref.name,
                            "scope": "cluster-wide"
                        })
        
        return {
            "service_account": service_account,
            "namespace": namespace,
            "roles_bound": roles_bound,
            "has_permissions": len(roles_bound) > 0,
            "issue": "ServiceAccount has NO roles bound - likely permission denied errors" if len(roles_bound) == 0 else None
        }
    except Exception as e:
        return {"error": f"failed to check permissions: {e}"}


# ==========================================
# SUMMARY TOOLS
# ==========================================

@tool()
async def get_cluster_health_summary():
    """
    Get a high-level health summary of the entire cluster.
    Good starting point for "what's wrong with my cluster?"
    """
    try:
        # Get nodes
        nodes = v1.list_node()
        nodes_ready = sum(1 for n in nodes.items if any(c.type == "Ready" and c.status == "True" for c in (n.status.conditions or [])))
        nodes_total = len(nodes.items)
        
        # Get all pods
        all_pods = v1.list_pod_for_all_namespaces()
        pods_running = sum(1 for p in all_pods.items if p.status.phase == "Running")
        pods_failed = sum(1 for p in all_pods.items if p.status.phase == "Failed")
        pods_pending = sum(1 for p in all_pods.items if p.status.phase == "Pending")
        pods_total = len(all_pods.items)
        
        # Get events (last 100)
        events = v1.list_event_for_all_namespaces()
        warning_events = sum(1 for e in events.items if e.type == "Warning")
        
        # Identify issues
        issues = []
        if nodes_ready < nodes_total:
            issues.append(f"{nodes_total - nodes_ready} node(s) not ready")
        if pods_failed > 0:
            issues.append(f"{pods_failed} pod(s) in Failed state")
        if pods_pending > 5:
            issues.append(f"{pods_pending} pod(s) stuck in Pending")
        if warning_events > 20:
            issues.append(f"{warning_events} Warning events recently")
        
        return {
            "cluster_health": "HEALTHY" if len(issues) == 0 else "DEGRADED",
            "nodes": {
                "ready": nodes_ready,
                "total": nodes_total
            },
            "pods": {
                "running": pods_running,
                "failed": pods_failed,
                "pending": pods_pending,
                "total": pods_total
            },
            "recent_warnings": warning_events,
            "issues": issues if issues else ["No major issues detected"]
        }
    except Exception as e:
        return {"error": f"failed to get cluster health: {e}"}