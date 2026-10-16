---
name: flowchat
description: "Flowchat · 流程图生成器：从 graph JSON 生成单文件、自包含、可直接用浏览器打开的流程图 HTML 页面。Use when the user asks for a 流程图 / 流程可视化 / 流程页面 / flow diagram / process map / pipeline visualization, or provides nodes/edges JSON to render."
---

# Flowchat · 流程图渲染器

把 graph JSON 变成**一个自包含 HTML 文件**，浏览器直接打开即可。不用 iframe、不用 srcdoc、无外链、无构建。

## When to use

- 用户要一个可浏览的流程图 / 流程 / 流水线 / 架构页面。
- 用户给了 `nodes` + `edges` 数据，或描述了一个可以建模成节点 + 边的流程。
- 用户想用自己的配色重绘一个已有流程页面。

**不要**用它产出图片、Mermaid 片段或嵌入式组件——这里的交付物是独立的 HTML 文件。

代码快照：`c46b22b`（https://github.com/vinterye/flowchat-skill/commit/c46b22b3a85e0428b2f9846b4dcb938ec46c523b）。枚举一律以该快照里的 `data/type-registry-v1.json` 为准。

## 铁律（按此顺序执行）

1. **先校验，再生成。** `validate_graph.py` 是硬前置，不是可选项。边的端点指向不存在的节点时，渲染器会**静默丢边**——你会拿到一个看着正常但内容缺失的页面。
2. **不要猜测枚举。** 节点类型、边类型、状态一律以 `data/type-registry-v1.json` 为准（49 / 19 / 13）。文档里没写的类型就是不存在的类型。
3. **几何不达标就是失败，不是警告。** 生成命令返回 2 时**没有写文件**，修图重跑，不要手工改 HTML。
4. **不要自己造业务对象。** 容器靠 `children` 关联已有节点，引用靠 `drilldown` 指向已注册流程。输入里没有的东西，图上就不该出现。

## 三步命令

```bash
# 1. 校验（exit 1 = 图有错，已打印字段与边 id；exit 2 = 文件缺失或 JSON 非法）
python3 scripts/validate_graph.py path/to/graph.json

# 2. 生成（exit 2 = 几何不达标，未写文件，已打印是哪条边、怎么修）
python3 scripts/generate_flowchat.py \
  --graph path/to/graph.json \
  --theme path/to/theme.json \
  --title "流程标题" \
  --output path/to/flowchat.html

# 3. 几何门禁
python3 harness/flowchat_local_harness.py path/to/flowchat.html --output out/harness-report.json
```

`--graph` 省略则渲染内置 22 节点示例图；`--theme` 省略则用内置浅色主题。

判读第 3 步：看 `static_status` 字段，**不要看退出码**。没有浏览器回执时 `status` 恒为 `blocked`、退出码恒为 2，这是证据门禁的设计，不是几何失败。

```bash
python3 -c "import json;print(json.load(open('out/harness-report.json'))['static_status'])"
```

需要完整浏览器证据时才用 `scripts/self_check_flowchat.py`（`--browser-receipt` 必填）。

## 输入契约

顶层：`nodes`（必填非空）、`edges`、`viewBox`、`subflows`、`layout`、`dependency_contract`。

| 层级 | 字段 |
| --- | --- |
| 节点 | `id` `label` `type`（`kind` 为兼容别名）`status` `raw_status` `visual_status` `x` `y` `width` `height` `order` `children` `drilldown` `input_refs` `output_refs` `context_refs` |
| 边 | `id` `source` `target` `type` `status` `source_port` `target_port` `source_side` `target_side` `routing` `route_points` `crossing` `fanout_group` `fanin_group` `label` `dependency` |
| 子流程 | `subflows.<stage-node-id>`：`title` `entry` `next` `loop` `nodes` `edges` |

**snake_case 与 camelCase 都接受**：`source_port`/`sourcePort`、`route_points`/`routePoints`/`path`、`dependencyContract`。Graph V2 适配器输出 camelCase，不需要先转换。

### 端口

`left` `right` `top` `bottom`，可选三车道 `-1/-2/-3`（落在该边 1/3、1/2、2/3 处）。扇出扇入用编号车道，多条边才会落在稳定且互不重叠的锚点上；不写车道则是中心端口。

### 路由

**普通近邻边不要给 `route_points`**，交给自动路由选直线或少弯折路径。只有回环、绕行、外框绕行、明确交叉才保留显式 `route_points`，并标 `crossing: true`。

相对位置决定端口：水平中心距离占优走 `left`/`right`，垂直占优走 `top`/`bottom`。违背这个关系的显式端口会被 harness 判 `relative_port_mismatch`。完整阈值见 [references/routing-rules.md](references/routing-rules.md)。

### 状态

用 `completed` `active` `pending` `blocked` `return` 让动画跟着运行状态走。原始运行值（`unknown` `candidate` `not_run` `not_implemented`）留在 `raw_status`，`visual_status` 只管视觉分类。**状态不改变节点类型**：类型填充、形状、图标是稳定语义。

### 因果边契约（可选）

图声明 `dependency_contract: "causal-v1"` 后，只有把一个 source output 接到一个 target input 的依赖才画成边：

```json
{"dependency": {"kind": "input", "output_ref": "requirements:analysis", "input_ref": "requirements:analysis"}}
```

两个节点共享同一个 run / stage / policy **不是**依赖，放 `context_refs`，不要画边。

## V2 证据绑定拓扑（可选）

两级 Orchestrator Hub 拓扑用单独入口，不从单个 JSON 凭空造图：

```bash
python3 scripts/generate_v2_topology.py \
  --agents /path/to/agents.json \
  --capabilities /path/to/capabilities.json \
  --relationships /path/to/relationships.json \
  --runtime /path/to/runtime-state.json \
  --output out/flowchat-v2.html

python3 scripts/validate_v2_topology.py out/flowchat-v2.html --output out/v2-report.json
```

规则：Stage 是业务对象，不能渲染成 Agent；没有证据的关系不画边；注册表投影永远不是运行时证据；`blocked`/`not_run`/`candidate`/`unknown` 必须保持各自可辨。注册表不在默认位置时显式传参，或设置 `FLOWCHAT_AIOS_ROOT`。

## 硬约束（生成结果恒定满足）

- 边长 ≥ 90 px，末端箭头段 ≥ 75 px
- 无零长 / 反向 / 斜向线段；端点吸附到声明的节点边
- 连线 ≤ 2 px，箭头 ≤ 5×5，单一连线配色
- 文字居中不溢出，菱形文字居中，不穿过中间节点
- 状态用虚线与动画表达，**不靠加粗线条或放大箭头**
- 渲染器**拒绝**非法路由，不会补一条反向折线让箭头骗人

## 已知边界

- **菱形节点（`gate` / `decision`）配编号车道端口**会触发 `source_not_on_boundary`：渲染器把车道投影到矩形边界，harness 要求端点落在菱形边上。改用非菱形类型（`human_review` / `review`）或显式 `route_points`。这是既有不一致，不要改几何内核来绕过。
- 生成的 HTML **不要手工改**。改图或改主题重新生成。

## 主题

可选 JSON，覆盖 [references/theme.md](references/theme.md) 里的任意令牌，未提供的用内置默认值。只覆盖令牌，不要用全局选择器改写宿主页面。
