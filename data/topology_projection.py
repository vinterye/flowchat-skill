"""Build a fact-preserving topology projection for the Flowchat data layer.

This module deliberately does not know anything about the Level 1 UI.  It reads
the five registry/runtime sources, keeps source status and location contracts,
and emits one projection with separate registry and runtime namespaces.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = "topology-projection/v1"
INVERSE_RELATIONS = {
    "governs": "governed_by",
    "governed_by": "governs",
    "handoff": "receives",
    "receives": "handoff",
    "supply": "supplied_by",
    "supplied_by": "supply",
    "calls": "called_by",
    "called_by": "calls",
    "contains": "contained_by",
    "contained_by": "contains",
    "precheck": "prechecked_by",
    "prechecked_by": "precheck",
    "registration": "registered_by",
    "registered_by": "registration",
    "rule_dependency": "used_by",
    "used_by": "rule_dependency",
}
FORBIDDEN_UI_IDS = {
    "rules-protocol",
    "human-gate",
    "harness-registry",
    "artifact-lineage",
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _ref(source_id: str, pointer: str) -> dict[str, str]:
    return {"source_id": source_id, "pointer": pointer}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}:{sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    return list(value)


def _label(record: Mapping[str, Any], fallback: str) -> str:
    for key in ("name_zh", "name", "title", "label", "asset_id", "id", "node_id"):
        value = record.get(key)
        if value not in (None, "", "Unknown"):
            return str(value)
    return fallback


def _status(record: Mapping[str, Any], fallback: str = "Unknown") -> str:
    value = record.get("status", fallback)
    return fallback if value in (None, "") else str(value)


class ProjectionBuilder:
    def __init__(self, source_paths: Mapping[str, Path]):
        self.source_paths = dict(source_paths)
        self.sources: list[dict[str, Any]] = []
        self.source_ids: dict[str, str] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}
        self.stage_bindings: dict[str, dict[str, Any]] = {}
        self.conflicts: list[dict[str, Any]] = []
        self._relation_records: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._agent_ids: set[str] = set()
        self._capability_ids: set[str] = set()
        self._stage_ids: set[str] = set()
        self.runtime_overlay: dict[str, Any] = {
            "source_refs": [],
            "selected_run": None,
            "projects": [],
            "stage_bindings": [],
        }

    def _source(self, source_id: str, path: Path, role: str) -> dict[str, Any]:
        item = {
            "source_id": source_id,
            "path": str(path),
            "sha256": _sha(path),
            "role": role,
            "status": "read",
        }
        self.sources.append(item)
        self.source_ids[source_id] = source_id
        return item

    def add_node(
        self,
        node_id: str,
        kind: str,
        record: Mapping[str, Any],
        source_id: str,
        pointer: str,
        *,
        status: str | None = None,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        location: Any = None,
        evidence_refs: Iterable[Any] = (),
    ) -> None:
        if node_id in FORBIDDEN_UI_IDS:
            self.conflicts.append({
                "type": "forbidden_ui_object_suppressed",
                "id": node_id,
                "source_ref": _ref(source_id, pointer),
                "reason": "projection never creates UI business objects without a fact-source record",
            })
            return
        source_ref = _ref(source_id, pointer)
        evidence = _as_list(evidence_refs)
        existing = self.nodes.get(node_id)
        if existing is None:
            existing = {
                "id": node_id,
                "kind": kind,
                "label": label or _label(record, node_id),
                "status": status if status is not None else _status(record),
                "source_kind": source_id,
                "source_refs": [source_ref],
                "evidence_refs": evidence,
                "metadata": dict(metadata or {}),
            }
            if location is not None:
                existing["location"] = location
            self.nodes[node_id] = existing
            return
        existing["source_refs"] = _unique(existing.get("source_refs", []) + [source_ref])
        existing["evidence_refs"] = _unique(existing.get("evidence_refs", []) + evidence)
        if location is not None and "location" not in existing:
            existing["location"] = location
        if metadata:
            existing["metadata"] = {**existing.get("metadata", {}), **dict(metadata)}
        # Relationship Registry repeats the same subjects without a domain
        # kind. That is source overlap, not a semantic kind conflict.
        if existing.get("kind") != kind and "relationship_subject" not in {existing.get("kind"), kind}:
            self.conflicts.append({
                "type": "node_kind_collision",
                "id": node_id,
                "kinds": sorted({existing.get("kind"), kind}),
                "source_refs": existing["source_refs"],
            })

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        relation: str,
        record: Mapping[str, Any],
        source_id: str,
        pointer: str,
        *,
        status: str | None = None,
        evidence_refs: Iterable[Any] = (),
        canonicalize: bool = True,
    ) -> None:
        if not from_id or not to_id or from_id == "Unknown" or to_id == "Unknown":
            return
        inverse = INVERSE_RELATIONS.get(relation)
        if canonicalize:
            pair = tuple(sorted((from_id, to_id)))
            relation_family = tuple(sorted((relation, inverse))) if inverse else (relation,)
            key = _stable_id("edge", *pair, *relation_family)
        else:
            key = _stable_id("edge", from_id, to_id, relation, source_id, pointer)
        raw = {
            "id": record.get("id") or record.get("edge_id") or _stable_id("raw-edge", source_id, pointer),
            "from": from_id,
            "to": to_id,
            "relation": relation,
            "status": status if status is not None else _status(record),
            "source_ref": _ref(source_id, pointer),
            "evidence_refs": _as_list(evidence_refs) or _as_list(record.get("evidence") or record.get("evidence_refs")),
            "record": dict(record),
        }
        if key not in self.edges:
            self.edges[key] = {
                "id": key,
                "from": from_id,
                "to": to_id,
                "relation": relation,
                "canonical_key": key,
                "status": raw["status"],
                "source_refs": [raw["source_ref"]],
                "evidence_refs": raw["evidence_refs"],
                "directions": [raw],
            }
        else:
            edge = self.edges[key]
            edge["source_refs"] = _unique(edge["source_refs"] + [raw["source_ref"]])
            edge["evidence_refs"] = _unique(edge["evidence_refs"] + raw["evidence_refs"])
            edge["directions"].append(raw)
            if raw["relation"] != edge["relation"] and raw["relation"] != INVERSE_RELATIONS.get(edge["relation"]):
                self.conflicts.append({
                    "type": "relationship_relation_conflict",
                    "canonical_edge_id": key,
                    "relations": sorted({edge["relation"], raw["relation"]}),
                    "source_refs": edge["source_refs"],
                })
        self._relation_records[(from_id, to_id)].append(raw)

    def add_group(self, group_id: str, kind: str, member_ids: Iterable[str], source_id: str, pointer: str, **extra: Any) -> None:
        members = [item for item in member_ids if item and item != "Unknown"]
        if not members:
            return
        group = self.groups.setdefault(group_id, {
            "id": group_id,
            "kind": kind,
            "member_ids": [],
            "source_refs": [],
        })
        group["member_ids"] = _unique(group["member_ids"] + members)
        group["source_refs"] = _unique(group["source_refs"] + [_ref(source_id, pointer)])
        group.update({k: v for k, v in extra.items() if v is not None})

    def add_stage_binding(
        self,
        stage_id: str,
        target_ids: Iterable[str],
        source_id: str,
        pointer: str,
        *,
        binding_kind: str,
        status: str,
        evidence_refs: Iterable[Any] = (),
        source_node_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not stage_id or stage_id in {"Unknown", "unknown", ""}:
            return
        targets = sorted({item for item in target_ids if item and item not in {"Unknown", "automatic"}})
        if not targets:
            return
        key = _stable_id("stage-binding", stage_id, binding_kind, *targets)
        binding = self.stage_bindings.setdefault(key, {
            "id": key,
            "stage_id": stage_id,
            "target_ids": [],
            "binding_kind": binding_kind,
            "status": status,
            "source_refs": [],
            "evidence_refs": [],
            "statuses": [],
        })
        binding["target_ids"] = _unique(binding["target_ids"] + targets)
        binding["source_refs"] = _unique(binding["source_refs"] + [_ref(source_id, pointer)])
        binding["evidence_refs"] = _unique(binding["evidence_refs"] + _as_list(evidence_refs))
        binding["statuses"] = _unique(binding["statuses"] + [status])
        if source_node_id:
            binding["source_node_ids"] = _unique(binding.get("source_node_ids", []) + [source_node_id])
        if metadata:
            binding["metadata"] = {**binding.get("metadata", {}), **dict(metadata)}
        self._stage_ids.add(stage_id)

    def build(self) -> dict[str, Any]:
        agents_path = self.source_paths["agent_registry"]
        caps_path = self.source_paths["capability_registry"]
        rels_path = self.source_paths["relationship_registry"]
        flow_path = self.source_paths["flow_registry"]
        runtime_path = self.source_paths["runtime"]

        self._build_agents(agents_path)
        self._build_capabilities(caps_path)
        self._build_relationships(rels_path)
        self._build_flow(flow_path)
        self._build_runtime(runtime_path)
        self._detect_cross_registry_conflicts()

        return {
            "schema": SCHEMA,
            "nodes": sorted(self.nodes.values(), key=lambda item: item["id"]),
            "edges": sorted(self.edges.values(), key=lambda item: item["id"]),
            "groups": sorted(self.groups.values(), key=lambda item: item["id"]),
            "stageBindings": sorted(self.stage_bindings.values(), key=lambda item: item["id"]),
            "runtimeOverlay": self.runtime_overlay,
            "conflicts": self.conflicts,
            "sources": self.sources,
        }

    def _build_agents(self, path: Path) -> None:
        source = self._source("agent_registry", path, "authoritative Agent Registry")
        data = _json(path)
        for index, agent in enumerate(data.get("agents", [])):
            agent_id = str(agent.get("id"))
            self._agent_ids.add(agent_id)
            metadata = {
                key: agent.get(key)
                for key in ("type", "version", "path", "entrypoint", "decision_gateway", "usage_card", "runtime_gate", "test_pack_id")
                if key in agent
            }
            self.add_node(agent_id, "agent", agent, source["source_id"], f"#/agents/{index}", metadata=metadata,
                          location=agent.get("location"), evidence_refs=agent.get("evidence_refs", []))

    def _build_capabilities(self, path: Path) -> None:
        source = self._source("capability_registry", path, "authoritative Capability Registry")
        data = _json(path)
        for index, agent_caps in enumerate(data.get("agents", [])):
            owner = str(agent_caps.get("agent_id"))
            for c_index, capability in enumerate(agent_caps.get("capabilities", [])):
                capability_id = f"capability:{owner}:{capability.get('id')}"
                self._capability_ids.add(capability_id)
                metadata = {key: capability.get(key) for key in ("input", "output", "trigger", "constraints") if key in capability}
                self.add_node(capability_id, "capability", capability, source["source_id"], f"#/agents/{index}/capabilities/{c_index}",
                              status=agent_caps.get("status"), metadata={"agent_id": owner, **metadata})
                self.add_edge(owner, capability_id, "provides_capability", {"agent_id": owner, "capability_id": capability.get("id")},
                              source["source_id"], f"#/agents/{index}/capabilities/{c_index}", status=agent_caps.get("status"), canonicalize=False)

    def _build_relationships(self, path: Path) -> None:
        source = self._source("relationship_registry", path, "authoritative Relationship Registry")
        data = _json(path)
        for index, node in enumerate(data.get("nodes", [])):
            node_id = str(node.get("id"))
            self.add_node(node_id, str(node.get("type") or "relationship_subject"), node, source["source_id"], f"#/nodes/{index}",
                          metadata={k: node.get(k) for k in ("name", "status", "path") if k in node}, location=node.get("location"))
        for index, edge in enumerate(data.get("edges", [])):
            self.add_edge(str(edge.get("from")), str(edge.get("to")), str(edge.get("type")), edge, source["source_id"], f"#/edges/{index}",
                          status=edge.get("status"), evidence_refs=[edge.get("evidence")] if edge.get("evidence") else [])

    def _build_flow(self, path: Path) -> None:
        source = self._source("flow_registry", path, "candidate Flow Registry projection")
        data = _json(path)
        if data.get("status") != "candidate_projection":
            self.conflicts.append({"type": "flow_registry_status_unexpected", "status": data.get("status"), "source_ref": _ref(source["source_id"], "#/status")})
        hierarchy = data.get("hierarchy", {})
        hierarchy_nodes = hierarchy.get("nodes", [])
        hierarchy_by_id: dict[str, Mapping[str, Any]] = {}
        for index, node in enumerate(hierarchy_nodes):
            node_id = str(node.get("node_id") or node.get("id"))
            hierarchy_by_id[node_id] = node
            self.add_node(node_id, str(node.get("kind") or node.get("type") or "flow_node"), node, source["source_id"],
                          f"#/hierarchy/nodes/{index}", status=node.get("status"), label=node.get("title") or node.get("name_zh"),
                          metadata={k: node.get(k) for k in ("parent_id", "relation_source", "confidence", "independent_invocation") if k in node},
                          location=node.get("location"), evidence_refs=node.get("evidence_refs", []))
            if node.get("parent_id") and node.get("parent_id") in hierarchy_by_id:
                self.add_group(f"group:hierarchy:{node.get('parent_id')}", "hierarchy", [node_id], source["source_id"],
                               f"#/hierarchy/nodes/{index}/parent_id", parent_id=node.get("parent_id"), status=data.get("status"))
        for index, link in enumerate(hierarchy.get("links", [])):
            self.add_edge(str(link.get("from")), str(link.get("to")), str(link.get("relation") or "contains"), link,
                          source["source_id"], f"#/hierarchy/links/{index}", status=link.get("status") or data.get("status"),
                          evidence_refs=link.get("evidence_refs", link.get("source_refs", [])))

        assets = data.get("assets", [])
        for index, asset in enumerate(assets):
            asset_id = str(asset.get("asset_id"))
            kind = str(asset.get("kind") or "flow_asset")
            if asset_id not in self.nodes:
                self.add_node(asset_id, kind, asset, source["source_id"], f"#/assets/{index}", status=asset.get("status"),
                              label=asset.get("name_zh") or asset_id, location=asset.get("location"),
                              metadata={"flow_status": asset.get("flow_status"), "projection_status": data.get("status")})
            parent_ids = list(asset.get("parent_ids") or ([asset.get("parent_id")] if asset.get("parent_id") else []))
            for parent_id in parent_ids:
                self.add_group(f"group:asset:{parent_id}", "asset_parent", [asset_id], source["source_id"], f"#/assets/{index}/parent_id",
                               parent_id=parent_id, status=data.get("status"))
            for n_index, node in enumerate(asset.get("flow_nodes", [])):
                node_id = str(node.get("node_id"))
                self.add_node(node_id, str(node.get("node_type") or "flow_node"), node, source["source_id"],
                              f"#/assets/{index}/flow_nodes/{n_index}", status=node.get("status"), label=node.get("title") or node.get("name_zh"),
                              metadata={"stage": node.get("stage"), "purpose": node.get("purpose"), "owner_asset_id": asset_id,
                                        "label_status": node.get("label_status")}, location=node.get("location"),
                              evidence_refs=node.get("evidence_refs", []))
                self.add_group(f"group:flow-asset:{asset_id}", "flow_asset", [node_id], source["source_id"],
                               f"#/assets/{index}/flow_nodes/{n_index}", owner_asset_id=asset_id, status=data.get("status"))
                targets = []
                if kind in {"agent", "capability"}:
                    targets.append(asset_id)
                for gate in node.get("gates", []) or []:
                    if gate not in {"Unknown", "automatic", ""}:
                        gate_id = str(gate)
                        targets.append(gate_id)
                        self.add_node(gate_id, "gate", {"id": gate_id, "title": gate_id, "status": node.get("status")}, source["source_id"],
                                      f"#/assets/{index}/flow_nodes/{n_index}/gates", status=node.get("status"), label=gate_id,
                                      metadata={"derived_from": "explicit flow_node.gates", "projection_status": data.get("status")})
                self.add_stage_binding(str(node.get("stage")), targets, source["source_id"], f"#/assets/{index}/flow_nodes/{n_index}",
                                       binding_kind="flow_registry_explicit_owner", status="candidate_projection",
                                       evidence_refs=node.get("evidence_refs", []), source_node_id=node_id,
                                       metadata={"owner_asset_id": asset_id, "node_type": node.get("node_type")})
                next_node = node.get("next_node")
                if next_node and next_node != "Unknown":
                    self.add_edge(node_id, str(next_node), "sequence", node, source["source_id"],
                                  f"#/assets/{index}/flow_nodes/{n_index}/next_node", status=node.get("status"),
                                  evidence_refs=node.get("evidence_refs", []))
            for l_index, link in enumerate(asset.get("links", [])):
                self.add_edge(str(link.get("from")), str(link.get("to")), str(link.get("relation") or "sequence"), link,
                              source["source_id"], f"#/assets/{index}/links/{l_index}", status=link.get("status") or data.get("status"),
                              evidence_refs=link.get("evidence", link.get("evidence_refs", [])))

    def _build_runtime(self, path: Path) -> None:
        source = self._source("runtime", path, "Runtime state and event source")
        data = _json(path)
        self.runtime_overlay["source_refs"] = [_ref(source["source_id"], "$")]
        self.runtime_overlay["status"] = "available"
        for p_index, project in enumerate(data.get("projects", [])):
            project_summary = {
                "project_id": project.get("id"),
                "status": project.get("status"),
                "current_stage": project.get("currentStage"),
                "task_count": len(project.get("tasks", [])),
                "tasks": [],
            }
            for t_index, task in enumerate(project.get("tasks", [])):
                task_id = str(task.get("id"))
                task_summary = {
                    "task_id": task_id,
                    "status": task.get("status"),
                    "current_stage": task.get("currentStage"),
                    "node_ids": [str(node.get("id")) for node in task.get("nodes", [])],
                    "event_count": len(task.get("events", [])),
                }
                project_summary["tasks"].append(task_summary)
                for n_index, node in enumerate(task.get("nodes", [])):
                    node_id = f"runtime:{task_id}:{node.get('id')}"
                    self.add_node(node_id, "runtime_task_node", node, source["source_id"],
                                  f"#/projects/{p_index}/tasks/{t_index}/nodes/{n_index}", status=node.get("status"), label=node.get("name"),
                                  metadata={"task_id": task_id, "stage_id": node.get("stage"), "runtime_namespace": True})
                    stage_id = node.get("stage")
                    if stage_id:
                        self._stage_ids.add(str(stage_id))
                for e_index, event in enumerate(task.get("events", [])):
                    stage_id = event.get("stage_id")
                    agent_id = event.get("agent_id")
                    if stage_id and agent_id:
                        self.add_stage_binding(str(stage_id), [str(agent_id)], source["source_id"],
                                               f"#/projects/{p_index}/tasks/{t_index}/events/{e_index}",
                                               binding_kind="runtime_event", status=str(event.get("status") or "Unknown"),
                                               evidence_refs=[event.get("event_id") or event.get("id")],
                                               source_node_id=str(event.get("node_id") or ""),
                                               metadata={"task_id": task_id, "run_id": event.get("run_id") or event.get("execution_id"),
                                                         "event_type": event.get("type")})
            self.runtime_overlay["projects"].append(project_summary)
        self.runtime_overlay["stage_bindings"] = [b for b in self.stage_bindings.values() if any(r.get("source_id") == "runtime" for r in b.get("source_refs", []))]

    def _detect_cross_registry_conflicts(self) -> None:
        flow = self.source_paths["flow_registry"]
        flow_data = _json(flow)
        for source in flow_data.get("sources", []):
            path = Path(str(source.get("path")))
            if path.exists() and source.get("sha256") and _sha(path) != source.get("sha256"):
                self.conflicts.append({
                    "type": "source_hash_mismatch",
                    "source_path": str(path),
                    "recorded_sha256": source.get("sha256"),
                    "actual_sha256": _sha(path),
                    "registry": "flow_registry.sources",
                })
        cap_agents = {str(a.get("agent_id")) for a in _json(self.source_paths["capability_registry"]).get("agents", [])}
        missing = sorted(self._agent_ids - cap_agents)
        if missing:
            self.conflicts.append({
                "type": "capability_registry_coverage_gap",
                "agent_ids": missing,
                "reason": "Agent Registry records have no corresponding Capability Registry record",
            })
        reciprocal = [edge for edge in self.edges.values() if len(edge.get("directions", [])) > 1]
        if reciprocal:
            self.conflicts.append({
                "type": "relationship_reverse_records_canonicalized",
                "edge_count": len(reciprocal),
                "edge_ids": [edge["id"] for edge in reciprocal],
                "resolution": "one canonical edge retains all raw directions",
            })


def _unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def default_source_paths() -> dict[str, Path]:
    """Resolve the V2 registry sources without hard-coding any machine path.

    Resolution order for the AIOS registries:
      1. `FLOWCHAT_AIOS_ROOT` (export it, or pass `--agents/--capabilities/
         --relationships` explicitly to `generate_v2_topology.py`).
      2. `<workspace>/AIOS`, where workspace is the parent of this skill root.

    Flow registry and runtime stay workspace-relative. Nothing here points at a
    specific user's home directory, so the published skill never leaks one.
    """
    project_root = Path(__file__).resolve().parents[2]
    workspace_root = project_root.parent
    aios_root = Path(os.environ.get("FLOWCHAT_AIOS_ROOT") or (workspace_root / "AIOS"))
    return {
        "agent_registry": aios_root / "registry/agents.json",
        "capability_registry": aios_root / "capabilities/capabilities.json",
        "relationship_registry": aios_root / "relationships/relationships.json",
        "flow_registry": workspace_root / "agent_builder/registry/agent-flow-registry.json",
        "runtime": workspace_root / "runtime/state.json",
    }


def build_projection(source_paths: Mapping[str, Path] | None = None) -> dict[str, Any]:
    paths = source_paths or default_source_paths()
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "missing topology sources: "
            + ", ".join(missing)
            + " — pass --agents/--capabilities/--relationships/--runtime/--agent-flow, "
            "or set FLOWCHAT_AIOS_ROOT to the directory holding registry/, "
            "capabilities/ and relationships/."
        )
    return ProjectionBuilder(paths).build()


__all__ = ["SCHEMA", "ProjectionBuilder", "build_projection", "default_source_paths"]
