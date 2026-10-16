# Flowchat · 流程图生成器

**Flowchat** 是一个流程图生成器：从 graph JSON 生成**单个、自包含、双击即可打开**的流程图 HTML 页面。
无外部依赖、无 CDN、无构建步骤、纯 Python 3.10+ 标准库。

产出页面自带：流程视图 / 架构视图 / 时序视图、节点点击、阶段子流程、边状态动画、事件日志、拖拽、滚轮缩放、双指缩放钩子、自适应视图、键盘导航与 ARIA 标注。

<p align="center">
  <img src="docs/capability-map.png" alt="Flowchat 能力地图" width="100%">
  <br>
  <sub>能力地图：49 节点类型 / 19 边类型 / 13 状态 / 12 形状 / 4 尺寸 / 12 端口位置</sub>
  <br>
  <a href="docs/enum-spectrum.html"><b>→ 下载后用浏览器打开 docs/enum-spectrum.html 查看完整枚举参考与真实渲染效果</b></a>
</p>

## 快速开始

```bash
# 1. 校验输入（必做：悬空引用会直接报错，不会静默漏画）
python3 scripts/validate_graph.py examples/minimal.graph.json

# 2. 生成页面
python3 scripts/generate_flowchat.py \
  --graph examples/minimal.graph.json \
  --theme examples/theme.example.json \
  --title "交付流程" \
  --output out/flowchat.html

# 3. 几何门禁
python3 harness/flowchat_local_harness.py out/flowchat.html --output out/harness-report.json
```

打开 `out/flowchat.html` 就是结果。`--theme` 可省略（用内置浅色主题）。**`--graph` 必填**——内置的 22 节点示例图当前无法通过自身的几何门禁（见"已知边界"），请以 [examples/minimal.graph.json](examples/minimal.graph.json) 为起点改你自己的图。

## 安装

把整个目录放到你的 agent 客户端的 skills 目录下即可，**不需要任何安装命令**。

| 客户端 | 放置路径 |
| --- | --- |
| Codex | `~/.codex/skills/flowchat/` |
| Claude Code | `~/.claude/skills/flowchat/` |
| Cursor | `~/.cursor/skills/flowchat/` |
| 其他 / 手动 | 任意位置，cd 进去直接跑命令 |

```bash
git clone https://github.com/vinterye/flowchat-skill.git ~/.codex/skills/flowchat
```

**代码快照**：本 README 描述的代码对应 commit [`e74c2c1`](https://github.com/vinterye/flowchat-skill/commit/e74c2c186b011d8dc8e2369a8c8985f0aa0bc82e)。
该 SHA 冻结的是代码与数据；文档自身的后续润色不在其中。

## 类型系统

枚举不是文档里的约定，而是随包发布的 [data/type-registry-v1.json](data/type-registry-v1.json)——渲染器、校验器、测试三处读的是同一份文件，所以文档不会和实现漂移。

| 维度 | 数量 | 说明 |
| --- | --- | --- |
| 节点类型 `type` | 49 | 5 个族：Flow Control / Execution / Data-Artifact / Governance / Structure |
| 边类型 `type` | 19 | `main` `flow` `return` `retry` `loop` `parallel` `handoff` `human_review` `feedback` … |
| 状态 `status` | 13 | `completed` `active` `pending` `blocked` `return` `review` `candidate` `unknown` `not_run` … |
| 形状 `shape` | 12 | 由 type 决定；`kind` 作为 `type` 的兼容别名保留 |
| 尺寸预设 | 4 | `compact` 132×56 / `regular` 156×88 / `wide` 220×88 / `tall` 180×120 |
| 端口 | 12 | `left/right/top/bottom` × 三车道 `-1/-2/-3`，车道落在该边的 1/3、1/2、2/3 |

- **状态靠虚线与动画表达**，不改线宽、不放大箭头：`completed`/`pending` 实线，`return`/`retry` 虚线或动画。
- **原始运行状态**（`unknown` `candidate` `not_run` `not_implemented`）保留在 `raw_status`，`visual_status` 只管视觉分类——渲染器从不把"跑没跑"改写成"跑过了"。
- **扇出用 `fanout_group`、扇入用 `fanin_group`**：1→N 共用一条主干 + 一条分流走廊，N→1 共用汇流走廊，端口自动错开车道。

完整枚举与真实渲染效果见 [docs/enum-spectrum.html](docs/enum-spectrum.html)（下载后浏览器打开）。

## 校验器在拦什么

`validate_graph.py` 是生成前的硬前置。它不只是 schema 检查，而是拦那些**"页面看着正常但其实错了"**的情况：

| 检查 | 级别 | 为什么 |
| --- | --- | --- |
| `source`/`target` 指向不存在的节点 | ERROR | 渲染器会静默丢边，你拿到一个缺边的页面 |
| 重复 node/edge id | ERROR | 后写的覆盖先写的，图少内容 |
| 端口不是 `side` 或 `side-1/2/3` | ERROR | 端点会落在节点外 |
| `route_points`/`routePoints`/`path` 少于两点或坐标非数值 | ERROR | 路由直接崩 |
| `dependency_contract: causal-v1` 下缺 `dependency` / 用 context 当边 | ERROR | 共享上下文不是依赖，不该画成边 |
| `subflows` 的 key 不是声明过的节点 id / nodes 为空 | ERROR | 子流程点开是空的 |
| 未知 `type` / `status` / `edge type` | WARN | 渲染器保留原值，但你可能拼错了 |

同时接受 **snake_case 与 camelCase 两种写法**（`source_port` / `sourcePort`、`route_points` / `routePoints` / `path`），因为 Graph V2 适配器输出 camelCase。未知枚举按值聚合输出，28 节点的图不会刷出十几行重复告警。

## V2 证据绑定拓扑（可选）

两级 Orchestrator Hub 拓扑走单独入口，不从单个 JSON 凭空造图：

```bash
python3 scripts/generate_v2_topology.py \
  --agents /path/to/agents.json \
  --capabilities /path/to/capabilities.json \
  --relationships /path/to/relationships.json \
  --runtime /path/to/runtime-state.json \
  --output out/flowchat-v2.html

python3 scripts/validate_v2_topology.py out/flowchat-v2.html --output out/v2-report.json
```

生成器记录每个注册表的 SHA-256 与来源指针，**没有证据的关系不画边**，注册表投影永远不会变成运行时证据。
注册表不在默认位置时，显式传 `--agents/--capabilities/--relationships`，或设置 `FLOWCHAT_AIOS_ROOT`。

## 几何是内建保证的

渲染器拒绝非法路由，而不是补一个反向折线让箭头骗人。生成结果恒定满足：

- 边长 ≥ 90 px，末端箭头段 ≥ 75 px
- 无零长 / 反向 / 斜向线段，端点吸附到声明的节点边
- 相对位置决定端口：水平距离占优走 left/right，垂直占优走 top/bottom
- 连线 ≤ 2 px，箭头 ≤ 5×5，单一连线配色
- 文字居中且不溢出，菱形文字居中，不穿过中间节点

## 退出码

| 命令 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `validate_graph.py` | 通过 | 图有错误（已打印具体字段与边 id） | 文件不存在或 JSON 非法 |
| `generate_flowchat.py` | 已生成 | — | 几何不达标，未写文件（已打印是哪条边、怎么修） |
| `flowchat_local_harness.py` | 全部通过 | — | 静态失败，**或**缺少浏览器回执 |

**harness 退出码 2 不等于几何失败**：它是证据门禁，没有浏览器回执时 `status` 恒为 `blocked`、退出码恒为 2。判断几何看报告里的 `static_status`：

```bash
python3 -c "import json;print(json.load(open('out/harness-report.json'))['static_status'])"
```

需要完整浏览器证据时用 `scripts/self_check_flowchat.py`（`--browser-receipt` 必填）。

## 已知边界

- **内置 22 节点示例图（省略 `--graph`）当前渲染失败**：`dispatch-research` 边的扇出走廊起点用了车道坐标 (543.3,410)、而走廊点取主干 x=580，产生斜段，渲染器按设计拒绝。命令会打印 `edge 'dispatch-research': route segment 0 must be axis aligned` 并返回 2。这是渲染器 fanout trunk 逻辑的既有缺陷，本次未改几何内核；请显式提供 `--graph`。
- **菱形节点（`gate` / `decision`）配编号车道端口**会被 harness 判 `source_not_on_boundary`：渲染器把车道投影到矩形边界，而 harness 要求端点落在菱形边上。规避方式是用非菱形类型（`human_review` / `review`），或给这类边显式 `route_points`。这是渲染器与门禁之间的既有不一致，未在本次改动中修改几何内核。
- `data/p1-p2-test-graph.json` 的 `subflows.development` 是空壳（`nodes` 为空、key 不是声明的节点），校验器会如实报错。它是测试夹具，不是示例。

## 目录

```
SKILL.md                           # agent 读取的行为规则（契约、硬约束、命令）
README.md
data/type-registry-v1.json         # 49/19/13/4/12 枚举的唯一事实源
data/topology_projection.py        # V2 投影构建（事实保全，不造业务对象）
data/*.json                        # 测试图、高对比主题、preservation map
scripts/validate_graph.py          # 生成前输入校验（注册表驱动）
scripts/generate_flowchat.py       # 渲染器
scripts/self_check_flowchat.py     # 完整门禁（需浏览器回执）
scripts/generate_v2_topology.py    # V2 证据绑定拓扑
scripts/validate_v2_topology.py    # V2 快照校验
scripts/{build_topology_projection,projection_to_flowchat_graph,
         execution_truth_to_flowchat_graph,validate_execution_truth,
         augment_enum_report}.py   # 投影 / 执行事实 / 枚举报告工具链
harness/flowchat_local_harness.py  # 几何 + 路由契约 + 交互钩子门禁
harness/checks_visual.py           # 视口边界与边样式检查
references/{theme.md,routing-rules.md}  # 主题令牌 / 完整路由规则
tests/                             # 7 个 pytest 文件（routing / dependency / p0 / p1-p2 / projection）
examples/minimal.graph.json        # 可直接跑通并通过门禁的最小示例
examples/theme.example.json        # 主题覆盖示例
tools/render_capability_map.py     # 重生成 docs/capability-map.{svg,png}
tools/build_enum_atlas.py          # 合并能力地图与枚举全谱
docs/                              # capability-map.{png,svg}、enum-spectrum.html
```

## License

MIT — 见 [LICENSE](LICENSE)。
