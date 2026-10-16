#!/usr/bin/env python3
"""Generate the Level 1 Flowchat system overview from TopologyProjection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from data.topology_projection import build_projection  # noqa: E402


STAGES = (
    ("competitor", "01", "竞品分析"),
    ("requirement", "02", "需求文档"),
    ("interaction", "03", "交互设计"),
    ("prototype", "04", "原型"),
    ("ui_design", "05", "UI 设计"),
    ("development", "06", "开发"),
    ("testing", "07", "测试验收"),
)
RUNTIME_WORKER_IDS = {"interaction-agent", "implementation-worker", "test-worker"}
SYSTEMS = (
    ("rules", "RULES & GOVERNANCE", "规则与治理"),
    ("review", "REVIEW / GATE", "审核与门禁"),
    ("agents", "AGENT / CAPABILITY", "执行能力"),
    ("harness", "HARNESS / RUNTIME", "运行保障"),
    ("artifacts", "ARTIFACT / EVIDENCE", "产物与证据"),
)


def _node_index(projection: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(node.get("id")): node for node in projection.get("nodes", []) if node.get("id")}


def _status(value: Any, fallback: str = "Unknown") -> str:
    return fallback if value in (None, "") else str(value)


def _runtime_project(projection: Mapping[str, Any]) -> Mapping[str, Any]:
    projects = projection.get("runtimeOverlay", {}).get("projects", [])
    return projects[0] if projects else {}


def _runtime_bindings(projection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [binding for binding in projection.get("stageBindings", [])
            if binding.get("binding_kind") == "runtime_event"]


def _runtime_edges(value: Any, default_source: str = "runtime") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in value or []:
        if not isinstance(raw, Mapping):
            continue
        from_id = raw.get("from") or raw.get("source")
        to_id = raw.get("to") or raw.get("target")
        if not from_id or not to_id:
            continue
        result.append({
            "edge_id": raw.get("edge_id") or raw.get("id") or f"{from_id}->{to_id}",
            "from": str(from_id),
            "to": str(to_id),
            "runtime_status": _status(raw.get("runtime_status") or raw.get("status"), "unknown"),
            "source": raw.get("source") or default_source,
            "evidence": raw.get("evidence") or raw.get("evidence_ref") or raw.get("evidence_refs") or "Unknown",
            **({"reason": raw["reason"]} if raw.get("reason") else {}),
        })
    return result


def build_overview_projection(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate facts into the small Level 1 renderer contract."""
    nodes = _node_index(projection)
    runtime = projection.get("runtimeOverlay", {})
    project = _runtime_project(projection)
    bindings = projection.get("stageBindings", [])
    runtime_bindings = _runtime_bindings(projection)
    structural_bindings = [binding for binding in bindings if binding.get("binding_kind") != "runtime_event"]
    bound_stage_ids = {str(binding.get("stage_id")) for binding in structural_bindings}
    runtime_bound_stage_ids = {str(binding.get("stage_id")) for binding in runtime_bindings}
    selected_run = runtime.get("selected_run") or {}
    selected_run_id = selected_run.get("run_id") or selected_run.get("execution_id")
    current_run_bindings = [binding for binding in runtime_bindings
                            if selected_run_id and selected_run_id in {binding.get("metadata", {}).get("run_id"), binding.get("metadata", {}).get("execution_id")}]
    current_run_stage_ids = {str(binding.get("stage_id")) for binding in current_run_bindings}

    agent_nodes = [node for node in projection.get("nodes", [])
                   if node.get("kind") == "agent" and node.get("source_kind") == "agent_registry"]
    capability_nodes = [node for node in projection.get("nodes", []) if node.get("kind") == "capability"]
    rule_nodes = [node for node in projection.get("nodes", []) if node.get("kind") == "rule"]
    gate_nodes = [node for node in projection.get("nodes", []) if node.get("kind") == "gate"]
    harness_nodes = [node for node in projection.get("nodes", []) if node.get("kind") == "harness"]
    artifact_nodes = [node for node in projection.get("nodes", [])
                      if node.get("kind") in {"artifact", "evidence", "artifact_manifest"}]
    runtime_status = "idle" if not runtime.get("selected_run") else _status(runtime.get("selected_run", {}).get("status"), "unknown")
    stage_rows: list[dict[str, Any]] = []
    for stage_id, number, name in STAGES:
        structural = [binding for binding in structural_bindings if binding.get("stage_id") == stage_id]
        runtime_stage = [binding for binding in runtime_bindings if binding.get("stage_id") == stage_id]
        current = [binding for binding in current_run_bindings if binding.get("stage_id") == stage_id]
        visible_bindings = structural + (runtime_stage if runtime_status != "idle" else [])
        executor_ids = sorted({target for binding in visible_bindings for target in binding.get("target_ids", [])
                                if target in nodes and nodes[target].get("kind") in {"agent", "capability", "gate"}})
        stage_rows.append({
            "id": stage_id, "number": number, "name": name,
            "status": "not_run" if runtime_status == "idle" else "pending",
            "phase": "—" if runtime_status == "idle" else "—",
            "activity": "未运行" if runtime_status == "idle" else "等待运行",
            "executor_ids": executor_ids,
            "binding_ids": [binding.get("id") for binding in visible_bindings],
            "structural_binding": bool(structural),
            "runtime_binding": bool(runtime_stage),
            "current_run_binding": bool(current),
            "binding_status": "current" if current else "runtime" if runtime_stage and runtime_status != "idle" else "configured" if structural else "unbound",
            "source_refs": [ref for binding in visible_bindings for ref in binding.get("source_refs", [])],
        })

    active_agents = [node for node in agent_nodes if _status(node.get("status")).lower() in {"active", "running"}]
    registered_rules = sorted({str(node.get("id")).split(":")[1] for node in rule_nodes if str(node.get("id", "")).startswith("rule:") and ":" in str(node.get("id"))})
    active_rules = [node for node in rule_nodes if str(node.get("id", "")).startswith("rule:") and _status(node.get("status")).lower() in {"active", "running", "verified"}]
    waiting = [] if runtime_status == "idle" else sorted({status for binding in runtime_bindings for status in binding.get("statuses", [])
                                                           if status in {"waiting_review", "needs_human", "review"}})
    runtime_workers = [] if runtime_status == "idle" else sorted({target for binding in runtime_bindings for target in binding.get("target_ids", [])
                                                                    if target in nodes and target in {"interaction-agent", "implementation-worker", "test-worker"}})
    registry_workflows = len([node for node in projection.get("nodes", []) if node.get("kind") == "workflow"])
    registered_agent_count = max(0, len(agent_nodes) - len(RUNTIME_WORKER_IDS & {str(node.get("id")) for node in agent_nodes}))
    runtime_worker_count = len(RUNTIME_WORKER_IDS)
    active_edges = _runtime_edges(runtime.get("active_edges"))
    return_edges = _runtime_edges(runtime.get("return_edges"))
    project_id = project.get("project_id") or "PROJECT-COCKPIT"
    task_id = selected_run.get("task_id") or selected_run.get("id")
    return {
        "schema": "overview-projection/v1",
        "brain": {
            "status": "IDLE" if runtime_status == "idle" else runtime_status.upper(),
            "current_stage": "—" if runtime_status == "idle" else project.get("current_stage", "—"),
            "current_action": "等待任务" if runtime_status == "idle" else "Agent Dispatch",
            "summary": f"{registered_agent_count} Registered Agents · {runtime_worker_count} Runtime Workers · {registry_workflows} Workflows" if runtime_status == "idle" else f"{registered_agent_count} Registered Agents · {len(runtime_workers)} Runtime Workers",
            "source_refs": runtime.get("source_refs", []) + projection.get("sources", [])[:1],
        },
        "stages": stage_rows,
        "systems": {
            "rules": {"title": "RULES & GOVERNANCE", "subtitle": "规则与治理", "registered_count": len(registered_rules), "active_count": len(active_rules), "applied_count": runtime.get("applied_rule_count", 0), "pending_count": runtime.get("pending_rule_count", 0), "conflict_count": len(projection.get("conflicts", [])), "state": "conflict" if projection.get("conflicts") else "clear"},
            "review": {"title": "REVIEW / GATE", "subtitle": "审核与门禁", "registered_count": len(gate_nodes), "auto_count": runtime.get("auto_review_count"), "human_count": runtime.get("human_review_count", len(waiting)), "waiting": bool(waiting) or bool(runtime.get("human_review_count")), "gate_count": len(gate_nodes)},
            "agents": {"title": "AGENT / CAPABILITY", "subtitle": "执行能力", "active_count": len(active_agents), "registry_agent_count": registered_agent_count, "runtime_worker_count": runtime_worker_count, "capability_count": len(capability_nodes), "runtime_workers": runtime_workers, "chips": ["REQ", "UI", "TECH"]},
            "harness": {"title": "HARNESS / RUNTIME", "subtitle": "运行保障", "state": "Runtime Idle" if runtime_status == "idle" else "Runtime Active", "harness_count": len(harness_nodes), "preflight": "—" if runtime_status == "idle" else "✓"},
            "artifacts": {"title": "ARTIFACT / EVIDENCE", "subtitle": "产物与证据", "count": len(artifact_nodes), "latest": "—" if not artifact_nodes else artifact_nodes[-1].get("label", "Unknown")},
        },
        "runtime": {"state": runtime_status, "task_id": task_id, "project_id": project_id, "current_stage": project.get("current_stage"), "active_edges": active_edges, "return_edges": return_edges, "selected_run": runtime.get("selected_run")},
        "alerts": [], "sources": projection.get("sources", []),
    }


def build_model(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a small Level 2 compatibility model while Level 1 uses the adapter."""
    nodes = _node_index(projection)
    agents = []
    for node in projection.get("nodes", []):
        if node.get("kind") != "agent" or node.get("source_kind") != "agent_registry":
            continue
        capabilities = [candidate for candidate in projection.get("nodes", [])
                        if candidate.get("kind") == "capability" and candidate.get("metadata", {}).get("agent_id") == node.get("id")]
        agents.append({"id": node.get("id"), "name": node.get("label") or node.get("id"), "status": node.get("status", "Unknown"), "version": node.get("metadata", {}).get("version", "Unknown"), "path": node.get("metadata", {}).get("path", ""), "capabilities": [{"id": c.get("id", "").split(":", 2)[-1], "name": c.get("label", "Unknown"), "input": c.get("metadata", {}).get("input", "Unknown"), "output": c.get("metadata", {}).get("output", "Unknown"), "trigger": c.get("metadata", {}).get("trigger", "Unknown"), "constraints": c.get("metadata", {}).get("constraints", []), "source": c.get("source_refs", [{}])[0].get("pointer", "Unknown")} for c in capabilities], "source": node.get("source_refs", [{}])[0].get("pointer", "Unknown")})
    relationships = []
    for edge in projection.get("edges", []):
        if edge.get("source_refs", [{}])[0].get("source_id") != "relationship_registry":
            continue
        first = edge.get("directions", [{}])[0]
        relationships.append({"id": edge.get("id"), "from": edge.get("from"), "to": edge.get("to"), "type": edge.get("relation", "Unknown"), "automated": first.get("record", {}).get("automated"), "carrier": first.get("record", {}).get("carrier", "Unknown"), "evidence": first.get("record", {}).get("evidence", {}), "source": first.get("source_ref", {}).get("pointer", "Unknown")})
    overview = build_overview_projection(projection)
    return {"schema": "flowchat-v2/overview", "overviewProjection": overview, "stages": [[stage_id, name] for stage_id, _, name in STAGES], "systems": [[key, title, subtitle] for key, title, subtitle in SYSTEMS], "agents": agents, "relationships": relationships, "runtime": overview["runtime"], "candidate_projection": None, "sources": projection.get("sources", [])}


def load_projection(path: Path) -> dict[str, Any]:
    projection = json.loads(path.read_text(encoding="utf-8"))
    required = {"nodes", "edges", "groups", "stageBindings", "runtimeOverlay", "conflicts", "sources"}
    if projection.get("schema") != "topology-projection/v1" or not required <= set(projection):
        raise ValueError("projection must be topology-projection/v1 with all required collections")
    return projection


def render(model: Mapping[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__MODEL_JSON__", payload)


HTML_TEMPLATE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>总控大脑 · Level 1 System Overview</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#172033;background:#f7f9fc;--line:#d8e1ec;--blue:#2563eb;--green:#16a34a;--amber:#d97706;--red:#dc2626}*{box-sizing:border-box}body{margin:0;background:#f7f9fc}button{font:inherit;cursor:pointer}header{height:62px;display:flex;align-items:center;gap:16px;padding:0 28px;background:#fff;border-bottom:1px solid #e7edf5}header strong{font-size:17px}header small{color:#64748b;font-size:12px}.status{margin-left:auto;padding:6px 12px;border-radius:99px;background:#f1f5f9;color:#64748b;font-size:11px}.layout{display:grid;grid-template-columns:minmax(0,1fr);min-height:calc(100vh - 62px)}.layout.inspector-open{grid-template-columns:minmax(0,1fr) 440px}main{padding:22px 26px;overflow:auto}.canvas{max-width:1640px;margin:0 auto}.topline{display:flex;align-items:center;gap:12px;margin-bottom:14px}.topline h1{margin:0;font-size:18px}.crumb{font-size:11px;color:#94a3b8;letter-spacing:.08em}.spacer{flex:1}.topline button,.ins-head button{border:1px solid #dce4ef;background:#fff;color:#334155;border-radius:8px;padding:6px 10px}.overview-space{min-height:770px;padding:32px 38px 44px;background:#f7f9fc}.eyebrow,.plane-title{font-size:11px;letter-spacing:.12em;color:#64748b}.plane-title{margin:0 0 12px;color:#94a3b8;letter-spacing:.14em}.control-plane{width:520px;margin:0 auto 24px}.control-row{display:flex;justify-content:center;gap:20px}.control-card,.agent-card,.harness-card,.artifact-card{width:220px;height:96px;padding:15px 17px;text-align:left;border-radius:16px;background:#fff}.control-card{background:#eef2ff;border:1.5px solid #818cf8;box-shadow:0 8px 18px #4f46e512}.control-card.review{background:#fff7e6;border-color:#d97706}.node-kicker{font-size:10px;letter-spacing:.08em;color:#64748b}.node-title{margin-top:8px;font-weight:700;font-size:14px;color:#172033}.node-sub{margin-top:6px;font-size:11px;color:#64748b}.node-metric{margin-top:9px;font-size:12px;color:#334155}.control-arrow{display:none}.return-edge-wrap{min-width:1498px;margin:18px 0 0;position:relative;color:#dc2626;font-size:11px}.return-edge-wrap svg{display:block;width:1498px;height:92px;overflow:visible}.return-edge-wrap path{fill:none;stroke:#dc2626;stroke-width:2;stroke-dasharray:8 6}.return-edge-wrap span{display:block;margin-top:-8px;text-align:center;color:#991b1b}.brain{width:480px;height:136px;margin:0 auto 28px;padding:18px 22px;border-radius:22px;background:#eff6ff;border:2px solid #93c5fd;box-shadow:0 10px 22px #2563eb12}.brain.running{border-color:#2563eb}.brain.blocked{border-color:#2563eb;border-bottom:5px solid #dc2626}.brain-head{display:flex;justify-content:space-between;align-items:center;font-size:11px;letter-spacing:.1em;color:#1d4ed8}.brain-state{padding:4px 8px;border-radius:99px;background:#dbeafe;color:#1d4ed8;font-size:10px}.brain.blocked .brain-state{background:#fee2e2;color:#dc2626}.brain-name{margin-top:14px;font-size:20px;font-weight:700}.brain-details{display:flex;gap:28px;margin-top:10px;font-size:11px;color:#64748b}.brain-details b{display:block;color:#334155;font-size:12px;margin-top:3px}.stage-plane{margin-top:6px}.stage-flow{display:flex;align-items:center;justify-content:flex-start;min-width:1310px;overflow:visible}.stage-card{flex:0 0 190px;height:104px;padding:14px 15px;border:1.5px solid #d8e1ec;border-radius:16px;background:#fff;text-align:left;position:relative;z-index:1}.stage-card.current{background:#eff6ff;border-color:#2563eb}.stage-card.completed{background:#fbfffc;border-color:#bbf7d0}.stage-card.review{background:#fffaf0;border-color:#d97706}.stage-card.blocked{border-color:#dc2626;background:#fff7f7}.stage-number{font-size:11px;color:#64748b;letter-spacing:.1em}.stage-name{margin-top:9px;font-size:16px;font-weight:700}.stage-phase{margin-top:8px;color:#64748b;font-size:11px}.stage-status{position:absolute;right:12px;top:12px;font-size:10px;color:#64748b}.stage-card.current .stage-status{color:#2563eb}.stage-card.completed .stage-status{color:#16a34a}.stage-card.review .stage-status{color:#d97706}.stage-card.blocked .stage-status{color:#dc2626}.rail-link{height:2px;width:28px;background:#d8e1ec;position:relative;flex:0 0 28px}.rail-link .overlay{height:3px;width:0;position:absolute;left:0;top:-.5px;background:var(--blue)}.rail-link.completed .overlay,.rail-link.running .overlay,.rail-link.review .overlay,.rail-link.blocked .overlay{width:100%}.rail-link.completed .overlay{background:var(--green)}.rail-link.running .overlay{background:var(--blue)}.rail-link.review .overlay{background:var(--amber)}.rail-link.blocked .overlay{background:var(--red)}.rail-link.return{display:none}.moving-dot{position:absolute;width:6px;height:6px;border-radius:50%;background:#fff;border:2px solid var(--blue);top:-2px;animation:active-dots 2.4s linear infinite}.moving-dot:nth-child(2){animation-delay:.8s}.moving-dot:nth-child(3){animation-delay:1.6s}@keyframes active-dots{from{left:0}to{left:calc(100% - 6px)}}.execution-plane{margin:36px auto 0;max-width:500px}.execution-row{display:flex;justify-content:center;gap:20px}.agent-card{background:#f6f2ff;border:1.5px solid #c4b5fd}.agent-card .node-kicker{color:#7c3aed}.harness-card{background:#f8fafc;border:1.5px dashed #94a3b8}.output-plane{margin:34px auto 0;max-width:220px}.artifact-card{height:96px;background:#f0fdfa;border:1.5px solid #5eead4;position:relative;overflow:hidden}.artifact-card:after{content:"";position:absolute;right:0;top:0;border-style:solid;border-width:0 24px 24px 0;border-color:transparent #ccfbf1 transparent transparent}.issue-card{width:220px;min-height:82px;margin:22px auto 0;padding:13px 15px;border:1.5px solid #fca5a5;background:#fff1f2;border-radius:14px;color:#991b1b}.issue-card strong{display:block;font-size:11px;letter-spacing:.08em}.issue-card span{display:block;margin-top:7px;font-size:12px}.system-button{border:0;padding:0}.system-button:focus-visible,.stage-card:focus-visible,.brain:focus-visible{outline:3px solid #93c5fd;outline-offset:3px}.hint{margin-top:20px;text-align:center;color:#94a3b8;font-size:11px}.layout aside{display:none;background:#fff;border-left:1px solid #dce4ef;overflow:auto;padding:24px}.layout.inspector-open aside{display:block}.ins-head{display:flex;align-items:center;gap:8px}.ins-head h2{margin:0;flex:1;font-size:17px}.ins-body{font-size:13px;line-height:1.6;overflow-wrap:anywhere}.ins-body dl{display:grid;grid-template-columns:105px 1fr;gap:8px}.ins-body dt{color:#64748b}.ins-body dd{margin:0}.ins-body code{font-size:11px}.ins-note{padding:12px;border-radius:8px;background:#f8fafc;color:#64748b}.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}.card{background:#fff;border:1px solid #dfe6f0;border-radius:14px;padding:18px;min-height:110px;text-align:left;width:100%}.notice{padding:16px 18px;border:1px dashed #cbd5e1;border-radius:12px;background:#fff;color:#64748b;font-size:13px;line-height:1.7}@media(max-width:1450px){.overview-space{overflow-x:auto;padding-left:20px;padding-right:20px}}@media(max-width:900px){.layout.inspector-open{grid-template-columns:1fr;grid-template-rows:minmax(400px,1fr) 45vh}.control-plane{width:auto}.brain{width:min(480px,100%)}.control-row,.execution-row{flex-wrap:wrap}}
</style></head><body><div class="shell"><header><strong>总控大脑</strong><small>PROJECT CONTEXT</small><span class="status" id="run-status"></span></header><div class="layout" id="layout"><main><div class="canvas"><div class="topline"><button id="back" hidden>← 返回系统总览</button><h1 id="view-title">系统总览</h1><span class="crumb" id="crumb">LEVEL 1</span><span class="spacer"></span><button id="reset">总览</button></div><div id="content"></div></div></main><aside id="inspector"><div class="ins-head"><h2 id="ins-title">Inspector</h2><button id="pin" aria-pressed="false">Pin</button><button id="close">关闭</button></div><div class="ins-body" id="ins-body"></div></aside></div></div><script>window.__FLOWCHAT_V2_MODEL__=__MODEL_JSON__;</script><script>
(()=>{'use strict';const model=window.__FLOWCHAT_V2_MODEL__,content=document.getElementById('content'),layout=document.getElementById('layout'),body=document.getElementById('ins-body');let view='overview',focus=null,pinned=false;const esc=s=>String(s??'Unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const friendly={'design-research-agent':'设计研究 Agent','requirement-agent':'需求 Agent','interaction-agent':'交互 Agent','implementation-worker':'Implementation Worker','test-worker':'Test Worker'};const clone=o=>JSON.parse(JSON.stringify(o));
function fixtureProjection(){const p=clone(model.overviewProjection),name=new URLSearchParams(location.search).get('fixture');if(!name)return p;const edge=(from,to,status)=>({edge_id:`stage-${from}-to-${to}`,from,to,runtime_status:status,source:'fixture',evidence:'FIXTURE-DEVELOPMENT-ONLY'});const set=(id,status,phase,activity)=>{const stage=p.stages.find(x=>x.id===id);if(stage){stage.status=status;stage.phase=phase;stage.activity=activity;stage.current_run_binding=true;stage.binding_status='current'}};p.runtime.state=name;p.runtime.task_id='FIXTURE-DEVELOPMENT-ONLY';p.runtime.project_id='PROJECT-COCKPIT';p.runtime.active_edges=[];p.runtime.return_edges=[];p.brain.status=name.toUpperCase();p.brain.current_stage=name==='blocked'?'development':name==='review'?'prototype':name==='completed'?'testing':'interaction';p.brain.current_action=name==='blocked'?'等待修复':name==='review'?'等待人工审核':name==='completed'?'完成验收':'Agent Dispatch';p.brain.summary=name==='running'?'3 Active · 1 Waiting':name==='review'?'1 Waiting Human':name==='blocked'?'1 Blocked · Return':'7 Completed';if(name==='running'){p.systems.rules.applied_count=2;p.systems.rules.pending_count=1;p.systems.review.auto_count=2;p.systems.review.human_count=1;p.systems.review.waiting=true;p.systems.agents.runtime_workers=['interaction-agent'];p.systems.harness.state='Runtime Active';p.systems.harness.preflight='✓';set('competitor','completed','POST','完成');set('requirement','completed','POST','完成');set('interaction','running','MID','Agent 执行');set('prototype','pending','—','等待进入');p.runtime.active_edges=[edge('competitor','requirement','completed'),edge('requirement','interaction','completed'),edge('interaction','prototype','running')]}if(name==='review'){p.systems.rules.applied_count=2;p.systems.rules.pending_count=1;p.systems.review.auto_count=2;p.systems.review.human_count=1;p.systems.review.waiting=true;p.systems.harness.state='Verification Running';p.systems.harness.preflight='✓';set('competitor','completed','POST','完成');set('requirement','completed','POST','完成');set('interaction','completed','POST','完成');set('prototype','review','POST','等待人工');p.runtime.active_edges=[edge('competitor','requirement','completed'),edge('requirement','interaction','completed'),edge('interaction','prototype','completed'),edge('prototype','ui_design','review')]}if(name==='blocked'){p.systems.rules.applied_count=1;p.systems.rules.pending_count=2;p.systems.review.auto_count=1;p.systems.review.human_count=0;p.systems.review.waiting=false;p.systems.agents.runtime_workers=['implementation-worker'];p.systems.harness.state='Test Failed';p.systems.harness.preflight='✓';set('competitor','completed','POST','完成');set('requirement','completed','POST','完成');set('interaction','completed','POST','完成');set('prototype','completed','POST','完成');set('ui_design','completed','POST','完成');set('development','blocked','BLOCKED','接口边界冲突');set('testing','pending','—','等待修复');p.runtime.active_edges=[edge('competitor','requirement','completed'),edge('requirement','interaction','completed'),edge('interaction','prototype','completed'),edge('prototype','ui_design','completed'),edge('ui_design','development','blocked')];p.runtime.return_edges=[{edge_id:'return-development-requirement',from:'development',to:'requirement',runtime_status:'blocked',source:'fixture',evidence:'FIXTURE-DEVELOPMENT-ONLY',reason:'接口边界冲突'}];p.alerts=[{id:'fixture-block',title:'接口边界冲突',reason:'接口边界冲突',status:'blocked',return_stage_id:'requirement'}]}if(name==='completed'){p.systems.rules.applied_count=3;p.systems.rules.pending_count=0;p.systems.review.auto_count=2;p.systems.review.human_count=0;p.systems.review.waiting=false;p.systems.harness.state='Verification Passed';p.systems.harness.preflight='✓';p.stages.forEach(stage=>set(stage.id,'completed','POST','完成'));p.runtime.active_edges=p.stages.slice(0,-1).map((stage,index)=>edge(stage.id,p.stages[index+1].id,'completed'))}return p}
function edgeStatus(p,index){const a=p.stages[index],b=p.stages[index+1];if(!a||!b)return '';const edge=(p.runtime.active_edges||[]).find(candidate=>candidate.from===a.id&&candidate.to===b.id);return edge?String(edge.runtime_status||'').toLowerCase():''}
function returnEdgeMarkup(p){const edge=(p.runtime.return_edges||[])[0];if(!edge)return '';const from=p.stages.findIndex(stage=>stage.id===edge.from),to=p.stages.findIndex(stage=>stage.id===edge.to);if(from<0||to<0)return '';const start=from*218+95,end=to*218+95,route=`M ${start} 2 L ${start} 78 L ${end} 78 L ${end} 2`,target=p.stages[to]?.name||edge.to;return `<div class="return-edge-wrap" data-edge-id="${esc(edge.edge_id)}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" data-route="${esc(route)}"><svg viewBox="0 0 1498 92" aria-label="Return Edge"><defs><marker id="return-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#dc2626"/></marker></defs><path d="${route}" marker-end="url(#return-arrow)"/></svg><span>Return → ${esc(target)} · ${esc(edge.reason||'')}</span></div>`}
function stageCard(s){const cls=s.status==='running'?'current ':s.status;const statusMap={not_run:'未运行',pending:'待任务',running:'运行中',review:'待审核',blocked:'阻塞',completed:'已完成'};const status=statusMap[s.status]||s.status;return `<button class="stage-card ${esc(cls)}" data-nav="stage:${esc(s.id)}" aria-label="${esc(s.name)} ${esc(status)}"><span class="stage-number">${esc(s.number)}</span><span class="stage-status">${esc(status)}</span><div class="stage-name">${esc(s.name)}</div><div class="stage-phase">${esc(s.phase==='—'?'—':`${s.phase} · ${s.activity}`)}</div></button>`}
function railLink(status){const dots=status==='running'?'<span class="moving-dot"></span><span class="moving-dot"></span><span class="moving-dot"></span>':'';return `<span class="rail-link ${status}" data-runtime-status="${esc(status||'idle')}"><span class="overlay"></span>${dots}</span>`}
function controlNode(key,info){const cls=key==='review'?'review':'';let metric=key==='rules'?(info.applied_count?`${info.applied_count} Applied · ${info.pending_count} Pending`:`${info.registered_count} Registered Rules · ${info.conflict_count} Registry Conflicts`):key==='review'?(info.waiting?`AUTO ${info.auto_count??0} · HUMAN ${info.human_count} · ${info.human_count} Waiting Human`:`${info.registered_count} Registered Gates · No Active Review`):'';return `<button class="control-card ${cls}" data-nav="${esc(key)}"><div class="node-kicker">${esc(info.title)}</div><div class="node-title">${esc(info.subtitle)}</div><div class="node-metric">${esc(metric)}</div></button>`}
function systemCard(key,info){if(key==='agents')return `<button class="agent-card" data-nav="agents"><div class="node-kicker">${esc(info.title)}</div><div class="node-title">${esc(info.subtitle)}</div><div class="node-metric">${info.registry_agent_count} Registered Agents · ${info.runtime_worker_count} Runtime Workers</div><div class="node-sub">${info.runtime_workers.length?'RUNTIME WORKER · '+info.runtime_workers.map(x=>friendly[x]||x).join(' · '):'Registry / Runtime 分离'}</div></button>`;if(key==='harness')return `<button class="harness-card" data-nav="harness"><div class="node-kicker">${esc(info.title)}</div><div class="node-title">${esc(info.subtitle)}</div><div class="node-metric">${esc(info.preflight==='—'?'Preflight —':`Preflight ${info.preflight}`)}</div><div class="node-sub">${esc(info.state)}</div></button>`;return `<button class="artifact-card" data-nav="${esc(key)}"><div class="node-kicker">${esc(info.title)}</div><div class="node-title">${esc(info.subtitle)}</div><div class="node-metric">${key==='artifacts'?(info.count?`${info.count} Artifacts`:'No Artifact Evidence'):''}</div><div class="node-sub">${key==='artifacts'&&info.count?'Latest · '+esc(info.latest):''}</div></button>`}
function brain(p){const b=p.brain,stage=p.stages.find(x=>x.id===b.current_stage),current=stage?`${stage.number} ${stage.name}`:b.current_stage;return `<div class="brain ${esc(String(b.status).toLowerCase())}" tabindex="0" data-nav="brain"><div class="brain-head"><span>ORCHESTRATOR HUB</span><span class="brain-state">${esc(b.status)}</span></div><div class="brain-name">◎ 总控大脑</div><div class="brain-details"><span>当前阶段<b>${esc(current)}</b></span><span>当前动作<b>${esc(b.current_action)}</b></span><span>运行摘要<b>${esc(b.summary)}</b></span></div></div>`}
function overview(){const p=fixtureProjection(),sys=p.systems;let stages='';p.stages.forEach((stage,index)=>{stages+=stageCard(stage);if(index<p.stages.length-1)stages+=railLink(edgeStatus(p,index))});const issue=p.alerts?.[0],returnTarget=issue?.return_stage_id?p.stages.find(stage=>stage.id===issue.return_stage_id)?.name||issue.return_stage_id:'';return `<section class="overview-space"><div class="control-plane"><h2 class="plane-title">CONTROL PLANE</h2><div class="control-row">${controlNode('rules',sys.rules)}${controlNode('review',sys.review)}</div></div>${brain(p)}<div class="stage-plane"><h2 class="plane-title">STAGE RAIL</h2><div class="stage-flow">${stages}</div>${returnEdgeMarkup(p)}</div><div class="execution-plane"><h2 class="plane-title">EXECUTION PLANE</h2><div class="execution-row">${systemCard('agents',sys.agents)}${systemCard('harness',sys.harness)}</div></div><div class="output-plane"><h2 class="plane-title">OUTPUT PLANE</h2>${systemCard('artifacts',sys.artifacts)}</div>${issue?`<div class="issue-card"><strong>⚠ BLOCKED</strong><span>${esc(issue.title)}${returnTarget?`<br>Return → ${esc(returnTarget)}`:''}</span></div>`:''}<div class="hint">点击一级节点切换视图 · fixture 仅用于开发验收，不写入事实源</div></section>`}
function setView(next,id){view=next;focus=id||null;document.getElementById('back').hidden=next==='overview';document.getElementById('view-title').textContent=next==='overview'?'系统总览':next==='stage'?((model.stages.find(s=>s[0]===id)||[])[1]||id)+' · Stage Detail':next==='agent'?(model.agents.find(a=>a.id===id)?.name||id):next.toUpperCase();document.getElementById('crumb').textContent=next==='overview'?'LEVEL 1':'LEVEL 2';render();if(layout.classList.contains('inspector-open')&&!pinned)closeInspector()}
function detail(){if(view==='stage'){const s=fixtureProjection().stages.find(x=>x.id===focus);return `<div class="notice">${esc(s?.name||focus)} · ${esc(s?.phase||'—')} · ${esc(s?.activity||'—')}<br>StageBinding：${esc(s?.binding_status||'unbound')}。完整 Binding 在 TopologyProjection 中保留。</div>`}if(view==='brain')return '<div class="notice">Brain 详情使用 overviewProjection 聚合结果。Runtime 与 Registry 状态分离。</div>';if(view==='agents')return `<div class="detail-grid">${model.agents.map(a=>`<button class="card" data-agent="${esc(a.id)}"><h3>${esc(a.name)}</h3><p>${esc(a.id)} · ${a.capabilities.length} Capabilities</p><strong>${esc(a.status)}</strong></button>`).join('')}</div>`;if(view==='agent'){const a=model.agents.find(x=>x.id===focus);return a?`<div class="notice">${esc(a.name)} · ${esc(a.status)}<br>完整 ID：<code>${esc(a.id)}</code></div>`:'<div class="notice">Agent 未登记</div>'}return `<div class="notice">${esc(view)} Detail 保持现有入口。本轮只验证 Level 1。</div>`}
function closeInspector(){layout.classList.remove('inspector-open')}function render(){const headerProjection=fixtureProjection(),headerState=headerProjection.runtime.state==='idle'?`${headerProjection.runtime.project_id||'PROJECT-COCKPIT'} · IDLE`:`${headerProjection.runtime.task_id||headerProjection.runtime.project_id} · ${headerProjection.brain.status}`;document.getElementById('run-status').textContent=headerState;content.innerHTML=view==='overview'?overview():detail();content.querySelectorAll('[data-nav]').forEach(n=>{const go=()=>{const v=n.dataset.nav;v.startsWith('stage:')?setView('stage',v.slice(6)):setView(v)};n.addEventListener('click',go);n.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})});content.querySelectorAll('[data-agent]').forEach(n=>n.addEventListener('click',()=>setView('agent',n.dataset.agent)))}
document.getElementById('back').onclick=()=>setView('overview');document.getElementById('reset').onclick=()=>setView('overview');document.getElementById('close').onclick=closeInspector;document.getElementById('pin').onclick=e=>{pinned=!pinned;e.currentTarget.setAttribute('aria-pressed',String(pinned))};render()})();</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Level 1 Flowchat overview from TopologyProjection")
    parser.add_argument("--projection", type=Path)
    parser.add_argument("--agents", type=Path)
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("--relationships", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--agent-flow", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.projection:
        projection = load_projection(args.projection)
    else:
        paths = {"agent_registry": args.agents, "capability_registry": args.capabilities, "relationship_registry": args.relationships, "flow_registry": args.agent_flow, "runtime": args.runtime}
        if not all(paths.values()):
            parser.error("use --projection or provide all registry/runtime paths")
        projection = build_projection(paths)
    model = build_model(projection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(model), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "schema": model["schema"], "overview_schema": model["overviewProjection"]["schema"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
