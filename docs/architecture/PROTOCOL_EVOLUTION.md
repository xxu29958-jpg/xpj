# 跨端协议、mixed-version 与 schema 演进审查目录

本目录处理现实版本偏差，不引入分布式系统幻想，也不自行产生协议决定。当前生产拓扑仍是一个
PostgreSQL 权威后端、可能长期离线并持久写意图的 Android 客户端、API network-only 的 Web 客户端，
以及覆盖升级时可能回滚失败的单机安装。任何“同 release 一起发”都不能证明所有设备同时升级。

- Catalog version: `1.1.0`
- Current API shape: unversioned `/api/*`
- Related: [[0038]], [[0041]], [[0042]], [[0057]], [[0061]], [[0062]], [[0067]], [[0069]], [[0070]]

## PROTO-001 版本维度必须分开

至少记录：backend build/version、API/response contract revision、client capability/min read+write version、
database `schema_version/schema_min_compatible`、outbox payload version、identity/session/role binding revision、
installation currency binding revision、ledger calendar semantic revision，以及 installer/Manager/PG/config/restore-set version。不能用一个
`BACKEND_VERSION` 代替所有兼容性证明。

## PROTO-002 mixed-version 矩阵

| 组合 | 默认行为 | 必须验证 | 禁止 |
| --- | --- | --- | --- |
| 新后端 + 旧客户端 | 仅在明确 compatibility window/capability 允许时继续；否则 `upgrade_required` | 旧请求缺新字段、response 新 enum/nullable、最低写能力 | 按 User-Agent 猜能力后写入 |
| 旧后端 + 新客户端 | 新客户端先读 auth/capability；缺能力时降级只读或提示升级后端 | endpoint/field absence、错误映射、缓存保留 | 用 `/api/health` 冒充能力检查 |
| 新 schema + 旧应用 | `schema_min_compatible` 高于应用支持时 fail closed | 启动 compatibility gate、rollback drill | 旧应用对未知事实继续写 |
| 新应用 + 旧 schema | 只允许受控 Alembic migrator；任何业务 writer/seed 早于 migration 成功都关闭 | inspect/compatibility/backup-before-DDL、migration head、重入/中断 | `create_all()` 先偷偷改 existing DB |
| 长期离线 Android 重连 | 校验 session/role、ledger binding、payload/API、installation-currency/ledger-calendar revision、row_version、idempotency retention/age cap | expired/quarantined outbox、deleted/merged target、semantic binding 漂移 | 按新 schema/默认 CNY/新时区猜解旧 payload |
| 多实例版本不一致 | 当前不支持；部署必须保持单 active backend writer | listener/process/build identity | “通常只有一个”代替锁/启动 gate |

多实例将来若成为真实拓扑，必须另 ADR 定义版本 skew、leader/worker、migration ownership 和 rolling
compatibility；本文件不提前创建抽象。

## PROTO-003 expand → migrate → contract

1. **Expand**：先加新 nullable/default 列、新字段/endpoint 或双读能力；明确声明哪些旧 writer 仍安全。数据库约束
   若暂时放宽，必须有失效期限和残余检测。
2. **Migrate**：分批/可重入 backfill，记录游标、计数、失败；校验行数、财务汇总、引用和时区/序列。
   中断后能判断已完成边界，不能靠重新全跑碰运气。
3. **Capability gate**：证明全部 active writer/离线 payload 已能生产新形态；收紧最低客户端/应用版本。
4. **Contract**：停止旧写入后才 SET NOT NULL/删旧列/删旧字段/退役 parser。先确认没有消费者和可恢复
   rollback，再移除兼容代码。

紧急数据/安全修复可先 fail closed，但不得跳过 migration evidence 和后续收口。

## PROTO-004 API 字段与语义演进

- 在同一稳定协议中新增 response enum/value 也可能破坏穷举客户端，必须做 unknown-case 测试。
- rename 等价于 add new + deprecate old；不能在原字段原地改名/改格式/改含义。
- 新 request 字段先 optional 或 capability-gated；变 required 前必须证明所有 writer 已升级且旧 outbox 已
  消耗/过期/迁移。
- 删除字段、endpoint 或 enum 前必须有弃用标记、消费者清单、观察期和 removal release；当前无 `/api/v1`
  前缀并不授权任意破坏。
- 409/OCC、idempotency replay、错误 code 与权限 401/403/404 的语义也是协议，不能只比较 JSON shape。

Google AIP-180 和 Kubernetes deprecation policy只作校准：小票夹不照搬其发布周期，但采用“同一稳定
版本内不静默删除/改语义、先兼容再收缩、持久数据可解码”的原则。

## PROTO-005 离线 payload 演进

每条持久 outbox row 至少绑定 mutation type、payload schema version、target、expected row_version、
intent idempotency key、principal/session 与 ledger binding revision，以及会影响整数/日期解释的 installation-currency/ledger-calendar
revision。dispatcher 必须显式支持版本；未知版本进入 quarantine/conflict/upgrade-required，保留原始 payload，
不得 deserialize 成默认值后执行。

新增 required 字段或改变 fingerprint/canonicalization 时，需要旧 payload adapter 或明确 age-cap + min-client
gate。服务端 key retention 必须大于仍可 replay 的客户端窗口。

## PROTO-006 schema 与应用回滚

迁移分三类：

- **可回滚**：旧应用仍能读写 expanded schema，down migration 不丢事实。
- **前滚优先**：schema 可兼容旧读，但 down migration 会丢新字段；故障时修应用前滚，保留 DB。
- **不可逆**：事实已按新语义写入、重算/丢弃旧信息或提升 `schema_min_compatible`。执行前必须有独立
  backup/restore drill、明确 no-return point、旧 binary fail-closed 测试和 owner 决策。

应用二进制回滚不是数据库回滚。已跨不可逆点后，安装器不得仅恢复旧 EXE 指向新 DB 并宣称成功。

## PROTO-007 当前成熟度和未完成门

已有结构：PostgreSQL/Alembic、`row_version`、OpenAPI snapshot、schema compatibility metadata、Android outbox
type、后端 auth/status endpoint。它们只证明存在相关代码。当前**没有**统一 versioned capability envelope、
最低读/写客户端 gate、payload/ledger semantic revision 或稳定 `upgrade_required`；Android DTO 还会丢弃部分
版本信息，不能把 `/api/status/private` 称为能力握手。

当前存在 release-blocking nonconformance：main 在 compatibility gate 前已 `create_all`/migration/seed；Room
10→11 丢 outbox；unknown mutation 行为漂移；非 CNY/账务时区可被默认值误解释；server idempotency 不能返回
稳定首次结果。它们分别由 [[0067]], [[0069]], [[0061]], [[0070]], [[0057]] 收口，在此之前协议状态为
`nonconformant/unverified`。

installer/backend/Manager/PostgreSQL/config/restore-set 的 mixed-version 属于宿主生命周期 [[0062]]/[[0067]]，
不能由本通用目录承诺自动 rollback。多实例 skew 仍 unsupported。

## PROTO-008 验证矩阵

- N backend × N-1 Android：核心读、旧写 compatibility/upgrade_required、unknown enum、权限、离线 replay/quarantine。
- N Android × N-1 backend：capability absence、只读/升级引导、不损坏本地 outbox。
- Alembic head × N-1 binary：必须按 `schema_min_compatible` 拒启动或通过已声明兼容测试。
- expand migration 中断：重跑不重复副作用；backfill 计数/财务汇总一致。
- contract 前注入旧 writer/outbox：gate 必须阻止收紧；contract 后旧 writer 必须稳定失败而非写错。
- 长离线跨 delete/merge/currency/calendar/role binding：显式 conflict/upgrade required，不能覆盖 PostgreSQL。
- Web service worker：只允许静态 asset cache；HTML/API network-only，断网不产生持久业务写意图。

## References

- [Google AIP-180 — Backwards compatibility](https://google.aip.dev/180)
- [Google AIP-185 — API versioning](https://google.aip.dev/185)
- [Kubernetes API deprecation policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)
- [Kubernetes version-skew policy](https://kubernetes.io/releases/version-skew-policy/)
