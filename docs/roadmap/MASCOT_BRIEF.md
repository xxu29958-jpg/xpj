# 小票夹吉祥物角色 Brief —「夹夹」

> 状态：proposed（2026-06-13，用户拍板「夹子拟人 + 我写 brief 你拿去 AI 出图」）。
> 用途：① 喂 AI 图像生成（Midjourney / 即梦等）出专业角色原画；② 之后 Rive 绑 10 个交互状态的设计真相源；③ 三端（Android / `/web` / `/owner`）共用同一角色。
> 实现技术栈见 [ADR-0048](../DECISIONS/0048-rive-mascot-animation.md)（Rive 状态机 + 运行时换色）。
> 外部参照边界（[[ENGINEERING_RULES §14]]）：可参考 Duolingo Duo 的**工艺水准与情绪设计方法**，但**夹夹是原创角色**，不照搬任何已知吉祥物的造型/素材/商标。

## 1. 概念与记忆钩

- **主角**：拟人的**长尾夹 / 燕尾夹**（binder clip）——直接呼应产品名「小票**夹**」。它夹着一张小票当随身小物。
- **记忆钩（一眼记住的标志）**：顶部两条**会弹的金属丝手臂**。这是夹夹的专属表情器官（对标 Duo 的眉毛）——挥手、抱住、抛硬币、捂眼、伸懒腰全靠它，silhouette 独特、动画表现力强。
- **一句话人设**：稳稳夹住你每一笔的小管家——可靠、温暖、闲时有点慵懒，遇事手臂「boing」一下弹起来干活。可靠感 + 萌感，正合理财助手要的信任 + 愉悦。

## 2. 可爱公式（baby-schema，硬规格）

- 头身比 ≈ **1:1**，整体**圆胖**，夹子梯形身体把棱角全磨圆。
- **大而低的圆眼睛**：贴近水平中线，带一点高光（用 background token 做高光点，三主题都对比）。
- **腮红** + **小嘴**（小弧线 / 小「w」，无牙）。
- 四肢极简：两条金属丝手臂（细弧线）+ 两只小脚墩；身体本身无多余细节。
- 一处暖色点缀（腮红 / 夹口），其余克制。

## 3. 配色与三主题（token 驱动，硬约束）

- **禁止烤死颜色**。所有色走 token，Rive 运行时绑定，随 **paper / mono / midnight** 自动换：
  - 身体主色：随主题中性暖面；描边：text 强色；小票：纸面浅 token；腮红/夹口：暖强调 token。
- 三主题都要可读：paper（暖奶油）、mono（灰阶）、midnight（深色）。silhouette 在三主题下都要立得住。

## 4. 表情 / 交互状态谱（10 态，绑真实事件）

| # | 触发事件 | 夹夹反应 | 手臂动作 |
|---|---|---|---|
| 1 | 空态闲置 | 打盹（呼吸 + 偶尔眨眼 + zzz） | 垂下放松 |
| 2 | 进入空账本 | 醒来招手 | 一臂上扬挥手 |
| 3 | **确认一笔** | 蹦一下 + 撒爱心（「夹住」成功） | 双臂 boing 上弹 |
| 4 | 忽略 / 驳回 | 撇嘴转头 | 双臂垂、偏头 |
| 5 | **目标达成 / 欠款清零** | **撒花庆祝**（补上里程碑庆祝缺口 [[project_milestone_feedback_gap]]） | 双臂抛撒纸屑 |
| 6 | 下拉刷新 | 伸懒腰、身体拉伸 | 双臂向上伸展 |
| 7 | 戳它一下 | 身体抖、偷笑 | 双臂乱挥 |
| 8 | 加载 / 同步 | 抱硬币转圈 / 抛接 | 双臂抛接硬币 |
| 9 | 大额 / 超支提醒 | 捂眼吃惊 + 汗滴 | 一臂捂眼 |
| 10 | 搜索无果 | 举放大镜耸肩 | 一臂举镜、一臂摊 |

> 落地分批：v1 先做 1/2/3/5/10（空态 + 确认 + 庆祝 + 搜索无果，覆盖最高频与最高价值）；6/7/8/9 第二批。

## 5. 原画交付物（出图时要的）

- **角色三视图**（正 / 3-4 / 侧）—— Rive rigging 要拆部件（身体 / 两臂 / 两脚 / 眼 / 嘴 / 腮红 / 小票），各自独立图层。
- **表情/姿态 sheet**：至少含 睡、招手、夹住欢呼、撒花、捂眼、耸肩 六姿。
- **格式**：干净 **2D 矢量**风（适合 Rive 绑骨），平涂 + 轻微深度，**非厚重 3D 渲染**（3D 没法重矢量化进 Rive）。
- 部件可拆、线条干净、形体一致。

## 6. AI 出图 prompt（英文主，即梦可中文；按需调风格档）

```
Cute original mascot character sheet — "Jiajia", an anthropomorphic long-tail
binder clip holding a small paper receipt. Chubby rounded trapezoid body
(~1:1 head-to-body ratio), TWO springy curved metal wire-loop arms at the top
as expressive limbs, big low-set round sparkly dot eyes near the horizontal
center line, rosy round cheeks, tiny simple smile, two small stubby feet.
Warm, reliable, slightly sleepy-when-idle personality. Clean 2D vector
illustration, smooth rounded shapes, thick clean outlines, soft flat shading
with subtle depth — NOT 3D render, NOT photorealistic. Warm cream / paper
palette with a soft coral accent. Provide a character turnaround (front, 3/4,
side) AND an expression sheet: sleeping with zzz, waving hello, happily
clamping a receipt with hearts, celebrating with confetti, shocked covering
eyes, shrugging with a magnifier. White background. Modern premium app mascot,
memorable, original design — NOT an owl, NOT copying any existing mascot.
```

风格档备选（出图时挑一档，定了回填本文件）：
- **A 软糯平涂**（推荐）：圆润厚描边 + 平涂 + 一点点深度，最像现代 app mascot、最稳。
- **B 纸艺质感**：略带纸纹/折痕暗示，呼应「纸本感」，更暖。
- **C 极简线面**：更克制，偏「贵」，但萌感弱一档。

## 7. 出图回填（2026-06-13）

- [x] 最终风格档：**A 软糯平涂**。理由：圆润厚描边 + 平涂 + 轻微深度最适合现代 app 吉祥物，也最利于后续 Rive 拆层。
- [x] 名字定稿：**夹夹**。
- [x] 当前候选原画：[`docs/design_reference/jiajia-mascot-character-sheet-v3.png`](../design_reference/jiajia-mascot-character-sheet-v3.png)。
- [x] 10 态动作参考：[`docs/design_reference/jiajia-mascot-10-state-sheet-v1.png`](../design_reference/jiajia-mascot-10-state-sheet-v1.png)。
- [x] 对比稿保留：[`v1`](../design_reference/jiajia-mascot-character-sheet-v1.png)、[`v2`](../design_reference/jiajia-mascot-character-sheet-v2.png)。其中 v3 的「顶部金属丝就是手臂」规则最干净，优先作为 Rive 真相源。

出图结论：

- 角色方向成立：长尾夹身体 + 顶部两条金属丝手臂 + 前方小票，记忆钩清晰。
- 生产红线：不得新增侧边小手、圆手、爪子、手指或其它肢体；所有挥手、捂眼、举镜、抛硬币动作都必须由顶部两条金属丝完成。
- 10 态 sheet 覆盖完整状态谱，可作为动效分镜参考；最终矢量化时仍要逐帧核对第 8/10 态的道具必须挂在金属丝上，而不是被隐藏手握住。

### 7.1 主题 token 映射

Rive 内不要烤死颜色，先按现有三端 token 绑定；若实现时发现透明色不适合 Rive，可在同一 PR 中补 `mascot-*` 语义 token，并同步 Android `ThemeVisuals` 与 `shared/tokens.css`。

| 部件 | Rive 语义 | Web / Owner token | Android 对应 |
|---|---|---|---|
| 身体主色 | `mascot.body.fill` | `--surface-sunken` | `ThemeVisuals.surfaceSunken` |
| 身体轻高光 | `mascot.body.highlight` | `--surface-card` | `ThemeVisuals.solidCard` |
| 描边 / 眼睛 | `mascot.outline` | `--text-default` | `ThemeVisuals.textDefault` |
| 金属丝手臂 | `mascot.wire.stroke` | `--text-muted` | `ThemeVisuals.textMuted` |
| 小票纸面 | `mascot.receipt.fill` | `--surface-card` | `ThemeVisuals.solidCard` |
| 小票浅线 | `mascot.receipt.rule` | `--text-faint` | `ThemeVisuals.textFaint` |
| 腮红 | `mascot.blush.fill` | `--state-danger-bg` | `StateTokens.danger.bg` |
| 夹口 / 暖强调 | `mascot.clip.accent` | `--brand-primary` | `ThemeVisuals.primary` |
| 汗滴 / 信息道具 | `mascot.prop.info` | `--state-info-fg` | `StateTokens.info.fg` |
| 成功爱心 / 纸屑绿 | `mascot.prop.success` | `--state-success-fg` | `StateTokens.success.fg` |
| 警告 / 金币 | `mascot.prop.warn` | `--state-warn-fg` | `StateTokens.warn.fg` |

### 7.2 Rive 拆层清单

固定部件：

- `body`
- `wireArmLeft`
- `wireArmRight`
- `footLeft`
- `footRight`
- `eyeLeft`
- `eyeRight`
- `mouth`
- `blushLeft`
- `blushRight`
- `receipt`
- `clipMouth`

可选道具：

- `zzz`
- `hearts`
- `confetti`
- `coin`
- `sweatDrop`
- `magnifier`

### 7.3 状态机命名

| 状态 | 事件 | Rive state 建议名 |
|---|---|---|
| 1 | 空态闲置 | `idle_sleep` |
| 2 | 进入空账本 | `empty_welcome` |
| 3 | 确认一笔 | `confirm_success` |
| 4 | 忽略 / 驳回 | `review_reject` |
| 5 | 目标达成 / 欠款清零 | `milestone_celebrate` |
| 6 | 下拉刷新 | `pull_refresh_stretch` |
| 7 | 戳它一下 | `tap_giggle` |
| 8 | 加载 / 同步 | `sync_coin_loop` |
| 9 | 大额 / 超支提醒 | `overspend_alert` |
| 10 | 搜索无果 | `search_empty` |

v1 落地优先级仍按原计划：`idle_sleep` / `empty_welcome` / `confirm_success` / `milestone_celebrate` / `search_empty`。
