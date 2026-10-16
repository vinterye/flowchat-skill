# Flowchat 主题令牌

主题文件是 JSON 对象，未提供的字段使用白底中性默认值：

```json
{
  "canvas": "linear-gradient(135deg,#f8faff,#f1f2fb)",
  "panel": "rgba(255,255,255,.62)",
  "node_fill": "#ffffff",
  "node_stroke": "#9aabbd",
  "diamond_fill": "#f3f6fa",
  "square_fill": "#f1edff",
  "agent_fill": "#f1edff",
  "agent_stroke": "#7657d9",
  "dispatch_fill": "#f6f1ff",
  "dispatch_stroke": "#4a68e8",
  "review_fill": "#fff3e8",
  "review_stroke": "#d9983a",
  "feedback_fill": "#eef7ff",
  "blocked_fill": "#fff3f5",
  "blocked_stroke": "#ff6f7d",
  "phase_pre_stroke": "#4a68e8",
  "phase_mid_stroke": "#7657d9",
  "phase_post_stroke": "#3ea77a",
  "phase_unknown_stroke": "#98a5bd",
  "ready_stroke": "#3ea77a",
  "candidate_stroke": "#d9983a",
  "needs_review_stroke": "#98a5bd",
  "edge": "#98a5bd",
  "edge_completed": "#72c3a2",
  "edge_active": "#4a68e8",
  "edge_pending": "#98a5bd",
  "edge_blocked": "#d75a67",
  "edge_return": "#d75a67",
  "edge_feedback": "#3ea77a",
  "edge_review": "#d9983a",
  "text": "#172033",
  "muted": "#7b8495",
  "accent": "#4a68e8",
  "edge_stroke_width": "2",
  "arrow_marker_width": "5",
  "arrow_marker_height": "5",
  "arrow_marker_ref_x": "4",
  "arrow_marker_ref_y": "2"
}
```

## P2 类型覆盖、尺寸与多主题

类型颜色可通过 `type_colors` 覆盖，类型边框可通过 `type_strokes` 覆盖。渲染器先使用主题覆盖，再回退到类型注册表；状态仍通过边框、Badge、透明度和虚线表达，不替换类型填充。

```json
{
  "type_colors": {"agent": "#dbeafe", "human_review": "#fef3c7"},
  "type_strokes": {"agent": "#1d4ed8", "human_review": "#92400e"}
}
```

节点类型使用注册表中的 `size` 预设：`compact`、`regular`、`wide`、`tall`。节点可以显式提供 `width` / `height` 覆盖预设；未提供时按类型预设生成，保证控制节点、Agent、治理节点和容器节点的尺寸有稳定规则。

P2 的视觉回归矩阵覆盖注册表中的每个节点类型与 `completed`、`active`、`pending`、`blocked`、`unknown`、`not_run`、`candidate` 状态。通过条件是类型的 `shape`、`icon`、填充语义保持稳定，状态只改变状态层样式。高对比主题示例见 [theme-high-contrast.json](../data/theme-high-contrast.json)。

项目主题可以继续覆盖这些令牌。默认质感对齐 `cockpit-home-v1.html`：浅灰紫渐变画布、白色半透明毛玻璃面板、`17px` 左右圆角和柔和蓝紫阴影。前置阶段使用 `#4a68e8`，中置阶段使用 `#7657d9`，后置阶段使用 `#3ea77a`，未知阶段使用 `#98a5bd`；`ready`、`candidate`、`needs_review` 分别使用 `#3ea77a`、`#d9983a`、`#98a5bd`。节点填充和图标表达类型，状态只覆盖边框、Badge、透明度和动画；`completed`、`pending`、`unknown` 不覆盖类型填充色。连线统一使用 `edge` 令牌；`edge_completed`、`edge_active` 等旧状态令牌仅为兼容输入保留，不能让不同状态产生不同连线颜色。Execution Truth 的 `truth_type` 是证据层覆盖，必须单独声明，不能当作普通运行状态。

项目只能覆盖主题令牌，不要通过全局 `.node`、`.edge` 等选择器改写宿主页面。独立 HTML 使用 `flowchat` 命名空间；接入项目时继续遵守项目自己的样式隔离和门禁规则。

连线默认使用 `2px` 细线和 `5×5` 箭头，另有 `14px` 透明命中区。需要强调状态时使用虚线或动画，不通过加粗线条或放大箭头表达状态。选中的连线显示两个实心端点；端点悬停时放大并加粗白色描边。
