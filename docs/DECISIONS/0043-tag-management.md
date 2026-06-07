# 0043 标签管理：rename / delete / merge（online-only mutate surface）

- Status: accepted
- Date: 2026-06-06
- Decision makers: 项目维护者
- 说明: 设计经团队调研 + **四轮对抗校准**（① 误把 0042 当通用加键；② 漏级联 undo 快照与镜像写 row_version bump；③ 4-路并发审补 undo 须按账单 OCC、`_ensure_tag` 复活软删、merge 软删 A、purge/undo 互斥；④ 收敛审补 undo 用 token-carrier 免登记、snapshot 生命周期自包含、rename 不快照、rebuild 改为 bump，见勘误）。承重事实主张已回代码核实（见 Confirmation）。

## Context and Problem Statement

标签今天是**隐式 only**：`tag_service._ensure_tag`（tag_service.py:62-80）在存账单时从自由文本建 `Tag`，无 rename/delete/merge。三存储皆 ledger-scoped：`tags`（身份，unique `(tenant_id, key)`，key=casefold）、`expense_tags`（成员，多对多）、`expenses.tags`（**去规范化逗号串**）。

三条结构特性决定本 ADR 比 MerchantAlias 难：

- **无管理面 + 孤儿永积**：`set_expense_tags`（:111-113）删最后一条 link 留 `Tag` 行；全仓无 tag 清理；`list_tags` INNER JOIN（:50-59）藏孤儿不清。用户撞见碎片化（出差/差旅/出差报销）无从整理（2026-06-06 实机）。
- **管理操作级联到账单**：rename/delete/merge 改 `expense_tags` + 重写 N 条 `expenses.tags`，而该串**被分类规则匹配器直读**（rule_service.py:467 `parse_tags(expense.tags)`）+ CSV 导出 + 跨端 DTO。
- **隐式高频创建**：tag 走每次存账单的 `_ensure_tag`（不像 alias 是显式 admin create）→ 软删与隐式创建会撞车（契约 4）。

precedent：`MerchantAlias`（catalog.py:23-58）有 `public_id`/`row_version`/`deleted_at` 且 undo **不级联**（清 `deleted_at` 即恢复，merchant_alias_service.py:284-345）；`Tag`（catalog.py:61-79）三者皆无、undo 必须级联恢复账单侧。

## Decision Drivers

§0 #1 数据正确（镜像漂移让规则误匹配；镜像写不 bump 版本让旧 PATCH 误过；undo 无条件重放冲掉并发编辑）；§3 OCC 幂等 / §7 并发 row_version / §6 加列三步+双写迁移 / §11 测试 / §14 online-only 不带 client dedup key；复用 `merchant_alias_service` 框架；开发期无安装基数；同类 merge 无人做=差异点。

## Considered Options

- **寻址**：A `public_id`（选）/ B by key·name（否：特殊字符 URL 编码、与全资源不一致）。
- **删除语义**：A 软删+untag+重写镜像+快照（选）/ B 硬删留 `#tag` 文本（否：漂）/ C 在用阻断（否：死胡同）。
- **undo 范围**：A 仅 delete/merge 有快照+undo;rename 自反（rename back）不快照（选）/ B 所有 op 都快照（否：rename 快照无 soft-delete 锚,purge 触发不了→快照永积,P1-B）。
- **undo 重放方式**：A 无条件重放（否：冲掉并发编辑,正是 `undo_reject_expense` _update.py:470 防的）/ B 每账单 CAS + 部分 undo（选）。
- **undo 审计姿态**：A 无 token + 登记 ledger（否：cascade-replay 在闭合 `REASON_CODES` 11 码里无诚实项——`terminal_flag_flip` 称"状态机防竞态"对 skip-replay 是假,empty-table 码因写 4 表被禁）/ B **token-carrier**（undo 带软删 Tag 的 `expected_row_version`,以载体过审,免登记免假 reason_code）（选）。
- **去规范化列**：A 保留+每 op 重写（选）/ B 删列（否：rule_service:467 直读+导出+DTO 全依赖）。
- **幂等边界**：A online-only（选,过 0042 test③）/ B 离线化（否：契约 7）。
- **rename 撞 key**：A 409 回带目标 token、显式 merge（选）/ B 静默 merge（否：惊吓性破坏）。

## Decision Outcome

Chosen：镜像 `merchant_alias_service` OCC/软删框架,**自建：仅 delete/merge 的级联快照(自包含生命周期)+ 镜像写版本号 + 隐式创建复活 + token-carrier undo**;标签管理是 **online-only mutate surface**。

- **模型**：`Tag` 加 `public_id`(回填 UUID)、`row_version`(server_default `1`)、`deleted_at`。snapshot 用**两表**:`tag_mutation_undo_groups`(`mutation_public_id`、op、**自身 `created_at`**、`consumed_at`[可空,undo 认领标记]、涉及 tag 的 public_id+原始名)+ `tag_mutation_undo_items`(`group_id` **FK→groups** + 每条受影响账单 `(expense_public_id, 原 tags 串, 原 tag_id 列表, 原 expense.row_version)`)。本仓无 DB 级 cascade(全显式 Python 删),故 undo 用**软标记认领**而非先删 group(见契约 2)。**删 usage_count=0 的孤儿 tag 无 item 行,但仍写一条 group row 作 undo 锚**(undo 只复活 `Tag.deleted_at`)。两表 + Tag 改动都进 `models/__init__.py`(否则 metadata/Alembic/create_all 看不到)。rename 不写 snapshot。`color`/`hidden` 推迟。
- **MVP 操作**(ledger-scoped、`writer`、OCC `expected_row_version`)：① list+使用计数(计数降序,过滤 deleted_at)② rename(自反,无快照)③ delete=untag 软删(写快照)④ merge A→B(**source+target 两 token**,写快照)⑤ **undo(delete/merge 限定,带软删 Tag 的 `expected_row_version`,强制守卫见契约 2)**。
- **契约 1 · 镜像写必 bump 账单版本 + 前向写单事务**：rename/delete/merge 每重写一条 `expenses.tags` = 账单写入,**必 bump 该 `Expense.row_version`**([[feedback_row_version_bump_rule]];merge dedup 同账单只 +1)。否则旧版本 PATCH 误过 OCC 改回——0038 跨端 OCC 要堵的洞。delete/merge 的**整个前向写**(镜像重写 + 各账单 bump + 软删 Tag + 写 group row + **全部 item rows**)在**一个事务**内,绝不留半截/无 item 的悬空快照或无快照的软删 Tag。
- **契约 2 · undo = 单事务有序三步(Tag-token 强制 + 按账单 CAS 部分 undo)**：undo 在**一个事务**内顺序执行:**① 软标记认领 group**(`UPDATE tag_mutation_undo_groups SET consumed_at=now WHERE mutation_public_id=… AND consumed_at IS NULL`;rowcount=1 守卫——并发第二次 undo / purge 撞到 → rowcount=0 → 404;**不删 group**,故 item 行仍在,行锁与 purge 互斥)→ **② 原子认领软删 Tag**(`UPDATE tags SET deleted_at=NULL, row_version=row_version+1 WHERE id, tenant_id, row_version=token, deleted_at IS NOT NULL`;token 陈旧[被复活/重删超越]/已 live/已 purge → rowcount=0 → **整个 undo 409 `state_conflict`**;**merge-undo 的 token 必是源 A**——A 才是软删那个,B 仍 live 进不了 `deleted_at IS NOT NULL` 谓词)→ **③ 读 `group_id` 下 item 行**,按每账单原 `row_version` 做 CAS 重放(账单版本已动/已删/非可编辑态 → **跳过**,绝不覆盖)→ **④ 物理删 group+items**(本 tx 末;step③ 读完才删,无"先删后读")。**任一步 rowcount=0 → 整个事务回滚**(group 消费一并回滚,修好 token 可再试)。成功则**返回 applied/skipped 计数**(部分 undo 显式可见;全跳过=Tag 复活成零链 live tag,可见非静默)。**Tag token 守 mutation 级有效性、per-expense CAS 守逐账单漂移,两层都真强制**(与测试矩阵『undo 旧 Tag token→409』一致;**不是**空载体)。清 `Tag.deleted_at` ≠ undo。
- **契约 3 · merge 软删 A、undo 按 tag_id 恢复**：merge 软删 A(保 `tag_id` 稳定),dedup 撞 `uq_expense_tags_tenant_expense_tag`(catalog.py:95)丢 A-link 但快照存原 tag_id;undo 按 **tag_id** 重建 expense_tags + 复活 A。
- **契约 4 · `_ensure_tag` 撞软删键 = 复活、保留快照(复活后该 delete 不再 token-undo)**：隐式创建过滤 `deleted_at IS NULL` 查 live;撞软删同 key tag → **复活(清 deleted_at + bump row_version)但保留其 delete 快照**(快照按自身 `created_at` 窗口 age-purge,不随复活销毁,供审计/清理,闭合 rev3 P2-C 的快照孤儿)。**与契约 2 step② 自洽:复活清了 `deleted_at` 且 bump 了 `row_version`,故该 delete 的 token-undo 此后返回 409**(token 被复活消费、tag 已 live,落到 step② 的 `row_version=token AND deleted_at IS NOT NULL` 谓词外)——即「复活」即承认这次重打标就是用户的意图,不再用 token-undo 把原账单集捞回(要恢复请重新手动打标);快照仅靠 purge 过窗清。(rev8 修:rev≤7 契约 4 误写「原 delete 仍可 undo」,与契约 2 step②「token 被复活→409」矛盾——团队并发审 lens-4 抓出,见勘误⑧。)
- **契约 5 · rename 409 回带目标 token**：撞已有 key(casefold,含软删行)→ `409 tag_conflict`,body 带现存 tag 的 `public_id`+`row_version`,客户端据此发 merge(source 自己的、target 用 409 给的)。
- **契约 6 · 快照生命周期自包含、purge/undo 互斥**：snapshot 保留期 = 自身 `created_at` 起的 undo 窗口(`soft_delete_policy`),**不锚在 `Tag.deleted_at`** —— 这样 delete/merge 快照在其 Tag 被复活(契约 4)或仍软删的**任意**态下,都按自身龄独立 purge,不会因 rename 不软删/复活清 deleted_at 而失去 purge 触发或窗口锚(修 P1-B)。`is_within_undo_window` 对 undo 读快照 `created_at`,非 `Tag.deleted_at`。purge(过窗)**一事务**删过龄 group+items(+ 仍软删且过窗的 Tag);undo 的 group 认领(契约 2 步①,`consumed_at` UPDATE-rowcount 守卫 + 行锁)与 purge 删 group **互斥**——不能并行成功,避免 purge 在 undo 读/重放 item 期间删掉 group+items(步③读空 / 步④双删 / FK 违约)。undo 的有序步骤见契约 2(单事务)。
- **契约 7 · online-only 过 0042 test③**：merge 软删 A + live-only 查 → 丢响应重试找不到 live A → 404 不双应用;online-only **无持久 outbox** → 无 undo 后陈旧自动重放 → 加键反引入风险。故只 OCC、不带键(§14);§2.4 离线化才补键。**实现强制**:`/api/tags*` **不声明 `Idempotency-Key` header**(`main.py` `_custom_openapi`:175-211 把任何**声明**的该 header 在 OpenAPI schema 翻成 required + 路由体 `claim_idempotent_request` 422)、不走 idempotency replay helper —— 声明=破坏 online-only。
- **读点过滤清单(软删不得泄漏)**：`list_tags`(tag_service.py:50)、`_tag_stats_for_filtered_query`(stats_service.py:239/252)、**合同 tag filter** `confirmed_query`(spending_contract_service.py:127-136)、新 list+count、`_ensure_tag` 全部加 `Tag.deleted_at IS NULL`。
- **安全胜同类**：删/合并确认显示「影响 N 笔」;op 原子 + 窗口内可 undo。

## Consequences

Good：闭合孤儿永积 + rename/merge(同类无人做);OCC/软删框架抄 MerchantAlias;rename/delete/merge **及 undo 全部带且强制 token → mutate-token-coverage 以载体通过,无需 ledger 豁免、无需造假 reason_code**(与 merchant/rule undo 的"无 token+terminal_flag_flip 登记"分叉,因 tag undo 是 OCC 级联非 flag-flip,载体更诚实且真强制);不在 0042 outbox 集合 → 幂等覆盖审计以缺席通过。

Bad/成本：
- 迁移面(`Tag` +3 列 + group/item 两快照表);**手写 Alembic(非 autogen)+ legacy `_migrations/_budgets_tags.py`(今天只建索引)同步补列/backfill/index**,否则旧库/stale-head 路径漏([[project_sqlite_legacy_migrator_column_complete]])。`public_id` 回填走跨方言三步(PG add-nullable→UPDATE uuid→SET NOT NULL+unique index;SQLite batch 表重建)——**Tag-specific 无先例**(项目其它表如 `_recurring_goals` 已有 public_id backfill 可借形)。
- 迁移镜像 invariant rebuild：修 `expenses.tags` ↔ `expense_tags` 漂移的行**要 bump row_version**(与 image-cleanup cleanup_service.py:202 一致;开发期 live==HEAD,客户端重同步无害,优于 rev3 的"不 bump"——那会让陈旧 PATCH 把订正改回,P2-D)+ 分批(§12);`backfill_expense_tags`(tag_service.py:120)有链接即早退,**修不了部分漂移**,rebuild 要独立对账 pass。
- **merge 双 token 审计盖不住**:`_audit_mutate_token_coverage.py:78` 只看「有无一个 token 字段」;merge 的 source+target **双** token 正确性(任一 stale 都 409)由 route-specific **测试**钉(source-stale-409 + target-stale-409),审计抓不到。
- 新增 error code `tag_not_found`/`tag_conflict`/`tag_undo_*`(errors.py 今天只有 merchant alias 码);group/item 两 model 必进 `models/__init__.py`。
- 级联写:每 delete/merge 扫该 tag 所有 expense、bump 各自版本、写快照——新且易漏的正确性面。三端 UI 新面。

回收条件:加列+快照表后不轻易回退。改离线化按 0042 §2.4 另评键。

## Confirmation

承重事实(已回代码核实):`Tag` 缺三列 catalog.py:61-79 vs MerchantAlias 全有 :23-58;`_ensure_tag` :62-80 无 deleted_at 过滤/无 IntegrityError retry;删 link 留 Tag 行→孤儿 :111-113,全仓无 tag 清理(cleanup 仅 alias/rule :392-401);`list_tags` INNER JOIN :50-59;镜像被规则匹配器直读 rule_service.py:467;`set_expense_tags`/`sync_expense_tags` **今天不 bump** row_version(bump 来自上游 `_claim_expense_for_update` _update.py:147-156),故契约 1 必需;image-cleanup **bump**(cleanup_service.py:202)→"数据订正不 bump"非项目一致规则,故 rebuild 选 bump;MerchantAlias undo 只清 deleted_at 不级联 :284-345;`REASON_CODES` 闭合 11 码、empty-table 码禁非空表(_mutate_token_ledger.py:30-44,338-347)→ undo 选 token-carrier 而非登记;mutate-token 审计:无 token 且不在 ledger→FAIL(_audit_mutate_token_coverage.py:200-204),载体即过;soft_delete 窗 5min,purge 仅 alias/rule;0042 outbox 含 Update/DeleteMerchantAlias(0042 行47)。

测试/验收矩阵(详随切片 B,test-agent 已出 A–L):OCC-409(rename/delete/merge,merge 任一旧 token;undo 旧 Tag token→409);**镜像写 bump 证明**(op 后账单 pre-op 版本 PATCH→必 409;无关账单不 bump;merge dedup 只 +1);**undo 按账单 CAS + 部分 undo**(版本未动→四镜像[expenses.tags/expense_tags/by_tag/规则匹配]回原;版本动→跳过+applied/skipped 计数;窗外→404);rename 撞 key→409 带目标 token;隐式重打→复活，且**复活后原 delete 不再 token-undo**（契约 4：复活清 deleted_at + bump row_version → undo 步②的 `deleted_at IS NOT NULL AND row_version==token` 两条皆不成立 → 409）;软删闭环(create-after-softdelete 不出重复 live 键;purge 过窗释放键+删快照);purge/undo 互斥(并发不 FK 违约);viewer-403、ledger 隔离(跨账本→404);迁移两路 + public_id 回填 + **部分漂移 rebuild(bump)**;audit(OpenAPI snapshot、undo 以载体过 mutate-token、route-test-matrix 401+marker)。**反向(必无)**:无缺 Idempotency-Key-422、无 same-key-replay、不发该 header。

## More Information

- [[0038]] 多端 OCC + [[0041]] `row_version`(本迁移给 Tag 加的并发层;镜像写 bump 是 0038 直接要求);[[0042]] 请求幂等边界(三测试含 test③,把标签放 online-only 侧);[[0027]] `/owner/fx/refresh`(对照:桶 upsert 豁免)。
- 落地切片(分层:schema→migration→service→routes→tests):A 迁移(Tag +3 列 + group/item 两快照表 + 镜像 rebuild[bump+分批],手写 Alembic+legacy)→ B service(rename[自反无快照]/delete/merge/undo[Tag-token 强制+按账单 CAS+部分 undo]/list+count,全程重写镜像+bump 账单)+ 5 路由(不声明 Idempotency-Key)+ 全量测试矩阵 + OpenAPI + audit 基线 → C 三端 UI。
- 勘误留档:① 误把 0042 当通用加键;② "undo like MerchantAlias" 忽略级联;③ undo 须按账单 OCC、`_ensure_tag` 须定撞软删=复活、merge 须软删 A 保 tag_id;④ snapshot 生命周期自包含(own created_at)、rename 自反不快照、复活保留快照、rebuild 改 bump、部分 undo 返回 applied/skipped;⑤ **自查纠错**:rev4 我在收敛 pass **之后**又加了一句「Tag token 仅载体、陈旧不 409」,与测试矩阵『undo 旧 Tag token→409』**自相矛盾**且让 token 成空载体(gaming 审计)→ 改回 **Tag token 强制守卫(陈旧→整个 undo 409)+ per-expense CAS 部分 undo**;并补 snapshot group+item 两表(孤儿 tag 删有 group 锚)、`/api/tags*` 不声明 Idempotency-Key header(main.py:176)、读点过滤加 `confirmed_query` tag filter、public_id 措辞改 Tag-specific 无先例、补 error code + models/__init__ 注册、merge 双 token 由测试钉(审计盖不到)。**教训:review pass 后不得再改契约就提交,改了必重审**([[feedback_verify_before_claiming_done]]);⑥ rev5 引入的强制 Tag-claim + group/item 拆表暴露**事务边界未声明**:契约 2 与契约 6 各自称 undo「第一步」(认领 Tag vs 认领 group)→ 统一为**契约 2 单事务有序三步**(group 认领 → Tag 认领 → per-expense CAS,任一步 rowcount=0 全回滚),契约 6 只留 purge 侧并指向契约 2;契约 1 补**前向写单事务**(镜像+bump+软删+group+items 一事务,无悬空快照);merge-undo token=源 A 明示;⑦ rev6 把 step① 写成 hard-DELETE group,但 step③ 要读 item 重放——本仓无 DB cascade(全显式删),先删 group 会 FK-abort 或孤儿化 item → 改本仓软标记惯例(同 `merchant_alias.deleted_at`):step① `UPDATE group SET consumed_at`(认领不删)、`items` 加 `group_id` FK、step③ 读 item、step④ tx 末物删 group+items。校准来源:Google Code Review / OWASP Threat Modeling / OWASP Secure Code Review。⑧ rev8(slice B 落地 + 团队并发审):契约 4 误写「复活后原 delete 仍可 undo」,与契约 2 step②「token 被复活→409」直接矛盾(undo step② 谓词 `row_version=token AND deleted_at IS NOT NULL`,复活后两条都不成立)→ 改契约 4 为**复活后该 delete 不再 token-undo,快照仅靠 purge 过窗清**,与契约 2 自洽;同时落实契约 6 purge(`cleanup_service.purge_expired_soft_deletes` 加 tag 快照 + 软删 tag 清理,rev≤7 只写了 merchant/rule)。lens-4 并发审还抓出:mutation 路由缺 401 测试(route-test-matrix 会红)、OpenAPI 快照未重生成——均已补。
- 治理:online-only 已合 §14,无需改 §14 或 version bump。
- ENGINEERING_RULES §0 / §2 / §3 / §6 / §7 / §11 / §12 / §14。
