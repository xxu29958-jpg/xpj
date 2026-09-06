# 本机治理边界收口

## Goal

继续全系统 Internal Beta RC：让治理入口只能在本机执行，移除公网逃生开关，保留真实本机治理和远程 ledger-scoped 产品任务。

Authority：用户完整 Goal 与本片 FIX 裁决 → 2026-08-26 最终产品合同第 15 节（Tunnel 视为公网，公网仅明确 UploadLink 与认证、ledger-scoped 产品 API）及 Windows/G2 后最终合同 → exact source。Atlas 是导航，历史 ADR/测试不定义支持范围。

起点：`d52ec6118c62aaf136aec9f43f6692532a0aa0f0`，`codex/local-governance-boundary-20260906`，初始 clean。施工时 Desktop main 资格仍 pending；root 集成前已独立核准 CI `34037804229`、CodeQL `34037804091`、Connected `34037804181` 全部成功。这不资格化本片新候选。

## Allowed Changes

退役 `ALLOW_PUBLIC_ADMIN_API` 的配置字段、启动检查、网络放行分支、Admin 专用 Access 分支和派生展示；共享 guard 覆盖 Admin、maintenance、bootstrap/pairing-codes。同步维护边界说明和直接测试。复用现有 guard、认证、服务与 CI lane，不新增治理框架。

## Forbidden Surface

不改账户/凭证/权限/ledger 授权、数据或业务服务写入；不迁移或撤销已有 token，不自动重发旧请求。不要创造远程 Admin 客户端。不得修改 Windows host、Cloudflare 安装或运行状态。Fresh G2 CLOSED；repair/reinstall/uninstall/upgrade/downgrade/full backup-restore/Cut C-D-E HOLD。本机不跑 PG、Gradle 或长测；子代理不 commit/push。

## Done Checks

- 即使旧环境变量为 true，公网 peer 或公网 Host 对三组实际路由均返回 `403/admin_api_local_only`，服务未执行。
- 本机 peer + 本机 Host 仍需合法 admin scope；真实远程 ledger-scoped 设备/配对产品 API 不被挂入此边界。
- Owner 本机设备、上传链接、配对恢复入口及服务 owner 保留；Web/static 的 Cloudflare Access 检查保留。
- 旧启动条件、配置读取和“公网已放行”派生状态物理退役；遗留环境变量不再改变支持边界，也不再要求为其配置 Access 才能启动。
- 直接测试、构造器、当前说明及 CI 生产者清单闭合；不把 mock/纯检查当作 PG、打包或部署资格。

## Before / After Impact

| 责任与入口/消费者 | Before | After / 直接验证生产者 |
|---|---|---|
| `config.py` → `main.lifespan` → `require_admin_network_boundary` | 环境变量放行公网，启动按 Access 配置许可 | 字段、配置读取、专用启动检查/异常及公网分支已删除；旧 env=true 的真实 guard 反例 GREEN。真实 lifespan 仅运行到被 fence 的 DB readiness 调用，证明旧 env 无 Access 不再阻断，不启动 DB/服务 |
| `routes/admin.py`：设备、上传链接；`routes/maintenance.py`：七个维护入口；`bootstrap.py`：pairing-codes | 同一个放行分支覆盖三组路由 | 三组实际路由保持原依赖；真实 app/router/auth + 最终 service spy 证明公网拒绝、本机 admin 通过、app/无效身份拒绝。不改变服务或数据 |
| `cloudflare_access.py` | 仅 `/api/admin/` 另加 JWT；maintenance/pairing 也被放行却不在附加分类中 | Admin 特例已删除；Web/static 原 Access 拒绝与有效 JWT 后进入 Web session 三条测试通过，禁止 DB 连接 |
| `SecurityView/get_security_view` → Owner 设置概览/安全页；route inspector → 接口页 | 暴露可放行配置和旧说明；维护错误归入公开组 | 派生字段已删除，现有页面说明固定本机治理；真实 DTO + StrictUndefined 两模板渲染通过；实际路由分组将三组入口归入本机管理 |
| Owner Console 设备/链接/配对恢复 → `owner_console_service` | 本机直接服务调用 | 保留；既有 Owner/身份/权限云测试 |
| Android `MyDevicesViewModel` → `LedgerRepository` → `LedgerDeviceApi`；Desktop Web BFF | 分别走 `/api/ledgers/{ledger}/devices` 与 `/web`，不消费 Admin API | 保留；既有 ledger/device 与 BFF 直接测试 |
| `maintenance_ticketbox.ps1` / `DATA_RETENTION.md`；`smoke_test.py` | 维护脚本默认 loopback，但 ServerUrl 参数未说明支持边界；烟测自行启动本机后端 | 原修正限定源码/测试和本机地址，但自定义端口说明遗漏后端 Host 配置前提；下方正式 P2 补查已补齐参数帮助、无参数提示及操作文档。参数、guard 和维护调用机制不变；烟测原本即向其启动的后端传入精确额外 Host。没有执行维护或烟测 |
| Desktop `public_endpoint_probe` → `public_connectivity_provider` | 无凭据负向探测接受 401，不能证明有效 admin 身份也被公网拒绝 | 保留有限观察及其状态协议；原 probe 的 60 条 fake-transport 测试通过。三组后端路由测试负责有效身份的拒绝证明，不把 admin 凭据发往公网 |
| `ci_gap_trigger_scope.py` / CI | network_boundary 属现有 pairing producer：postgres/backend_frozen/windows，单文件不触发 Desktop manager | 实际 classifier：本候选五个 lane 全 true；单独 guard 为 postgres/backend_frozen/windows=true，android/desktop=false。本片未改分类器/门禁，也未把 Native Windows lane 当生命周期开放 |
| 旧配置、测试、runbook、threat model | 保留公网 opt-in 的启动成功测试与说明 | 旧启动测试替换为当前请求/权限/启动前界行为；Owner 文件重复 guard 测试和错误公网成功测试删除；当前配置指导删除。历史 ADR 留作历史证据 |

## Evidence

施工前只读：三组共享 guard 的实际入口、全部配置投影和本机/远程消费者已追踪。`d52ec611` 上生产未改时，实际短 RED 为 6 failed / 9 passed（0.38 秒）：两个真实 guard 未拒绝；三组实际路由均返回 200 而应 403；路由分组遗漏 maintenance/pairing。九条本机身份对照已经通过。

最终局部组合：`test_admin_api_public_gate.py`、`test_network_boundary_extra_hosts.py`、原 `test_public_web_security_layers.py` 三条 Access 用例，共 **28 passed（0.47 秒）**。以 `--noconftest` 和 API 合同导入 stub 执行；命令外层在安全导入之后封锁真实 `Engine.connect` 并断言执行阶段未调用，该封口不是测试文件永久 fixture，也不能仅凭 JUnit 证明。TestClient 不启动服务 lifespan，唯一 startup 用例在 DB readiness 之前停住。JUnit：`tmp/local-governance-boundary-short.xml`。Desktop 原 `test_public_endpoint_probe.py` 为 **60 passed（0.10 秒）**，传输全为测试替身，不是公网或 Windows 实机资格。

另有：实际 `SecurityView` 构造 + 两个现有模板的 StrictUndefined 渲染通过；OpenAPI snapshot unchanged；变更 Python 的 Ruff、`git diff --check`、维护脚本 PowerShell parser 通过。生产 Python/模板删除了配置分支和启动责任，没有新增 owner/wrapper/writer、DB schema 或客户端字段。

测试修正保留证据：首轮 pairing fixture 的 `expires_at` 错用了 datetime，实际 DTO 是 string，先改正后才取得准确 RED。首次修后纯 guard 断言误用 `AppError.code`，改为真实 `AppError.error` 后 GREEN；拒绝状态和机器错误码断言未削弱。环境有已存在的 TestClient 依赖弃用提示及 pytest 预导入警告，不属于产品失败。

完整 diff 检查发现脚本帮助补丁最初匹配了内层函数的 `param`（脚本首行有 BOM），已移到真实脚本入口；实际 `Get-Help` 的 ServerUrl 说明确认本机边界可读。未改变执行参数或调用行为。

### 全部直接接线与构造器

- `Settings` 的唯一生产构造器是 `config.get_settings`；`SecurityView` 的唯一构造器是 `runtime_settings_service.get_security_view`。两处都已删旧字段。Owner `_settings.py` 的概览和安全页继续消费同一 view；模板无 fallback 字段。
- shared guard 的生产 Depends 仍是 `routes/admin.py` router、`routes/maintenance.py` router、`routes/bootstrap.py` pairing-codes。认证和各服务 owner 未动；旧 startup guard/异常没有剩余定义或导入。
- `cloudflare_access_guard` 仍通过 `_requires_cloudflare_access` 为 Web/static 执行原校验；`route_inspector_service.list_route_groups` 仍由 Owner `_settings.py` 接口页消费。
- 本机 Owner：`_devices.py`、`_upload_links.py`、`_pairing.py` → `owner_console_service` 保留。Android：`MyDevicesViewModel` → `LedgerRepository` → `LedgerDeviceApi` 保留。Desktop：`web_bff.allowed_target`、`public_connectivity_provider` → `public_endpoint_probe` 保留。
- 当前环境样例、设置页、接口页、THREAT_MODEL、CLOUDFLARE_TUNNEL、DATA_RETENTION 和维护脚本帮助已同步。Atlas 仅更新原 Public-admin 单行与原 Backstage 交付包，没有改变其他 PR 的状态。

PG/完整集成仍由现有生产者承担：`test_public_host_surface_regression.py`、`test_admin_devices.py`、`test_admin_upload_links.py`、`test_maintenance.py`、`test_auth_bootstrap.py`、`test_owner_console.py` 及现有 ledger/device、Desktop BFF 云用例。它们在本机未执行。本候选未提交；exact-candidate 云 CI/CodeQL/打包资格由 root 后续执行，此合同不替代全系统 RC 完成结论。

### 正式 P2：自定义维护端口的后端配置前提

本次定向修正基于 `401a9cd326fdd326a74b014cb92b1319c5fe7dc6` / tree `465157ee3b780cd219001a6a60c610778f3b18c1`，开始时 tracked clean，保留现有 tmp。正式 thread `PRRT_kwDOS5LrfM6fs9dt` 指出旧帮助承诺可选本机端口却遗漏 `XPJ_EXTRA_LOOPBACK_HOSTS`。这是原说明消费者的真实遗漏；先前 parser/帮助读取通过只证明帮助可解析，没有证明该自定义端口用法成立。

| 前后 impact 范围 | Before：当前反例与责任 | After：最小修正与保留证据 |
|---|---|---|
| 参数帮助 → `ServerUrl` → `BaseUrl` → `Invoke-MaintenancePost` → 三个清理 POST | 实际 `Get-Help -Parameter ServerUrl` 只有“可指定本机端口”；脚本不配置或启动后端，8765 的 Host 不在默认集合 | 帮助明确在后端启动窗口设置精确主机:端口、继承／重启前提、别名单独配置及客户端环境无效；参数和请求代码不变 |
| 无参数使用提示、`DATA_RETENTION.md` 的维护入口 | 同一说明没有带用户完成后端配置，直接改 `-ServerUrl` 仍被拒绝 | 提示指向实际参数帮助；文档提供后端环境赋值和同地址的 dry-run 命令，保持源码/测试限定及安装数据 HOLD |
| 维护 router → shared guard → admin auth → 原服务 | `/api/maintenance` router 的原依赖检查本机 peer 和精确 Host。未配置 `127.0.0.1:8765` 时，真实 guard 返回 `403/admin_api_local_only` | guard、Host allowlist、鉴权、ledger 和维护 writer 未改。匹配 extra Host 只通过网络 gate；未列出的 localhost 别名、公网 Host、非本机 peer 仍返回 403 |
| 既有额外端口生产者与维护检查消费者 | `smoke_test.py` 向新后端传入 `{HOST}:{port}` 后实际请求维护 API；截图脚本在启动子进程前配置两个明确别名。`check_public_boundary.ps1` 的维护 POST 是要求 403/404 的公网负向检查 | 保留这些已接线生产者和负向断言；不修改启动脚本、不扩大公网允许范围，不将维护帮助规则推广成其他产品 API 的限制。API/结构文档和 weight inventory 仅引用既有路径，没有另一份自定义端口操作说明 |

施工前实际证据：参数帮助缺少配置前提；真实 guard 在默认环境拒绝 8765，在精确 extra Host 下通过网络 gate，但继续拒绝未列出的别名、公网 Host 和非环回 peer。既有 `test_network_boundary_extra_hosts.py` 全部 9 例通过（0.11 秒）；执行时 `Engine.connect` 被封为立即失败，无服务或数据库启动。测试仅有既有 pytest 模块预导入警告。

施工后：实际 `Get-Help -Parameter ServerUrl` 显示后端启动窗口、精确 Host、重启继承和客户端环境无效等完整前提；脚本及操作文档 PowerShell 示例均通过原 parser。与 401 比较，脚本参数块及三个函数体完全相同，仅增加帮助和一行无操作时的提示；guard/router/auth/维护服务未改，`git diff --check` 通过。比较原始 Git 字符串时首次 `ParseInput` 未剥离文件 BOM 而失败，按 `ParseFile` 同样处理 BOM 后两版解析与比较通过，不是脚本运行失败。没有执行维护、启动／重启后端、烟测、PG 或 Windows action；没有新增测试文件、触碰 tmp、commit/push 或 resolve formal thread。新候选云端资格仍由 root 完成。
