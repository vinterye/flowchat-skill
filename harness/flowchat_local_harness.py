#!/usr/bin/env python3
"""Local Harness for standalone Flowchat HTML artifacts.

This intentionally does not call project skill.flowchart gates. It validates
standalone graph geometry, arrow anchoring, text layout, and interaction hooks.
Browser interaction evidence is supplied as a local JSON receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from collections import Counter

MIN_SEGMENT = 8.0
NEAR_ZERO = 2.0
DEFAULT_MIN_EDGE = 90.0
DEFAULT_MIN_ARROW = 75.0
MAX_EDGE_STROKE_WIDTH = 2.0
MAX_ARROW_MARKER_SIZE = 5.0
TOLERANCE = 2.5


def _load_graph(html: str) -> dict[str, Any]:
    match = re.search(r"window\.__FLOWCHAT_GRAPH__=(.*?);window\.__FLOWCHAT_THEME__=", html, re.S)
    if not match:
        raise ValueError("missing embedded Flowchat graph")
    return json.loads(match.group(1))


def _paths(html: str) -> dict[str, list[list[float]]]:
    result: dict[str, list[list[float]]] = {}
    pattern = re.compile(r'data-edge="([^"]+)"[^>]*>\s*<path class="flowchat-edge" d="([^"]+)"', re.S)
    for edge_id, path in pattern.findall(html):
        points = [[float(x), float(y)] for x, y in re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path)]
        result[edge_id] = points
    return result


def _length(a: list[float], b: list[float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _segment_length(points: list[list[float]]) -> list[float]:
    return [_length(a, b) for a, b in zip(points, points[1:])]


def _diamond_side(node: dict[str, Any]) -> float:
    return math.hypot(float(node["width"]) / 2, float(node["height"]) / 2)


def _on_boundary(node: dict[str, Any], point: list[float]) -> bool:
    x, y = point
    left, top = float(node["x"]), float(node["y"])
    width, height = float(node["width"]), float(node["height"])
    right, bottom = left + width, top + height
    shape = node.get("shape", "rect")
    if shape == "diamond":
        value = abs((x - (left + width / 2)) / max(width / 2, 1)) + abs((y - (top + height / 2)) / max(height / 2, 1))
        return abs(value - 1) <= 0.06
    if shape == "circle":
        return abs(math.hypot(x - (left + width / 2), y - (top + height / 2)) - min(width, height) / 2) <= TOLERANCE
    inside_x, inside_y = left - TOLERANCE <= x <= right + TOLERANCE, top - TOLERANCE <= y <= bottom + TOLERANCE
    on_side = min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom)) <= TOLERANCE
    return inside_x and inside_y and on_side


def _axis_aligned(a: list[float], b: list[float]) -> bool:
    return abs(a[0] - b[0]) <= 0.01 or abs(a[1] - b[1]) <= 0.01


def _segment_hits_rect(a: list[float], b: list[float], node: dict[str, Any]) -> bool:
    left, top = float(node["x"]), float(node["y"])
    right, bottom = left + float(node["width"]), top + float(node["height"])
    if abs(a[0] - b[0]) <= 0.01:
        x = a[0]
        return left + TOLERANCE < x < right - TOLERANCE and max(min(a[1], b[1]), top + TOLERANCE) < min(max(a[1], b[1]), bottom - TOLERANCE)
    if abs(a[1] - b[1]) <= 0.01:
        y = a[1]
        return top + TOLERANCE < y < bottom - TOLERANCE and max(min(a[0], b[0]), left + TOLERANCE) < min(max(a[0], b[0]), right - TOLERANCE)
    return False


def _attrs(markup: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', markup))


def _inside(node: dict[str, Any], point: list[float]) -> bool:
    x, y = point
    left, top, w, h = (float(node[k]) for k in ("x", "y", "width", "height"))
    dx, dy = x - left - w / 2, y - top - h / 2
    if node.get("shape") == "diamond":
        return abs(dx)/(w/2) + abs(dy)/(h/2) < 1 - 1e-6
    if node.get("shape") == "circle":
        return math.hypot(dx,dy) < min(w,h)/2 - 1e-6
    return left + 1e-6 < x < left+w-1e-6 and top+1e-6 < y < top+h-1e-6


def _hits(a: list[float], b: list[float], node: dict[str, Any]) -> bool:
    # Clip orthogonal segments analytically, including source and target bodies.
    left, top, w, h = (float(node[k]) for k in ("x", "y", "width", "height"))
    cx,cy=left+w/2,top+h/2
    horizontal=abs(a[1]-b[1]) < 1e-6
    if horizontal:
        fixed=a[1]; span=(min(a[0],b[0]),max(a[0],b[0])); center=cx; half=w/2
        dist=abs(fixed-cy); bound=h/2
    else:
        fixed=a[0]; span=(min(a[1],b[1]),max(a[1],b[1])); center=cy; half=h/2
        dist=abs(fixed-cx); bound=w/2
    if node.get("shape") == "circle":
        radius=min(w,h)/2
        if dist >= radius: return False
        half=math.sqrt(radius*radius-dist*dist)
    elif node.get("shape") == "diamond":
        if dist >= bound: return False
        half *= 1-dist/bound
    elif dist >= bound: return False
    return max(span[0],center-half)+1e-5 < min(span[1],center+half)


def _overlap(a, b, c, d):
    horizontal=abs(a[1]-b[1])<1e-6
    other_horizontal=abs(c[1]-d[1])<1e-6
    if horizontal != other_horizontal: return None
    axis=0 if horizontal else 1; fixed=1-axis
    if abs(a[fixed]-c[fixed])>1e-6: return None
    lo=max(min(a[axis],b[axis]), min(c[axis],d[axis]))
    hi=min(max(a[axis],b[axis]), max(c[axis],d[axis]))
    if hi-lo <= 1e-5: return None
    return (b[axis]-a[axis])*(d[axis]-c[axis])>0


def _cross(a,b,c,d):
    if (abs(a[1]-b[1])<1e-6)==(abs(c[1]-d[1])<1e-6): return None
    if abs(a[1]-b[1])>1e-6: a,b,c,d=c,d,a,b
    x,y=c[0],a[1]
    if min(a[0],b[0])+1e-5 < x < max(a[0],b[0])-1e-5 and min(c[1],d[1])+1e-5 < y < max(c[1],d[1])-1e-5:
        return [x,y]
    return None


def _edge_group_markup(html: str, edge_id: str) -> str:
    """Return one edge group's markup so crossing evidence is edge-bound."""
    match = re.search(
        r'<g class="flowchat-edge-group[^>]*data-edge="' + re.escape(edge_id) + r'"[^>]*>.*?</g>',
        html,
        re.S,
    )
    return match.group(0) if match else ""


def _edge_side(edge_id: str, edge: dict[str, Any], role: str, nodes: dict[str, dict[str, Any]], paths: dict[str, list[list[float]]]) -> str | None:
    explicit = edge.get(f"{role}_side") or edge.get(f"{role}_port")
    if explicit:
        return str(explicit).split("-", 1)[0]
    points = paths.get(edge_id, [])
    node = nodes.get(str(edge.get("source" if role == "source" else "target")))
    if not points or not node or node.get("shape", "rect") != "rect":
        return None
    point = points[0] if role == "source" else points[-1]
    left, top, width, height = (float(node[k]) for k in ("x", "y", "width", "height"))
    distances = {
        "left": abs(point[0] - left),
        "right": abs(point[0] - (left + width)),
        "top": abs(point[1] - top),
        "bottom": abs(point[1] - (top + height)),
    }
    return min(distances, key=distances.get)


def _static_checks(html: str, graph: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    failures=[]
    def fail(check, **extra): failures.append({"check":check, **extra})
    root_count=len(re.findall(r'<[^>]+data-flowchat-root(?:[ >])', html))
    if root_count != 1: fail("root_mount_count",actual=root_count,required=1)
    if re.search(r"<iframe\b|\bsrcdoc\s*=|file://", html, re.I):
        fail("nested_embed_forbidden")
    for key in ("nodes","edges"):
        ids=[str(item.get("id","")) for item in graph.get(key,[])]
        if not ids: fail("empty_graph", component=key)
        for item,count in Counter(ids).items():
            if count>1 or not item: fail("duplicate_graph_id", component=key,id=item)
    nodes={str(n["id"]):n for n in graph.get("nodes",[])}
    edges={str(e["id"]):e for e in graph.get("edges",[])}
    for node in nodes.values():
        for key in ("x","y","width","height"):
            if not math.isfinite(float(node[key])): fail("nonfinite_node",node=node["id"])
        if float(node["width"])<=0 or float(node["height"])<=0: fail("invalid_node_size",node=node["id"])
    paths=_paths(html)
    diamonds=[n for n in nodes.values() if n.get("shape")=="diamond"]
    min_edge=max(DEFAULT_MIN_EDGE,max((_diamond_side(n) for n in diamonds),default=0))
    metrics={"node_count":len(nodes),"edge_count":len(edges),"min_edge_length":min_edge,"min_arrow_segment":DEFAULT_MIN_ARROW,"backtracking_count":0,"opposite_overlap_count":0,"crossing_count":0,"max_edge_stroke_width":MAX_EDGE_STROKE_WIDTH,"max_arrow_marker_size":MAX_ARROW_MARKER_SIZE}
    segments={}
    strokes=set()
    marker_defs={m.group(1):m.group(0) for m in re.finditer(r'<marker\b[^>]*id="([^"]+)".*?</marker>',html,re.S)}
    for edge_id,edge in edges.items():
        points=paths.get(edge_id,[])
        source,target=nodes.get(str(edge.get("source"))),nodes.get(str(edge.get("target")))
        if not source or not target: fail("unknown_edge_node",edge=edge_id);continue
        if len(points)<2: fail("route_missing",edge=edge_id);continue
        segments[edge_id]=list(zip(points,points[1:]))
        lengths=_segment_length(points)
        for index,(a,b) in enumerate(segments[edge_id]):
            if not _axis_aligned(a,b): fail("diagonal_segment",edge=edge_id,segment=index)
            if lengths[index]<NEAR_ZERO: fail("near_zero_segment",edge=edge_id,segment=index)
            elif lengths[index]<MIN_SEGMENT: fail("segment_too_short",edge=edge_id,segment=index,actual=lengths[index])
            for node in nodes.values():
                if node["id"] in {source["id"], target["id"]}:
                    continue
                if _hits(a,b,node): fail("edge_through_node",edge=edge_id,node=node["id"],segment=index)
        for i,(a,b,c) in enumerate(zip(points,points[1:],points[2:])):
            u=(b[0]-a[0],b[1]-a[1]);v=(c[0]-b[0],c[1]-b[1])
            if abs(u[0]*v[1]-u[1]*v[0])<1e-6 and u[0]*v[0]+u[1]*v[1]<0:
                fail("route_backtracks",edge=edge_id,vertex=i+1);metrics["backtracking_count"]+=1
        if sum(lengths)+1e-5<min_edge: fail("edge_too_short",edge=edge_id,actual=sum(lengths),required=min_edge)
        if lengths[-1]+1e-5<DEFAULT_MIN_ARROW: fail("arrow_segment_too_short",edge=edge_id,actual=lengths[-1])
        for role,node,point,near in (("source",source,points[0],points[1]),("target",target,points[-1],points[-2])):
            if not _on_boundary(node,point): fail(role+"_not_on_boundary",edge=edge_id,point=point)
            side=edge.get(role+"_side")
            if not side and node.get("shape","rect") == "rect":
                left,top,w,h=(float(node[k]) for k in ("x","y","width","height"))
                distances={"left":abs(point[0]-left),"right":abs(point[0]-(left+w)),"top":abs(point[1]-top),"bottom":abs(point[1]-(top+h))}
                side=min(distances,key=distances.get)
            if side:
                normals={"left":(-1,0),"right":(1,0),"top":(0,-1),"bottom":(0,1)}
                normal=normals.get(side)
                vec=(near[0]-point[0],near[1]-point[1])
                if not normal or vec[0]*normal[0]+vec[1]*normal[1]<=0 or abs(vec[0]*normal[1]-vec[1]*normal[0])>1e-5:
                    fail(role+"_direction_wrong",edge=edge_id,side=side)
                if normal and node.get("shape","rect")=="rect":
                    expected={"left":float(node["x"]),"right":float(node["x"])+float(node["width"]),"top":float(node["y"]),"bottom":float(node["y"])+float(node["height"])}[side]
                    if abs(point[0 if side in {"left","right"} else 1]-expected)>TOLERANCE: fail(role+"_port_side_wrong",edge=edge_id)
                    along=point[1]-float(node["y"]) if side in {"left","right"} else point[0]-float(node["x"])
                    size=float(node["height"] if side in {"left","right"} else node["width"])
                    if min(along,size-along)<13: fail("port_on_rounded_corner",edge=edge_id,role=role)
            distance=max(_length(point,near),1e-6)
            probe=[point[k]+(near[k]-point[k])*min(5,distance/2)/distance for k in (0,1)]
            if _inside(node,probe): fail(role+"_direction_wrong",edge=edge_id)
        if _axis_aligned(points[0],points[-1]) and len(points)>2:
            a,b=points[0],points[-1]
            startvec=(points[1][0]-a[0],points[1][1]-a[1]);endvec=(b[0]-points[-2][0],b[1]-points[-2][1]);direct=(b[0]-a[0],b[1]-a[1])
            forward=lambda v: abs(v[0]*direct[1]-v[1]*direct[0])<1e-5 and v[0]*direct[0]+v[1]*direct[1]>0
            if forward(startvec) and forward(endvec) and not any(_hits(a,b,n) for n in nodes.values()) and any(abs((p[0]-a[0])*direct[1]-(p[1]-a[1])*direct[0])>1e-5 for p in points):
                # Occupied opposing lanes justify an explicit outer route, but a label alone does not.
                conflict=any(_overlap(a,b,c,d) is False for other,ss in segments.items() if other!=edge_id for c,d in ss)
                if not conflict: fail("unnecessary_bend_aligned_ports",edge=edge_id)
        match=re.search(r'data-edge="'+re.escape(edge_id)+r'"[^>]*>\s*<path class="flowchat-edge"[^>]*>',html)
        attrs=_attrs(match.group(0)) if match else {}
        stroke=attrs.get("stroke","");strokes.add(stroke)
        try:
            stroke_width=float(attrs.get("data-stroke-width","nan"))
        except ValueError:
            stroke_width=float("nan")
        if not math.isfinite(stroke_width) or stroke_width>MAX_EDGE_STROKE_WIDTH:
            fail("edge_stroke_too_thick",edge=edge_id,actual=stroke_width,maximum=MAX_EDGE_STROKE_WIDTH)
        marker_id=re.fullmatch(r'url\(#([^)]*)\)',attrs.get("marker-end",""))
        marker=marker_defs.get(marker_id.group(1),"") if marker_id else ""
        ma=_attrs(marker.split(">",1)[0])
        if not marker or ma.get("orient")!="auto": fail("arrow_marker_missing",edge=edge_id)
        else:
            try:
                marker_width=float(ma.get("markerWidth","nan")); marker_height=float(ma.get("markerHeight","nan"))
            except ValueError:
                marker_width=marker_height=float("nan")
            if not math.isfinite(marker_width) or not math.isfinite(marker_height) or marker_width>MAX_ARROW_MARKER_SIZE or marker_height>MAX_ARROW_MARKER_SIZE:
                fail("arrow_marker_too_large",edge=edge_id,width=marker_width,height=marker_height,maximum=MAX_ARROW_MARKER_SIZE)
            coords=re.search(r'<path[^>]*d="M\s*0[ ,]+0\s+L\s*([0-9.]+)[ ,]+([0-9.]+)\s+L\s*0[ ,]+([0-9.]+)\s+Z"',marker)
            if not coords or abs(float(ma.get("refX","-1"))-float(coords.group(1)))>0.01: fail("arrow_tip_not_at_endpoint",edge=edge_id)
            if stroke not in re.findall(r'fill="([^"]+)"',marker): fail("arrow_color_mismatch",edge=edge_id)
    if len(strokes)>1: fail("edge_palette_not_unified",colors=sorted(strokes))
    edge_markup = {edge_id: _edge_group_markup(html, edge_id) for edge_id in edges}
    edge_sides = {edge_id: {role: _edge_side(edge_id, edge, role, nodes, paths) for role in ("source", "target")} for edge_id, edge in edges.items()}
    items=list(segments.items())
    for i,(id1,segs1) in enumerate(items):
        for id2,segs2 in items[i+1:]:
            e1,e2=edges[id1],edges[id2]
            for a,b in segs1:
                for c,d in segs2:
                    overlap=_overlap(a,b,c,d)
                    if overlap is not None:
                        # Collinear segments with opposite directions are
                        # never mergeable, even when they share a node.
                        if not overlap:
                            fail("opposite_direction_overlap",edges=[id1,id2]);metrics["opposite_overlap_count"]+=1
                        else:
                            same_source_side=(e1.get("source")==e2.get("source") and edge_sides[id1]["source"] and edge_sides[id1]["source"]==edge_sides[id2]["source"])
                            same_target_side=(e1.get("target")==e2.get("target") and edge_sides[id1]["target"] and edge_sides[id1]["target"]==edge_sides[id2]["target"])
                            if not (same_source_side or same_target_side):
                                fail("unrelated_edges_overlap",edges=[id1,id2])
                    crossing=_cross(a,b,c,d)
                    if crossing:
                        metrics["crossing_count"]+=1
                        # A crossing is deliberate when either route carries an
                        # edge-bound marker.  Looking in the complete document
                        # lets an unrelated edge accidentally satisfy the gate.
                        if 'data-crossing="true"' not in edge_markup.get(id1, "") and 'data-crossing="true"' not in edge_markup.get(id2, ""):
                            fail("crossing_not_distinguished",edges=[id1,id2],point=crossing)
    markup={m.group(1):m.group(0) for m in re.finditer(r'<g class="flowchat-node[^>]*data-node="([^"]+)".*?</g>',html,re.S)}
    for node_id,node in nodes.items():
        content=markup.get(node_id,"")
        if not content: fail("node_markup_missing",node=node_id);continue
        for token in ('data-text-region="node"','data-text-align="center"','text-anchor="middle"','dominant-baseline="middle"'):
            if token not in content: fail("text_not_centered",node=node_id);break
        if node.get("shape")=="diamond" and 'data-diamond-text="centered"' not in content: fail("diamond_text_not_centered",node=node_id)
        # Static check is conservative; actual text boxes require browser evidence.
        line_count=max(1,len(str(node.get("label","")).splitlines()))
        if line_count*18 > float(node["height"])-8: fail("text_height_overflow",node=node_id)
    return failures,metrics


def _interaction_checks(html: str) -> dict[str, bool]:
    checks = {
        "drag": bool(re.search(r"pointerdown|pointermove|setPointerCapture", html)),
        "wheel_zoom": bool(re.search(r"addEventListener\(['\"]wheel", html)),
        "touch_pinch": bool(re.search(r"pointerType===['\"]touch|pinchDistance|activePointers", html)),
        "fit_view": bool(re.search(r"data-action=fit|ResizeObserver|const fit", html)),
    }
    return checks


def _browser_receipt(path: Path | None, artifact_sha256: str) -> tuple[str, dict[str, Any]]:
    if path is None:
        return "blocked", {"check": "browser_receipt_required", "reason": "browser receipt for this exact artifact is required"}
    data=json.loads(path.read_text(encoding="utf-8"))
    required=["loaded","console_errors","console_warnings","drag","wheel_zoom","fit_view","node_click","stage_subflow_click","subflow_transition_visible","subflow_loop_visible","subflow_output_visible","overview_restore","architecture_view","architecture_nodes_visible","architecture_node_click","arrows_visible","geometry_verified","text_bounds_verified","edge_style_verified"]
    missing=[key for key in required if key not in data]
    if missing: return "blocked", {"missing":missing}
    if data.get("artifact_sha256")!=artifact_sha256:
        return "blocked", {"check":"browser_receipt_artifact_mismatch","expected":artifact_sha256,"observed":data.get("artifact_sha256")}
    if not str(data.get("url","")).startswith(("http://","https://")):
        return "blocked", {"check":"browser_receipt_not_http"}
    if data.get("console_errors")!=0 or data.get("console_warnings")!=0 or not all(data.get(key) is True for key in required if key not in {"console_errors","console_warnings"}):
        return "blocked",data
    return "pass",data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate standalone Flowchat with its local Harness")
    parser.add_argument("html", type=Path)
    parser.add_argument("--browser-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    html = args.html.read_text(encoding="utf-8")
    try:
        graph = _load_graph(html)
        failures, metrics = _static_checks(html, graph)
    except Exception as exc:
        failures, metrics = [{"check": "harness_input", "error": str(exc)}], {}
    interactions = _interaction_checks(html)
    for name, passed in interactions.items():
        if name != "browser_validation_hook" and not passed:
            failures.append({"check": f"interaction_hook_{name}"})
    artifact_sha256 = hashlib.sha256(args.html.read_bytes()).hexdigest()
    browser_status, browser_details = _browser_receipt(args.browser_receipt, artifact_sha256)
    report = {
        "schema_version": "flowchat-local-harness.v2",
        "artifact": str(args.html),
        "artifact_sha256": artifact_sha256,
        "static_status": "blocked" if failures else "pass",
        "status": "pass" if not failures and browser_status == "pass" else "blocked" if failures or browser_status == "blocked" else "not_run",
        "checks": {"geometry": metrics, "interaction_hooks": interactions, "browser_validation": browser_status},
        "failures": failures,
        "browser_details": browser_details,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
