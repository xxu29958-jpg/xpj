# 体检与月报回到账单的任务链

- Goal：用户从体检的未分类计数直达同账本、同口径的待确认或已确认记录；从月报大额行直达那一笔事实，更正后保留原月份返回。属于总 Goal 的 Insights → Facts 能力补全。
- Allowed Changes：现有 Web 导航、列表筛选、返回上下文与对应查询；复用现有确认/更正 owner、权限、OCC、幂等与批量表单。未分类已确认列表覆盖全部月份，只列原始账单，不将退款等事件冒充待分类账单。
- Forbidden Surface：不新增事实 writer，不改财务统计、不自动分类或更正、不放宽身份/账本/角色边界，不开启 Windows lifecycle。
- Done Checks：计数与匹配记录一致（含旧月份、空值和 none，不含合法“其他”）；分页、详情返回、批量失败草稿及成功返回保留筛选；月报同显示字段不同 ID 的行精确定位，422/409/成功保留账本和原月份；viewer 只能查看。普通月度流水和规则历史应用能力保持成立。
- Evidence：纯真实投影/模板/导航反例先得到 3 RED、3 PASS；本地仅短测试。真实 PostgreSQL 与完整资格化放到 exact candidate 云端，未执行不冒充通过。单片闭合不等于总 Goal 或 RC 完成。

## Impact closure

本片导航改动先于 Owner 新纪律；以下以实际 main `5d460626` 重建施工前范围，和当前实现比较，不追认已经做过前置核查。末页收缩修正则在施工前先列直接影响，再用真实失败反例施工。

| 路径 | 基线 / 施工后责任与证据 |
| --- | --- |
| 入口、计数消费者 | `web_data_quality.py` 与 `insights.py`、Owner console index/ledger console 共用未修改的 `data_quality_summary`。仅 Web 混合计数 → 新规则出口被两条记录链接替换。`web_pending.py` 已调用原 `is_uncategorized_expense_category`；category service、expense helpers、edit command、money views、bulk review 的原 Python predicate 及 token/trim 常量未变。新增 SQL 筛选沿相同常量；一致性需真实 PG 用例执行，不能以源码同名代替。 |
| 列表 query 与全部消费者 | `list_confirmed` 仅有 `routes/expenses.py` 和 `routes/web_app.py` 两个调用者。新增开关默认 false，API 原调用未传，保留原 stream；`filtered_confirmed_stream` → `stats_service.py` 未改。Web 明确启用 root-only 筛选并传 `month=None`，隐藏月度汇总。末页修正只改 Web `_confirmed_page_rows`；其生产调用者仅 `_render_confirmed_page`，后者由 GET confirmed 和 batch error 两处进入，不改 API 分页。 |
| 返回上下文与旧成功出口 | reports 的 top query 已返回 ID，原文本投影丢 ID；新 `edit_href` 交现有详情。`_web_expense_return_context` 的消费者包括 Web app、bill split、expense edit/correction/items/splits/offsets/lifecycle、correction page、expense helpers/fact。原 allowlist 项和字段保持原分支，新增 reports/month 及 confirmed/filter；非法 origin 仍拒绝。fact/correction 页 hidden fields、422/409 原页、成功 redirect 均沿同一校验；批量 422/409 与成功出口显式传 filter。真实三态 PG 用例尚待执行。 |
| 持久化、权限、协议和恢复 | 不新增 writer/数据库列/Android payload。单笔与批量继续用原 actor/role、OCC、幂等键及事务 owner；导航字段不是授权。生成 OpenAPI 仅新增可选 Web filter query/form 字段，required API 字段未变。详情及批量返回必须保留 ledger/filter/month；空清单、越界末页也属于恢复链，不能把旧空态成功渲染当完成。 |
| 直接验证生产者 | `ci_scope.py` → `ci_gap_trigger_scope.classify_ci_paths` → CI backend PostgreSQL ordinary/real-db shards；新增真实用例用 `real_db` 标记进入现有生产者。共享 backend source 仍由原 Android/Windows scope 分类资格化；模板/查询/return helper 的变动需核准实际 scope 输出。纯导航测试、API snapshot 生成/检查、Ruff、bounded review 是短前置证据，云端与合并主干仍按 exact SHA 单独核准。 |

末页反例：51 条未分类记录的第 2 页更正唯一一条后，原 page=2 返回空列表、total=50 且隐藏分页。实际纯 owner 反例失败（只查询 page=2，未继续到有效页），新规范页码必须同时喂列表、分页、详情返回和批量 hidden page，不得丢草稿或筛选。真实 PG 批量三态将核对 51→50。

施工后：该 Web owner 现在查询有效末页，并把规范页码交给唯一 render 消费者，后者统一生成 pager、详情 query 和 batch hidden page。原 batch 的 422/409 草稿与键仍在同一次渲染传递，无跳转丢草稿。定向纯反例 RED 后全组 8 PASS（2.71 秒）；四个真实 PG 任务用例待云端。实际 changed-path classifier 输出 `postgres/backend_frozen/desktop=true`、`android/windows=false`；本片未改 Android 消费协议、APK 路径或 Windows 生命周期，API 的原 list 调用及统计 stream 默认分支未改。OpenAPI 已真实生成并复核，仅两个可选 Web filter 字段。

## 本轮云端失败后的定向修正

本轮在修改前列出下表涉及的生产者、消费者和旧出口，再核对模型与 fixture；不是事后追认前置核查。固定 source 为 `f7de69761bf92aab3e5d0e32f5c5549d08094ef5`，CI run `34032620672`。实际失败来自 job 日志；artifact 快照只有 repository-weight 报告，本轮没有取得逐例 JUnit。

| 失败生产者 / 受影响路径 | 修改前实际证据 | 最小修改与保留的后置条件 |
| --- | --- | --- |
| PG real-db 1/3，job `101484901362`；health → 跨月未分类 root 列表/分页，以及 viewer 只读任务 | `test_missing_category_matches_all_month_health_roots_and_pagination` 和 `test_missing_category_viewer_can_read_but_cannot_batch_correct` 均在 `_mark_uncategorized` 执行 `UPDATE category=NULL` 时被 NOT NULL 拒绝，尚未进入页面断言。`Expense.category` 既有模型为 `nullable=False, default="其他"`。 | `_mark_uncategorized` 的三个直接任务消费者统一用明确空串表示既有未分类事实；viewer 最后仍精确断言存储值未改变。未改模型/分类规则/权限/SQL predicate，不以“其他”冒充未分类。跨月、root-only、Unicode token、不同账本、分页无重漏、viewer 403 均保留。 |
| PG real-db 2/3，job `101484901330`；批量 422/409/成功及 51→50 末页恢复 | `test_missing_category_batch_keeps_context_through_errors_and_reduces_health` 在同一 fixture 写 NULL 失败。另三个 `_seed_categories([None])` 调用分别生成 pending、另一账本、剩余 50 行；INSERT 的 None 会采用“其他”默认值，无法证明未分类任务。 | 这三个 seed 消费点全部改为明确空串，参数类型收窄为 `list[str]`。保留原 OCC/idempotency 提交、422 草稿、409 原页、成功 redirect、规范 page=1、余下 50 个原 ID、health 恰减 1、实际分类写入断言。旧“成功返回但剩余工作不可见”出口仍由原强断言拒绝。Python helper 对 None 的既有纯口径样本不改。 |
| Backend contracts，job `101484901310` 的 repository-weight；全部返回上下文消费者 | artifact `9989198917`（qualification checkout `d9f8e1f9e928a058b7b78a7a5df78bb27ae02729`）唯一失败为 Python Backend production complexity excess `145→148`；`return_context_params` 的 Lizard CCN `17→20`。 | 将 confirmed/reports 参数策略原样提到同文件 `_confirmed_report_return_params`；公开 owner、签名、allowlist、month/filter/page/tag/query 边界及旧返回出口保持。直接消费者仍包括 Web app、bill split、详情、单笔更正、items、splits、offsets、lifecycle、correction page/form、expense helpers/fact 和月报；GET、错误页与成功 redirect 继续经过同一校验。未建立新导航 owner 或 fallback。 |

修后静态核对：移动分支的 AST 与原分支完全一致；执行两个实际源码版本的返回策略，在 2,187 个 allowlist/非法 origin 与边界输入组合上输出相同。真实任务文件的 70 个 assert 均保留，唯一预期存储值变化是将不可存储的 NULL fixture 换成语义明确的空串。生产模型、分类 token/trim 常量、Python/SQL predicate、财务 writer、OpenAPI 和持久化协议均无本轮改动。

短验证：8 个原纯导航用例在改前 `3.10s`、改后 `2.76s` 均通过；两修改 Python 文件的 Ruff 和 diff 检查通过。另行尝试收集既有 `test_uncategorized_token_shared_samples` 时，其模块引入 PG 环境并因本机测试集群标记不存在失败（1 collection error），没有执行该用例，也没有启动数据库或修改基础设施。Lizard 和真实 PG 三个失败任务未在本机重跑；修正后的 exact head 必须由原 repository-weight、PG shards 和完整 CI 重新核准，不用纯测试或旧 head 代替。

Root 集成复核：从仓库根误调用纯测试得到 `scripts.check_api_contract` 导入错误（1 PASS / 7 setup errors）；改用该入口要求的 `backend` 工作目录后，原 8 例实际通过（2.87 秒），Ruff 与 diff 检查通过。未改导入路径或生产代码来迎合错误启动方式。

## 清除标签后的范围闭合

`df397e63` 的三个 real-db shard 已通过；ordinary 2/2 job `101488519734` 在既有 `test_web_tags` 的五月清除标签链接失败（1 failed / 1822 passed / 3 skipped）。修改前已沿真实模板核对：筛选条与空态共用 `_clear_href`，它无条件同时拼 `month` 和 `filter`，把无关空参数带到月度或跨月入口。新增实际 Jinja 渲染反例同时执行两种范围、解析两个真实链接，得到 2 RED / 8 PASS（2.93 秒）；不放宽既有五月返回断言。

本次影响范围是 confirmed GET、批量错误重渲染共同使用的模板及两个清除标签出口：只清 tag 和分页，保留既有 ledger，并分别保留非空月度 month 或跨月 missing_category filter。财务查询、批量 writer、原幂等/OCC、持久化字段和详情返回上下文均未改；现有真实 PG 标签用例和新模板反例是直接生产者，Web 模板仍需 Desktop 和整合后的 native Windows consumer 资格化。缺口修正后再次核对两个入口，而非默认旧月度路径不受影响。

修后两个链接均只携带其有效范围；原 8 例加两个实际模板反例全 10 PASS（2.75 秒），Ruff 与 diff 检查通过。原云端 `test_web_tags` 没有在本机运行，仍由新 head 的 ordinary PG lane 重新核准。

## 报表返回反馈的影响闭合

施工前固定 `cb6deb00304f4037e35897a8a6bd2b83d831e821`：formal P2 指出详情失效返回报表时丢失提示。实际详情 GET、更正 GET 以及更正 POST 的目标不存在分支均通过原 return owner 将 msg/flash_type、ledger 和原 month 交给报表；报表 GET 没有接收参数，模板没有反馈消费者，因此旧“成功渲染报表”出口掩盖失败。生命周期返回沿相同 allowlist，但不创建新的反馈 writer。

第一步补报表 GET → 实际 reports.html 反馈消费者，复用 pending/confirmed 的 success/error allowlist、转义和状态/警示语义。报表正文筛选控件、CSV 与图表 JSON 继续只消费原报表字段，不传播临时提示；顶栏月份的补查和修正见下文。查询 owner、写权限、OCC/幂等、持久化和原月返回规则不改。直接生产者是真实 FastAPI route → redirect → 原模板的无 DB 反例、原月报真实 PG 任务、OpenAPI 生成检查，以及既有 Web/Desktop/native consumer scope。新增参数仅为 Web 可选 query，不改变产品 API 版本和 Android DTO。

施工后：两个实际详情/更正 GET 的失效返回均在原月份报表显示 alert；未经许可的样式值不进入 HTML，提示始终由 Jinja 转义。四条新增真实路由/模板反例在改前均因没有反馈实际失败（3.18 秒），修后连同原十条纯导航共 14 PASS（3.21 秒）。实际 Engine.connect 在路由执行前被封口，读服务隔离；这不代替真实 PG 资格。正文控制链接和 CSV 链接解析证明不带 msg/flash_type；OpenAPI 真实生成 diff 仅新增 `/web/reports` 两个 optional query。Ruff 与 diff 检查通过，final candidate 云门禁和 formal resolution 仍需新 SHA。

### 月选择器的直接消费者补查

独立审查发现上述“控制链接”证明只覆盖 reports.html 正文：新测试替换了 base.html，未执行真实顶栏的月选择器。实际 `base.html` 唯一 include → `_month_picker.html::_link` 只排除 month/page；五月错误返回的 msg/flash_type 会同时进入四月和六月链接，使已离开的事实操作仍显示为新月份错误。本项由主控裁 FIX；以下范围在修改共享模板前核准，不追认原测试已经覆盖全部导航。

| 真实入口 / owner | 修改前链与本次保留项 |
| --- | --- |
| 月报 GET | `web_reports.web_reports` → `_base_ctx(show_month_picker=True)` → base 月选择器；保留 ledger、原粒度、排名口径、商家分类，切到目标月份并去除 page 和临时反馈。正文控件、CSV、图表 JSON 保持原消费者。 |
| 已确认 GET / 批量错误重渲染 | `web_app._render_confirmed_page` 同样消费 base；月度模式保留 ledger/tag，切月仍回第 1 页。missing_category 跨月模式明确隐藏月选择器；批量草稿、原键、OCC 与筛选 owner 不改。 |
| 预算 GET / POST 重渲染 | `web_budgets._render_budgets` 消费同一月选择器；保留 ledger，预算表单、草稿、权限与 writer 不改。 |
| 目标 GET / POST 重渲染 | `web_goals._render_goals` 消费同一月选择器；保留 ledger/include_archived，目标表单、权限与 writer 不改。 |
| 唯一链接 owner / 直接生产者 | 只在 `_month_picker.html::_link` 排除 msg/flash_type，不增加页面分支、替代导航或持久化字段。新增短测试直接加载实际共享模板，执行四个真实页面的 query 上下文并解析上下月链接；旧真实 confirmed 切月去 page 用例仍保留。CI classifier 对模板触发 PostgreSQL、frozen backend、Desktop 和 native Windows；不因此开启 Windows lifecycle。 |

施工后：`test_web_month_picker_feedback.py` 四例先在实际 query 断言得到 4 RED（0.45 秒），均精确多出 msg/flash_type。唯一 `_link` 现只新增排除两字段；修后四页的上下月链接均精确保留原路径和非临时 query，去除旧 page，替换 month。未更改 base 的启用判断、任何页面 constructor、查询、表单、持久化或写权限。四例使用独立 Jinja 环境加载原共享模板，不替换该消费者，也不污染原报告 fixture 的 loader/StrictUndefined 恢复。

短组命令在 backend 目录执行 `python -B -m pytest --noconftest -p no:cacheprovider -q tests/test_web_month_picker_feedback.py tests/test_web_report_feedback.py tests/test_web_insight_fact_navigation.py`，得到 18 PASS（3.20 秒；原 14 例加本次 4 例）。新测试与原反馈测试 Ruff、diff 检查通过；旧真实 confirmed 去页码用例及 PG/Windows 云门禁本轮未在本机重跑。这一步证明限定月选择器及报表正文/导出，不把原 base stub 扩称全部导航；切账 next 随后由主控纳入下述同片闭合。

### 切账与身份恢复的同片闭合

主控随后将临时反馈进入切账/身份恢复的直接消费者裁 FIX。施工前一次搜索全部 Web routes、templates 与 middleware 的 query 读取/复制，确认只有下列完整 query 复制链；其余读取是字段消费（事实页 msg、revision pager 的既有返回字段 allowlist、ledger binding guard），不复制临时反馈到新导航。

| 复制链 | 本次最小改动与保留边界 |
| --- | --- |
| 月选择器 `_link` | 上述修正已覆盖四页上下月；只排除旧 month/page/msg/flash_type。 |
| `_base_ctx` → `_ledger_switch_next_url` → 浏览器 `_ledger_switcher` hidden next → `web_auth.web_ledger_switch` → `_safe_next_url` → 303 | 当前 helper 仅去旧 ledger，POST 只做站内目标校验，反馈会到新账本。既有 helper 增加去 msg/flash_type；账本切换仍由原鉴权、principal、session 与 `switch_ledger` owner 执行，目标 ledger 仍来自原表单，month/page/筛选保留。 |
| `_ledger_switcher` 的 Desktop / 非浏览器链接分支 | 当前另有原始 query 循环，也会复制旧反馈。迁移为消费同一 `ledger_switch_next_url`，只追加已选目标 ledger；物理退役该模板重复 query 循环。`_base_ctx` 已对所有 base 消费者提供该字段，不新增 fallback 或构造器。 |
| `_session_recovery_target` → `_normalized_recovery_target` → 身份入口 next | GET/HEAD 读取当前 URL、POST 只读取同源 referer；原规范化 owner 去旧 ledger 并拒绝外站/身份入口。只额外去两临时字段，其余目标与 query 保留，不改原 session、CSRF、权限或任何 POST draft/body。 |

新增反例使用实际切账模板；浏览器分支执行真实切账 POST 和站内 303，Desktop/非浏览器分支执行实际链接，再进入原报表 route/模板。仅隔离身份/读服务并封口 Engine.connect，不声称执行真实身份数据库。另两例执行实际 GET/POST 身份恢复目标 owner。以上先取行为 RED，再改既有 query owner；没有新增消息框架。

施工后重新核对同一复制范围：模板的第二个 query 循环已删除，两种切账分支均消费原 `_base_ctx` 必填投影；月选择器和身份恢复原 owner 均只去指定临时字段。实际 `desktop/ledger-switcher.js` 仅处理原生披露关闭，不解析目标 URL，因此目标 ledger 追加到 query 尾部没有改变该脚本消费方式。原角色展示、CSRF 表单字段、目标 ledger、principal/session 传递及权限服务未改；身份恢复的站内 allowlist、POST 同源 referer 与正文草稿未改。revision pager 和两个事实页 msg 消费者也保持原行为，未另建返回或消息 owner。

新增五例实际得到 5 RED（3.11 秒）：三种切账分支均在最终报表 HTML 仍含旧账本错误失败，两个身份恢复分支精确多出 msg/flash_type。修后同一短组共 23 PASS（3.61 秒），所有新/改 Python 文件 Ruff 与 diff 检查通过。shared template 环境仍由原 fixture 恢复 loader/undefined 并清缓存；月选择器用独立环境。实际全候选 changed-path classifier 为 PostgreSQL/frozen backend/Desktop/Windows=true、Android=false。原 `test_web_app_pages`、`test_web_reports_goals`、`test_web_budgets`、`test_local_web_identity*`、四个 real-db 任务及 native BFF 消费门继续由现有云端生产者执行；本机未运行 PG、长测或 Windows 生命周期，最终资格与 formal resolution 只认随后冻结的新 SHA。

### 月报 history 投影的质量回归修正

实际 Web source `1a3bbf9a6401cbafcb3178be8953d626e6586cfe` 的 CI `34040693548`、Backend contracts job `101506808834` 编译成功，但 release audit 失败。weight artifact `9991661364` 测量 qualification checkout `9ce6d5703d988b60315b92a0c27bad1c7c5010fa`（source 为上述 Web，base 为 main `6376bde3`）；唯一失败是 `long_functions:Python:Backend:production: 3 -> 4`。`web_reports` 从 80 行增至 84 行，越过物理长度 80；其 CCN 为 5，未越过复杂度 15。主控裁 FIX，不调整阈值、空行或原断言。

| 施工前实际 owner / 全部直接消费者 | 本次修正与保持项 |
| --- | --- |
| `web_reports` → `six_month_summary` → 六个月已确认支出与预算（含 rollover） | 查询仍位于 base ctx 之后、top-expenses 查询之前；服务、账本、锚定月、时区、本位币参数、返回顺序、金额与预算异常处理完全沿用。只抽取已读历史数据的纯视图组，不合并查询或前移均值异常。 |
| 六个月数组 → reports.html 期间范围、环比、超支月份 | `_six_month_history_view` 原样传递同一 rows；模板的首月、当前/前月及逐月预算比较不改。 |
| 同一数组 → 均值、图表与无 JS 数据表 | 原 `six_month_average_amount_yuan` 保留整数平均及币种格式化；新视图组统一给模板原两个字段。`#chart-trend` 的 data-series 与实际 trend-chart.js、fallback 数据表消费协议不改，不复制历史数据或引入另一 writer。 |
| 其余读链、反馈、返回与 CSV | `reports_overview`、monthly report/budget、base/sidebar、six-month、top-expenses 的调用顺序保持；均值仍在 top-expenses 之后求值。原 msg/flash_type、账本/月份返回、正文图表 JSON、CSV route 与 export query 不变。 |
| 验证生产者及旧出口 | 云端 weight 已给实际 RED；既有 23 短用例、OpenAPI、Ruff 与 diff 复核本次抽取；`test_reports` 的金额/rollover 和 `test_web_reports_goals` 的真实六个月图表、PG 月报事实任务由原云端执行。退役 route 内联六个月字段组；不另造框架、替代渲染或第二份均值计算。 |

同 run 的 Desktop manager job `101506808920` 另有 Node no-root 子进程 10 秒超时，未到主题断言；该测试/探针与 main `6376` 相同，原因未定。此项保持为独立未通过门，本次不改其源码、超时或断言，新 Web candidate 必须按原测试重新资格化。

施工后仅改 `web_reports.py` 与本合同：route 中原五行历史字段被同一文件的 `_six_month_history_view` 替代，传递原数组并调用原均值 owner。AST 实测 route 为 80 行（349–428），新纯视图组为 9 行；主控明确接受现有上限，不再为额外余量扩大上下文 owner。将新纯组按实际参数内联后，整个 route 的 AST 与 `1a3bbf9a` 完全相同（忽略位置属性），包括所有查询、其它投影与异常求值顺序；该静态等价证据不等于编译或云端 weight 通过。

同一原短组实际 23 PASS（3.37 秒）；OpenAPI 检查 up to date、Ruff 与 diff 检查通过。未改快照、测试断言、Desktop、金额/预算服务或任何模板/JS 消费者。未安装本机 Lizard、未重跑全仓 weight、PG 或长测；最终 repository-weight 与其余云门禁由 root 提交后的 exact candidate 重新核准。

### Windows served-Web 验证入口：单用 bootstrap 与 fresh-profile 重试（test-first）

本次固定 source `3eb75aed8d02f7177978978cd7427f7171ea6567`，施工前 clean。主控已核该候选只有 Windows 门禁失败，其余门禁完成；1180×760 served-Web 用例最后一次 `Runtime.evaluate` socket 读取超时，原始超时根因仍 unknown，probe 本身不 fetch。此处不把独立发现的恢复入口缺口冒充该超时根因，也不新增产品或 Windows lifecycle FIX。

当前 `_edge_cdp.evaluate_page` 为两次尝试分别建立 fresh profile，却复用调用前准备的同一个 URL。`ControlServer.prepare_web_bootstrap` 是既有单用 grant/material owner；真实 POST 成功后 `consume_web_bootstrap` 删除 material，再由原 handler 发放受约束 session cookie。第一 profile 已消费 grant 后再丢失 CDP 响应，第二 profile 既无第一 profile 的 cookie，也不能重用已删除 material。旧成功出口是“一次 DOM 成功”；必须补证受控传输失败之后，第二次真实浏览器仍能通过相同身份、账本和布局断言。

施工前全部直接消费者如下（行号固定为 `3eb75aed`）。Desktop 是 15 个调用，其中两个是纯 helper 测试；此外 Backend 动态导入同一 helper 的一个调用也必须在后续 required 签名迁移中处理，不能漏掉。

| 入口 / 行 | 当前 URL 与原验证责任 | RED 后需保留的准备责任 |
| --- | --- | --- |
| `test_desktop_first_use_edge.py:26` | 可复用 file URI；本机入口和原 code 继续 | 返回原 fixture URI |
| `test_ui_browser_layout.py:156` `_render_with_edge` | 可复用 file URI；Manager 各尺寸布局 | 返回原 fixture URI |
| 同文件 `:327` `_render_behavior_probe` | 可复用 file URI；实际页面状态与操作探针 | 返回原 fixture URI |
| 同文件 `:476` transport timeout 回归 | 纯 helper；两次不同 profile 后恢复 | 保留两次预算及原断言，URL 可复用 |
| 同文件 `:505` semantic assertion 回归 | 纯 helper；语义失败只执行一次 | 保留语义错误不重试，URL 可复用 |
| 同文件 `:716` served-Web 布局 | 单用 bootstrap；1180×760、820×660 两实例，真实 backend/pair/BFF/DOM | 仅原 Manager 每次独立创建 grant；本轮在原两个实例之外加一个响应丢失反例 |
| 同文件 `:814` product card matrix | 可复用 file URI；hidden authority 与尺寸 | 返回原 fixture URI |
| 同文件 `:971` prompt failures | 可复用 file URI；旧 DOM 退役与公网状态保留 | 返回原 fixture URI |
| 同文件 `:1071` dirty ledger selection | 可复用 file URI；成功前保留选择 | 返回原 fixture URI |
| 同文件 `:1131` ledger refresh cadence | 可复用 file URI；刷新不覆盖未提交选择 | 返回原 fixture URI |
| 同文件 `:1203` role / vanished ledger | 可复用 file URI；实时成员与账本消失 | 返回原 fixture URI |
| `test_web_bff_edge_e2e.py:328` | 单用 bootstrap；真实 BFF identity/header/请求与 DOM | 仅原 Manager 每次独立创建 grant |
| 同文件 `:381` theme | 单用 bootstrap；原 theme 静态脚本与本地外观 | 同上；不增加 API 外观 owner |
| 同文件 `:468` real backend render | 单用 bootstrap；两尺寸实例，pair/role/foreign-ledger 403/秘密不外露 | 同上；全部原断言保留 |
| `test_web_manual_draft_edge.py:108` | 可复用本机 HTTP URL；真实草稿重载和 unknown-response 继续 | 返回同一仍在 serving 的 URI |
| `backend/tests/test_web_edge_runtime_contract.py:87` | 动态加载 Desktop helper，可复用 file URI；实际 Web runtime consumers | required 签名迁移必须同步这个第 16 个调用 |

四个单用函数在基线共六个参数化实例；其余 Desktop 十一个 URL 可复用。预计最小责任修正是 `evaluate_page` 必填 `prepare_url(attempt)`，在每个 fresh profile 之前向原 caller 请求入口；内部 `_evaluate_page_once` 继续只读 URL。把 URL 识别、cookie 注入或 grant 生成塞进 CDP helper 会复制 Manager 的身份责任；复用同一个 profile 又不满足现有传输故障隔离。本轮不实施该 helper/调用者迁移，等实际 RED 后一次迁移全部 16 处，保持两次/10 秒和最后错误原义。

新反例只包装真实 `_WebSocket.request`：首次真实 `Runtime.evaluate` 已返回完整 served-Web DOM、同一布局/Owner 账本断言通过、单用文件已被真实消费，且仍是 attempt-1，才丢弃这一响应并抛一次 TimeoutError。JUnit 只记录无敏感值的前置成立属性。随后仍由原 helper cleanup 和第二 fresh profile 执行实际页面；最终原布局/身份/账本断言必须成立。JS 异常和布局断言不转换为 transport retry；不修改 bootstrap、cookie、pairing、服务端或 timeout。

直接云生产者是现有 `.github/workflows/ci.yml:349` 的 native Windows pytest 命令，它显式选择原 served-Web 函数，因此会收集新增参数实例；原 BFF/身份和其余消费者继续保留。当前只有测试源与本合同改变；本机不运行 Edge、PG 或长测，不声称已观察新 RED，主控负责 test-only candidate 的实际执行。

本轮短检查：原两个纯 helper 回归实际 2 PASS（0.13 秒；仅既有 `tests._real_backend` 预导入 rewrite warning），Ruff、Python AST 和 diff 检查通过。抽出的七行布局断言与原函数对应 AST 完全相同，原 `_SERVED_WEB_PROBE` 及其余函数 AST 未变；新增故障注入 helper 为 28 行、原 served-Web 函数现为 45 行。该测试路径独立选择 Desktop/Windows=true，其余重范围 false。原两个尺寸的参数 ID 保持，只有一个额外响应丢失实例；`_edge_cdp.py` 与所有产品、grant、会话和其余调用者源码未改。以上不证明新反例已 RED/GREEN，且未 commit/push。

### Native JUnit 证据出口补齐（仍未核准目标 RED）

Exact test-only `47822dbca71b1f14d592cc1469c46f006a46e49f` 的 CI `34046290437` 中，实际 native producer 是 **Windows installer build** job `101521833932`，不是已成功的 coordinator job `101521833967`。其真实 pytest 日志得到 11 PASS / 1 FAIL（57.45 秒），唯一失败为新增 `[1180x760-cdp-response-loss]`，最终 `AssertionError: layout probe did not become available`。但是 `RUNNER_TEMP/desktop-backend-results.xml` 未上传：原步骤在 pytest 非零后立即退出，当前 artifact 清单只有 APK/Room，没有 native XML。故不能核 `cdp_response_loss_after_consumed_bootstrap_dom=attempt-1`，不能把相符的错误形状认作已取得目标 RED。

| 直接生产者 / 消费者 | 最小补齐与保持边界 |
| --- | --- |
| 原 Windows native pytest → 唯一现成 JUnit XML → 主控核前置属性 | 在同 job 增加一个 `always()` artifact 上传步骤，原样上传已生成的 XML；复用该 job 已有的完整 SHA 固定 `upload-artifact` action。不复制报告、不另造断言或验收框架。 |
| 原退出 / no-skip / 清理 / 后续 Windows gate | pytest 命令、非零即退出和零用例/skip 拒绝原样保留；上传位于原 PG cleanup 之后。缺文件令上传失败，不能因此声明任何前置成立，也不改变或重跑 native 用例。 |
| 原请求与后续 helper 修正 | 响应丢失测试、record_property、单用 grant、产品会话及 CDP helper 全部保持。等新 exact candidate 的实际 XML 核准前置，再决定是否进入全部 16 消费者的 required prepare_url 施工。原 `3eb75aed` socket timeout 与 Facts `f614ceef` 的 820×660 probe-unavailable 仍是不同的 unknown 根因，不宣称由此修复。 |

本次只改必要 workflow 上传步骤和本合同。没有本机 Edge/PG/长测、commit/push；这次报告缺口补齐本身不是目标行为 RED 或 GREEN。

短检查通过：仓库实际 GitHub workflow contract audit 为 OK（4.65 秒）；现有 YAML loader 解析后，移除唯一新增上传步骤即与 `47822dbc` 的完整 workflow 数据相同，因此所有原命令、退出、no-skip、cleanup 和条件不变。上传复用原 job 已有 pinned v4 action，位于 PG cleanup 后，artifact 名为 `desktop-backend-test-results`，缺文件设为 error。现有 classifier 对 workflow 路径选中全部五个重范围；未改变路由规则。diff 检查通过，helper 和真实反例保持原样，等待新 candidate 的 actual XML。

后续 required 回调迁移还须保留准备失败的原出口：`ControlServer.prepare_web_bootstrap` 的目录/ACL/文件签发可以原样抛出 OSError；其写入清理分支也会重新抛出异常，没有统一转换成另一错误类型。旧调用在 `evaluate_page` 之前暴露这些错误，因此 `prepare_url(attempt)` 必须在每轮 transport try/catch **之外**执行，只有 `_evaluate_page_once` 的既有传输异常接受原两次处理。不得把签发、文件权限或 caller 准备错误包装为可重试的 CDP 故障；此边界进入 RED 后的前后 closure。
