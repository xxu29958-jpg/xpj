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
