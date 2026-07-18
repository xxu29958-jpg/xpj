# 产品 UI/UX 重构蓝图（2026-07-18）

> 本文是 `codex/product-uiux-rebuild` 的施工合同。候选主题图只作为后续视觉参考，
> 不再代表完整产品方案，也不作为开始结构重构前的选择门。

## 0. 证据与裁决顺序

本轮不把项目技能、本地规范、既有测试或审查意见本身当作事实。发生冲突时按以下顺序裁决：

1. 官方平台规范、开放标准与安全规范；
2. 成熟产品和设计系统已经验证的行业做法，并写明适用条件；
3. 小票夹真实业务模型、权限边界、数据契约与运行证据；
4. 本地 ADR、规则、技能、测试和旧实现，作为待验证的约束或假设。

低层证据不能推翻高层证据；行业惯例也不能脱离产品情境直接照搬。自动化测试证明的是已写入的
合同是否稳定，不自动证明合同本身正确。

### 0.1 本轮对抗性假设登记

| 旧有假设 | 本轮裁决 |
| --- | --- |
| 五个领域就是行业真理 | 否。它是当前基于任务流的 IA 假设；本轮保留并实现，但仍需后续可用性研究和使用数据验证。 |
| 三端必须逐字使用同一文案 | 否。必须统一业务语义和风险含义；角色、输入方式和平台不同，可使用更合适的具体措辞。 |
| 跨端 token 必须取相同原始值 | 否。统一的是 semantic role；尺寸、间距和控件值应遵循各平台规范。 |
| 所有固定 `px/dp` 都是魔法数 | 否。拒绝散落的设备特判；允许官方组件基线、可命名 token 和经约束验证的尺寸。 |
| 共享组件天然比页面实现正确 | 否。共享只降低重复，仍要逐项审查语义、键盘、焦点、错误和极值状态。 |
| 没有 mutation test 的问题就不成立 | 否。标准条款、静态证据和真实运行复现都可成立；修复后再补最合适的回归门禁。 |
| 成熟设计系统里的模式可以直接照搬 | 否。Carbon、Primer、Fluent 等只提供经过验证的交互模式；是否采用仍由小票夹的对象、风险、输入方式和平台约束裁决。 |
| 检测到任意折叠铰链就应退回单栏 | 否。竖向分隔铰链可以成为 expanded 多 pane 布局的自然分隔区；应按方向、遮挡和 `isSeparating` 决定布局，并由官方 adaptive pane scaffold 避让。 |
| 一级域切换应始终回到根页面 | 否。Android 底栏 / rail 代表并列 flow，切换后应恢复各域 back stack、筛选和滚动位置；仅在用户重复选择当前域时回到该域根。 |
| 金额输入统一按“元 × 100”最简单 | 否。ISO 4217 minor unit 是金额含义的一部分；JPY/KRW 等零位小数币种不能乘 100，超出币种精度的用户输入必须拒绝，不能静默四舍五入。 |
| Android 本地“默认币种”可以覆盖服务端 | 否。本位币是服务器会计事实，不是外观偏好；客户端必须从绑定/session 契约取得并只读展示，单笔原币才允许选择。 |
| 模型或数据库的 CNY 默认值足以覆盖新记录 | 否。默认值只可作为历史迁移兜底；上传建行必须显式冻结当时的权威本位币，后台 OCR 也不得用之后的实时配置覆盖快照。 |
| 发布门禁变红时提高已知债务阈值即可 | 否。本轮新增结构债务必须拆回既有基线；不得通过放宽阈值或删除测试制造全绿。 |
| 50/30/20 与美国 BLS 分位可直接成为中国家庭的计划默认值 | 否。仓库里相关模块目前没有生产调用，且包含未经本地化验证的金额与人群假设；本轮不把它接入 UI，也不把“行业常见”当成事实。后续应作为独立的财务事实模型审计处理。 |
| 自动化显示通过就代表运行干净 | 否。门禁还要检查进程退出、系统错误、crash buffer、浏览器控制台和真实可见状态；例如 connected XML 通过不能覆盖测试进程崩溃。 |
| Android 宽屏出现第二个 pane 就是 list-detail | 否。只有“选中集合项—展示该项详情”才是 list-detail；筛选、汇总、建议和上下文动作属于 supporting pane。两者可使用相同 adaptive 基础设施，但信息关系、返回行为和无选中态不同。 |
| 所有页面都应显示“最后刷新时间” | 否。异步、缓存或刷新失败后继续保留旧内容时，时间戳和陈旧状态是可信度上下文；每次请求都同步读取权威数据库的服务端页面不应伪造一个没有业务含义的“刷新时间”。 |
| Stripe 的币种例外就是通用会计规则 | 否。Stripe 是成熟支付通道的实现证据，可帮助发现零位币种等真实边界，但其通道特例不能替代 ISO、Unicode 或本项目账务契约。 |
| 批量模式下仍应允许整行打开详情 | 否，至少不适用于当前待处理列表。同一行同时承担“加入批量集合”和“打开抽屉”会产生焦点、选择状态和误触冲突；进入批量模式后整行导航暂停，复选框仍可操作，并提供明确退出动作。 |
| 为了整行可点，可以把复选框放进链接 | 否。视觉上的一整行不等于一个 HTML 交互控件；链接不能包含另一个交互控件或带 `tabindex` 的后代。批选 checkbox 与详情 link 必须是独立的原生可聚焦节点。 |
| bulk service 读到最新行后自取最新 `row_version` 更安全 | 否。这只能防止服务执行期间的并发覆盖，不能保护用户在旧页面上形成的意图。批量确认、忽略和元数据修改必须携带页面渲染时的快照 token；若其后行已变化，应显式跳过并提示陈旧，而不是替用户接受新值。 |
| 确认待处理记录时总可以顺带重提金额 | 否。未编辑金额的确认或商家修改不得重写 money/FX 字段；外币事实必须保留冻结的 original currency、original minor、home amount、rate 和 rate date。只有用户实际编辑金额时才提交完整且可验证的金额语义。 |

## 1. 产品模型

小票夹本轮不再按报表海报或模块陈列式 Dashboard 组织，而是采用一个待验证的五域工作台假设：

| 领域 | 用户任务 | 首要对象 | 默认动作 |
| --- | --- | --- | --- |
| 收件 | 把新记录整理到可入账 | 待确认账单、重复风险、后台任务 | 补齐、核对、确认 |
| 流水 | 查找和修正已入账事实 | 账单、分类、商家、标签 | 搜索、筛选、批量整理 |
| 往来 | 看清谁欠谁与下一步 | 应付、应收、还款复核 | 查看事实、记录动作 |
| 计划 | 管理未来约束 | 预算、目标、收入、固定支出 | 调整、归档、恢复 |
| 洞察 | 解释已经发生的变化 | 趋势、结构、异常、数据质量 | 定位原因、回到事实 |

一级导航可以统一，五个领域的中央内容不能再由同一套万能卡片或万能表格机械套用。

## 2. 设计原则

### 2.1 任务先于叙事

- 页面 H1 使用稳定业务名，例如“待我处理”“全部流水”“本月概览”。
- 当前数量、异常和权限紧随标题，构成可扫描的状态句。
- 操作进入同一命令区；大口号、眉题和说明文只用于首次引导或空状态。
- 首屏优先展示可执行对象，不用大面积留白或大卡片制造“高级感”。

### 2.2 事实先于装饰

- 所有金额、数量、趋势、状态和时间都来自真实 projection。
- 普通 UI 不展示 `row_version`、内部 id、端口、token、路径或接口名。
- date-only 事实不得伪造成具体时刻；币种和 minor-unit 语义必须明确。
- 加载保留最后一次可信内容并显示刷新状态，不能先清空再闪回。

### 2.3 一套正式视觉，外观偏好降为次级

- `paper / mono / midnight` 是外观偏好，不是三套产品方案。
- 顶层任务栏不放“主题”一级动作；外观入口放到账本或账户弹层。
- 视觉采用现有语义 token：中性 surface、清晰 ink 层级、一个主品牌强调色、
  状态色只表达成功、提醒、危险、信息和中性。
- 普通内容用节奏与 hairline 分组；卡片只用于独立交互边界、图表或需要保留状态的模块。

### 2.4 三端统一语义，不强制同皮

| 端 | 平台结构 | 密度与输入 |
| --- | --- | --- |
| Web | 固定领域导航、任务命令栏、高密度列表、侧栏详情 | 键盘与鼠标优先，宽屏保留上下文 |
| Desktop | Windows 式 NavigationView / CommandBar / list-detail 工作区 | 窗口可缩放，Inspector 在中等窗口转覆盖抽屉 |
| Android | compact 底栏、expanded 导航 rail、list-detail 或 supporting pane 自适应 | 触摸优先，单手主流程，宽屏按信息关系利用双栏 |

跨端必须统一领域名、状态词、金额语义、危险动作层级、空/错/加载/只读状态。

## 3. 领域结构合同

### 收件

1. 紧凑队列状态：总数、缺信息、重复风险、可确认。
2. 筛选和批量动作。
3. 待处理列表。
4. 选择后显示凭证与编辑详情；确认成功自动进入下一条。

### 流水

1. 月份、总额、笔数和筛选位于列表命令区。
2. 交易列表是主内容；日历、来源分布和资料库入口降为辅助。
3. 宽屏使用 list-detail，窄屏进入独立详情。

### 往来

1. 未结应付、未结应收、待复核动作。
2. 按当前主体角色展示事实，不让用户自行解释 owner-relative `direction`。
3. 还款、纠正、作废等动作明确影响范围并二次确认。

### 计划

1. 本月可用余量和需要调整的项目。
2. 按预算、目标、收入、固定支出分组，不混进一张万能表。
3. 编辑器后置；viewer 保留读态和原因说明。

### 洞察

1. 先显示异常、变化和建议回看的事实。
2. 本月事实与对比。
3. 趋势和结构。
4. 数据质量问题必须能回到具体账单或维护入口。

## 4. 响应式与可访问性

- Web 验收视口：`390×844`、`768×1024`、`1440×900`。
- Desktop 验收窗口：`820×660`、`1180×760`，另做 `320/390/480` 消费者回归。
- Android 验收：compact / medium / expanded 宽度和至少 `1.0 / 1.3 / 1.5` font scale。
- Android 一级域切换必须验证多 back stack：从至少两个域的二级页切走再返回，原 flow
  与局部状态仍在；重复选择当前域才回到该域根。
- 金额输入至少覆盖 CNY 二位、JPY/KRW 零位、负数、超精度和未知币种；所有错误路径验证
  repository 未调用且原状态未变。
- Web 指针目标至少满足 WCAG 2.2 的 24 CSS px 基线；高频产品控件优先使用现有 40/48
  高度 token，但不能把 token 存在本身当作可访问性证明。
- 键盘焦点使用清晰的 2 CSS px 轮廓或等效可见面积，不以去除 outline 代替设计。
- Android 触摸目标遵循 Material 组件默认触达尺寸；窄屏、横屏和窗口变化不依赖设备型号
  特判。官方基线和语义 token 可以使用固定 `dp`，散落且无约束依据的数值不可以。
- `prefers-reduced-motion` 下移除非必要位移；状态变化不只依赖颜色。

## 5. 实现边界

- 保留现有五领域 IA、后端权威 projection、CSRF、OCC、幂等、账本隔离和 viewer 守卫。
- 不引入 React、Tailwind、跨端框架或新的图表依赖。
- Web 使用 Jinja / CSS / 原生 JS；Desktop 使用现有本地 HTML / CSS / JS 和安全桥；
  Android 使用 Compose、ViewModel、Repository 和既有 token。
- 新尺寸、颜色、间距和动效优先来自语义 token。若确需新增跨端概念，要同步语义名称和用途，
  但平台值可以不同；parity gate 只验证语义映射，不强迫 raw value 相同。

## 6. 验收证据

每端至少保留以下改前/改后同视口证据：

- 一级首页或默认任务页。
- 有真实数据的列表。
- 列表—详情或抽屉交互。
- 空状态。
- 错误或离线状态。
- viewer / 只读状态。
- 窄屏或中等窗口。

截图不是唯一验收。还必须验证键盘顺序、焦点恢复、危险动作确认、加载保留旧内容、真实命令、
跨账本隔离和自动化门禁。

## 7. 本轮采用的权威设计依据

- Android Adaptive Apps：按 app window size class 决定导航与 pane，而不是按设备型号分叉。
  <https://developer.android.com/develop/adaptive-apps/guides/get-started-with-adaptive-apps>
- Android canonical list-detail：expanded 同时显示列表和详情，compact / medium 保持单 pane
  与返回连续性。<https://developer.android.com/develop/adaptive-apps/guides/canonical-layouts>
- Android fold-aware：`FoldingFeature` 的方向、遮挡与 `isSeparating` 才能说明铰链是否形成两个
  可用区域；不能把“检测到任意 hinge”机械等同于单栏或双栏。
  <https://developer.android.com/develop/adaptive-apps/guides/foldables/make-your-app-fold-aware>
- Android Compose list-detail：大窗口并排、小窗口单 pane；使用 Material 3 adaptive 的
  `HingeInfo` 与 pane scaffold 避让真实分隔区域。
  <https://developer.android.com/develop/adaptive-apps/guides/list-detail>
- Android multiple back stacks：底部导航和 navigation drawer 的并列 flow 应保存并恢复各自
  back stack；手写 `NavOptions` 时使用 `saveState` / `restoreState`。
  <https://developer.android.com/guide/navigation/backstack/multi-back-stacks>
- Android data layer / single source of truth：Repository 必须解决多数据源冲突，向 UI 暴露明确
  authority；本位币因此绑定服务端账本/session 事实，本地外观偏好不能成为第二权威。
  <https://developer.android.com/topic/architecture/data-layer>
- Windows NavigationView：稳定一级导航应适配窗口宽度。
  <https://learn.microsoft.com/windows/apps/develop/ui/controls/navigationview>
- Windows controls and patterns：命令栏承载上下文动作，list/details 承载集合与详情。
  <https://learn.microsoft.com/windows/apps/develop/ui/controls/>
- ISO 4217：币种代码与 minor-unit 关系是金额解释的一部分，不能把所有 `*_cents` 都假定为
  1/100。<https://www.iso.org/iso-4217-currency-codes.html>
- Unicode TR35 Numbers：货币的小数位、符号、分组和消歧属于 locale/currency metadata；
  CNY 与 JPY 等共享窄符号时必须提供足够上下文。
  <https://www.unicode.org/reports/tr35/tr35-numbers.html>
- Java `BigDecimal` / `RoundingMode.UNNECESSARY`：把用户输入缩放到币种 minor unit 时要求精确结果；
  需要丢弃小数位就抛错，不能用 `HALF_UP` 把超精度输入静默改成另一个金额。
  <https://docs.oracle.com/en/java/javase/22/docs/api/java.base/java/math/RoundingMode.html>
- WCAG 2.2 Target Size (Minimum)：指针目标至少 24×24 CSS px 或满足明确间距例外。
  <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum>
- WCAG 2.2 Focus Appearance：可见焦点应有足够面积和对比度。
  <https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html>
- WAI-ARIA Modal Dialog：模态框必须有可访问名称、焦点留在内部、关闭后回到合理触发点；
  不可逆动作优先聚焦破坏性最低的动作。
  <https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/>
- HTML `<a>` 内容模型：有 `href` 的链接不能包含另一个 interactive descendant，也不能包含显式
  `tabindex` 后代；整行详情和批选 checkbox 必须拆成独立交互节点。
  <https://html.spec.whatwg.org/multipage/text-level-semantics.html#the-a-element>
- WAI-ARIA Checkbox：checkbox 必须有可访问名称，并支持聚焦后以 Space 改变状态；优先使用原生
  `<input type="checkbox">`，避免重复手写浏览器已经提供的键盘与状态语义。
  <https://www.w3.org/WAI/ARIA/apg/patterns/checkbox/>
- RFC 9110 条件请求用快照 precondition 防止 lost update；小票夹 Web 表单虽然使用领域
  `row_version` 而不是 HTTP ETag，同一原则要求 mutation 绑定用户实际看见的版本，不能在服务端
  偷换成更新后的 token。<https://www.rfc-editor.org/rfc/rfc9110#section-13.1.1>

## 8. 采用的成熟行业做法

这些做法不是新的硬编码规范，只在与本项目任务和风险相符时采用：

- **任务型数据工作台**：Carbon Data Table 把全局搜索、筛选、导出和批量动作放在表格工具栏，
  行级动作留在具体对象，并用展开/详情渐进披露；本轮据此保留高密度列表、任务命令区和
  list-detail，而不是把每条事实包装成宣传卡片。
  <https://carbondesignsystem.com/components/data-table/usage/>
- **危险确认**：GitHub Primer 的 ConfirmationDialog 使用具体标题和动作标签，危险动作默认聚焦
  取消，并在关闭后把焦点还给触发器；Fluent 进一步要求只在潜在数据损失等强风险场景使用
  `alertdialog`，不能把所有普通确认都升级为强制打断。本轮共享确认框按风险条件选择语义与焦点。
  <https://primer.style/product/components/confirmation-dialog/accessibility/>
  <https://fluent2.microsoft.design/components/web/react/core/dialog/usage>
- **币种精度**：Stripe 的生产支付契约明确区分二位小数与 JPY/KRW 等零位小数币种；本轮所有
  Web/Owner 展示与输入都从产品明确支持、由 ISO/Unicode 校核的 currency metadata 推导，
  不再固定乘除 100，也不对未知三字母代码猜测两位小数。
  <https://docs.stripe.com/currencies>
  采用边界：Stripe 只作为支付行业实现证据，不把它的通道规则写成通用账务标准；最终仍以
  ISO/Unicode 和小票夹显式支持的闭合集合裁决。
- **异步结果可感知**：WCAG 2.2 Status Messages 要求不移动焦点也能让辅助技术获知结果；本轮批量
  成功、失败和进度使用恰当的 `status` / `alert` live region。
  <https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html>
- **数据新鲜度透明**：Power BI 把最后刷新时间作为用户判断内容是否可信的关键上下文；本轮刷新失败
  时保留上次可信内容，同时显示上次生成时间和陈旧状态，不把旧数据伪装成当前结果。
  <https://learn.microsoft.com/en-us/power-bi/explore-reports/end-user-fresh>
  采用边界：只用于异步生成、缓存或保留上次可信结果的 surface；同步请求即查权威数据库的普通页面
  不机械增加时间戳，并区分 `generated-at`、`synced-at` 与业务数据自身的 `as-of`。
- **条件式批量模式**：Carbon 的批量动作模式用于需要对多个对象执行统一命令的高密度集合；本轮只在
  待处理列表采用，并在该模式中暂停整行详情导航、保留复选框操作和清晰的“取消选择”，避免把
  浏览对象与构造批次混成一个交互状态。
  <https://carbondesignsystem.com/components/data-table/usage/>

### 8.1 明确保留的兼容与未来边界

- 旧 CSV 的 `amount_yuan` / `amount_cents` 仍是已发布的二位小数兼容字段；新会话、API 和 UI
  不再依赖它解释通用币种。若未来扩展导入协议，应新增明确的 `currency_code`、
  `original_amount_minor` 和精度元数据，而不是改变旧字段含义。
- 当前产品明确支持的闭合集合只含 0 位或 2 位 minor unit 币种；Web 与 Android 已按元数据解析，
  Desktop 的投影当前也覆盖这组集合。未来若加入三位币种，必须先扩展跨端格式化元数据与契约测试，
  不能从“现在全部通过”推断未来天然兼容。
- 跨端符号和分组仍受各端 locale formatter 能力影响；有歧义的窄符号必须配合 ISO code 或上下文，
  不把三端像素级、字符级完全一致当作正确性的条件。

## 9. 三端落地结果

本轮“完整产品”指五个业务域都能从真实 projection 进入、看到真实状态，并把该端展示出的主任务
做完；不等于三端逐像素相同，也不等于把尚未进入产品边界的未来模块伪装成已交付能力。可见控件
必须满足以下二选一：接入真实命令并有权限、并发和失败反馈，或明确呈现只读状态；不存在点击后只
换文案、只改本地状态或跳向空壳页面的主流程控件。

| 业务域 | Web | Desktop | Android |
| --- | --- | --- | --- |
| 收件 | 真实队列、筛选、独立详情抽屉、批量选择、补齐、确认、忽略 | Windows app window 通过本地 BFF 打开同一完整工作台，保留表单命令与账本上下文 | compact / expanded 队列、真实处理页、补齐与确认链路 |
| 流水 | 月份与条件筛选、搜索、列表—详情、编辑及资料库维护 | 通过 BFF 使用完整流水与维护页，不在本地 HTML 复制第二套事实 | 流水列表、筛选、搜索、详情与编辑；切域后恢复原 flow |
| 往来 | 应付、应收、个人/成员语义、还款复核、债务目标及关联欠款编辑 | 通过 BFF 使用相同往来命令；后端只接受 Desktop 绑定凭据 | 往来列表、详情、还款草稿、债务目标及完整关联欠款编辑 |
| 计划 | 预算、目标、收入与固定支出各自使用领域页面和真实 mutation | 通过 BFF 使用完整计划页，Viewer 权限下保持只读 | 对应原生页面、ViewModel 与 Repository 命令闭环 |
| 洞察 | 趋势、结构、数据质量与回到事实对象的入口 | 通过 BFF 使用完整洞察和数据质量页 | compact / medium / expanded 的真实领域 supporting pane 与下钻 |

Desktop 不再把后端 bearer 暴露给浏览器，也不把简化的本地投影页当作功能替代品。它以本地
Windows shell 承担启动、绑定和凭据保管，以 `/web` 工作台承担产品能力；这样三端共享业务语义，
同时只保留一个 Web mutation 实现。

## 10. 权限、会话与并发收口

- Web 所有写操作继续使用 cookie session、CSRF、账本隔离、Viewer 守卫和用户看到的
  `row_version`；批量操作逐条携带页面快照，不在服务端偷取最新版本替换用户意图。
- Web 抽屉把最终 URL、重定向、Content-Type 和 fragment 标记都作为响应合同。登录过期时保留原行，
  显示显式错误，不把登录页 HTML 当成成功结果。`J/K/Enter` 只在复核表格持有焦点时工作，符合
  WCAG 对单字符快捷键作用域/关闭机制的要求。
- Desktop BFF 只转发明确允许的同源产品路径；浏览器不接触后端 bearer。后端 `/desktop/*`
  只接受 live、`scope=app`、`platform=desktop` 的凭据，写命令在同一数据库事务中锁定并复核
  token、device、membership 和最新 role 后再提交。
- Desktop 启动凭据不进入 URL、Edge 参数或 profile 名。单次 bootstrap token 只存在于
  ACL/0600 受限的临时 HTML，并通过 POST body 兑换 HttpOnly、限路径 cookie；重放被拒绝并清理
  临时材料。重绑定先 prepare 一个 5 分钟、普通鉴权拒绝的 pending B；Manager 把 B 持久写入
  WinCred recovery 位后才调用 activation。服务端在同一事务中激活 B、延长到正式 TTL，并精确
  撤销仍有效的 Desktop A；Manager 随后把 B 提升到 primary。activation 响应丢失、进程 crash 或
  primary 写入失败都可从 recovery 幂等重放，不会留下已激活但本机失管的 B。若本地 A 已丢失，
  不按设备名或安装标识猜测撤销未知服务端会话，用户需在 Owner Console 精确撤销旧设备。
- Android 继续以服务端账本/session 为业务权威。还款草稿焦点进入可恢复 route state；Activity
  重建、折叠和窗口变化不会丢失当前任务。债务目标关联编辑携带最新 OCC 版本，失败保留用户选择，
  Viewer 不显示可写入口。

新增安全裁决依据：

- IETF *OAuth 2.0 for Browser-Based Applications* draft 27 的 BFF 模式把 token 留在后端组件，
  浏览器只持有防护后的 session cookie；本轮 Desktop 本地 BFF 采用同样的暴露面原则。
  <https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/27/>
- Microsoft WebView2 安全指南要求把 Web 内容视为不可信输入，限制 host object / message / origin
  边界；本轮虽使用 Edge app window 而不是 WebView2 SDK，仍采用其最小桥接与来源校验原则。
  <https://learn.microsoft.com/microsoft-edge/webview2/concepts/security>
- OWASP Authorization Cheat Sheet 要求默认拒绝并在每次请求校验授权；Session Management Cheat
  Sheet 要求服务端可撤销并失效 session。本轮 Desktop live credential 与事务内 role 复核据此
  裁决。<https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html>
  <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>
- PostgreSQL 显式锁与事务级 advisory lock 用来把身份/权限复核和业务提交放进同一竞争边界，
  消除“检查后、提交前”被撤权或切换成员关系的窗口。
  <https://www.postgresql.org/docs/17/explicit-locking.html>
- CWE-598 与 RFC 6750 都说明敏感凭据不应放在 URL 查询字符串；本轮因此移除启动 secret query，
  也不把它编码进浏览器 profile 或进程参数。
  <https://cwe.mitre.org/data/definitions/598.html>
  <https://www.rfc-editor.org/rfc/rfc6750.html>
- WCAG 2.2 Character Key Shortcuts 要求仅字符快捷键可关闭、重映射或只在相关组件获得焦点时生效；
  本轮采用最后一种。
  <https://www.w3.org/WAI/WCAG22/Understanding/character-key-shortcuts.html>

## 11. 最终验证证据

- Backend：最终测试集合为 `2819`；全量 pytest 通过。OpenAPI snapshot 与生成结果一致。
- Desktop：全量 `304` 个 pytest 通过；真实 Microsoft Edge bootstrap / BFF 端到端链路通过。
- Android：测试数量门禁 `1558`；完整 `testGrayDebugUnitTest`、`lintGrayDebug`、
  `assembleGrayDebug`、AndroidTest 编译与 baseline profile 门禁通过，主代码、unit-test 与
  androidTest detekt 均为 0 findings；lint 为 0 errors（149 warnings、6 hints），API 36 模拟器
  最终产品 APK 的关键用例 `6/6` 通过。
- 发布审计：ADR、架构债务、route/mutation 测试矩阵、CSRF、token parity、Android 文案与 alpha
  ratchet 等 `30/30` lane 全部通过；没有提高结构债阈值或新增 known gap。对抗性复核同时撤掉了
  `mutate_token_exempted` 原先不合理的总数 DOWN-only 假设和一次性 count grandfather：新增的
  create-row、终态与会话轮换路由本来就不能携带“旧行版本”，不能把真实产品扩展误记成债务。
  新门禁改为相对 exact Git base 比较完整的
  `route → (reason, owner, touched_tables, risk)` 映射，只放行本轮审阅过的 9 增 2 删；
  路由等量替换、元数据漂移、超调、少调和未来未审增量全部失败，合并后批准自动失效。
  OCC carrier 仍为 UP-only，因此已有并发保护不能降级。
- Web：Microsoft Edge 在 `390×844`、`768×1024`、`1440×900` 下完成可见与 DOM/交互检查；
  真实 Edge 回归覆盖 drawer 登录过期、批量模式、焦点作用域和 BFF。
- 可见对照保存在 `artifacts/uiux-audit/after/`；其中
  `comparison-web-pending-before-after.png`、
  `comparison-web-pending-mobile-before-after.png` 和
  `comparison-android-inbox-before-after.png` 使用相同状态/视口并排判断，不把单张截图当作 QA。

保留的非阻塞债务：Android lint 仍会报告仓库既有的未使用资源等提示；它们没有对应半成品入口，
本轮没有通过抬高发布阈值来隐藏。未来清理必须单独删除资源并跑全量回归，不能与功能重构混在一起。
