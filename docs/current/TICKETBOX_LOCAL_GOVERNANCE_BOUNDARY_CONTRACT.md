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

PG/完整集成由现有生产者承担：`test_public_host_surface_regression.py`、`test_admin_devices.py`、`test_admin_upload_links.py`、`test_maintenance.py`、`test_auth_bootstrap.py`、`test_owner_console.py` 及现有 ledger/device、Desktop BFF 云用例。本机未执行这些完整集成。原独立 source `401a9cd3` 后续实际通过 CI `34039757907`、CodeQL `34039757920`、Connected `34039758001`；后者 execution `101504272046` 执行 111 例。新的组合候选仍须独立资格化，此合同不替代全系统 RC 完成结论。

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

### 与核心能力候选的前后整合复核

施工前冻结 Gov help correction `18984f42` 与 Facts `4bc14c98`；后者包含 Income `ff060dc3`、Web `93e8485b`、Debt `5b5adf34` 和已资格化 Capture main `6376bde3`。两个实际 Atlas 冲突须同时保留已闭合的 Recycle/Advisor/FX 与 Gov 退休进度，不能择一覆盖。唯一交叉生产文件 main.py 须同时保留 Gov 启动 opt-in 退役和 Income 的真实 OpenAPI 必填 header 投影；各治理 guard、鉴权、维护 writer 及跨端产品 API 的原责任不变。

施工后，main.py 相对 Facts 仅有原 Gov 启动 opt-in 退役差异；相对 Gov 则保留原 Income header helper。18 个 Gov 自有路径与预期集合一致，没有额外生产冲突。Atlas 刷新已闭合 Desktop/Capture、当前核心候选与 CSV 的真实反例，保持全部八个完整 Goal 交付包和 Windows HOLD。组合上的实际 API 合同生成器为 up to date，main.py Ruff、合并 diff 和冲突标记检查通过。

本机组合窄执行实际得到 25 passed（治理及精确 Host 原用例），并有 3 个 Access 用例在 setup 阶段因 `--noconftest` 未提供原 client fixture 而报错；这不是产品行为失败，也不称这三例通过。执行阶段数据库连接被封锁且无调用。原 Access 用例保留给正常云端 fixture 与全候选验证，没有为得到本机绿色另造身份 fixture 或更改原断言。Gov 原独立 source 的成功云证据不替本组合背书；Facts 的 legacy-DONE 概览反例及后续修正仍属活动候选，必须整合最终版本再冻结发布候选。

### 正式 P2：维护地址必须在凭据使用前受约束

施工前固定 `ccfc580261697b978f8384e1fc3eaad4a576dd9c` / tree `f8b496657f76a6cc932a6505d67020e3cbacff32`，tracked clean，原 tmp 保留。正式 `PRRT_kwDOS5LrfM6ftUkm` 成立：帮助宣称本机限定，实际 `ServerUrl → BaseUrl → Invoke-MaintenancePost` 接受任意地址，并在远程 Backend 有机会拒绝之前附加 admin bearer。这是 local-only 合同的强制推论，不接受扩大远程管理或新的权限 policy。

| 入口 / 消费者 / 旧出口 | 本次必须闭合 |
| --- | --- |
| CLI ServerUrl、显式 AdminToken、环境 TICKETBOX_ADMIN_TOKEN | 在读取环境 token、进入任何维护调用前，解析绝对 HTTP(S) 根地址；只接受 localhost 或数值环回地址。不接受 userinfo、非根路径、query、fragment，错误不得回显输入或凭据。自定义端口仍须由原后端 extra Host 配置准入。 |
| 三个清理开关 → 唯一 Invoke-MaintenancePost；orphan dry-run/delete Query | 只有验证后的 authority 可拼接原固定 route/query；认证与维护 writer 不变。禁止 HTTP 重定向逃离已验证 authority。Vacuum 仍是原 autovacuum 提示，无数据库操作。 |
| 无动作帮助、DATA_RETENTION 操作示例 | 保留本机源码/测试、精确自定义端口与后端继承前提；更新实际地址限制。没有持久化、协议字段、身份 owner、安装或恢复动作变更。 |
| 直接验证 producer | 新 Desktop 测试在真实 Windows PowerShell 中调用完整原脚本，仅拦截 HTTP cmdlet并使用合成 token，无真实网络、维护或环境凭据读取。既有 Windows Desktop job 自动收集；脚本的 CI scope 另行实际核准，不能以测试文件触发代替产品脚本触发。 |

反例 harness 首次因 PowerShell script scope 捕获错误导致请求记录为空，三项合法地址控制失败，未记为产品 RED。修正为测试子进程内的独立全局请求记录，并保留异常类别后，原脚本实际 **12 failures / 0 errors（0.41 秒）**：九个非法地址均未拒绝，三个合法地址保留正常认证请求但没有禁止重定向。全部 HTTP 已被拦截，未发送真实凭据。生产修正须让同一组原断言 GREEN；不得把任意异常作为非法地址通过条件。

施工后：最前面的 URI/数值地址验证在环境 token 读取及唯一请求函数调用之前拒绝非环回或非 HTTP(S) 根地址；静态错误不回显参数。保留验证后 URI 的原始 authority 拼写，避免 Windows PowerShell 的 `GetLeftPart` 将 `[::1]` 展开后改变文档要求的精确 Host；首次候选这一差异实际由 IPv6 控制捕获（11 PASS / 1 FAIL），修正后原组 **12 PASS（0.35 秒）**。请求保留原三条清理 route、auth、orphan query 与 timeout，仅禁止重定向。帮助和 DATA_RETENTION 同步；没有读取真实环境凭据或执行 HTTP、清理、PG、安装动作。

直接 classifier 实测脚本单路径原本已选择全部五个 scope，新测试文件单路径选择 Desktop；该 Windows job 正常收集此完整 PowerShell 行为测试，无新增 workflow/selector。原后端 guard/router/服务、参数、持久数据与 tmp 不改。Python Ruff、PowerShell parser 与 diff 检查作为短门；最终组合 exact cloud、独立复核、formal resolved 和主分支资格仍由主控完成。

### 当前云端 gate：维护 URL 准入边界的具名提取

施工前固定 `de8655efa79fe21c4ab4cc7b5381ce47ff44a92a` / tree `2e1c706e6283f69b0c2b08dabb19779dfbe4c5c9`，仅保留原 `?? tmp/`。实际 CI `34057157832` / Backend contracts `101551067848` / weight artifact `9996388192` 报告：`maintenance_ticketbox.ps1` 顶层 PowerShell AST complexity 从 main `67f0f1cb` 的 12 增至 21，超过原阈值 15，导致复杂函数数 22→23、excess 298→304。这是本片 URL 强制准入增加顶层责任的实证，区别于同候选父 Facts 的 Kotlin 体量及 Detekt 失败；没有把整份 CI 失败称为维护行为失败。

| 施工前 impact：入口 / 消费者 / 旧出口 | 本次最小调整与不变量 |
| --- | --- |
| CLI `ServerUrl` → URI 解析、根地址限制与环回检查 → `BaseUrl` | 将完整准入块移入同文件的具名函数，唯一调用显式传入 `ServerUrl` 并取得验证后的 URI；原条件、短路顺序、异常类型与静态文案不变。继续使用 `OriginalString.TrimEnd('/')`，保留 IPv6 与精确 Host 拼写。 |
| 显式 `AdminToken`、环境 token → `Invoke-MaintenancePost` | 准入调用仍先于环境 token 读取及任何请求；函数不接收或读取凭据。非法地址仍在凭据使用前拒绝，原认证 owner 不变。 |
| confirmed / rejected / orphan 三路清理、orphan dry-run/delete、Vacuum 与无动作帮助 | 原三个固定 POST、query、timeout、`MaximumRedirection 0`、结果输出、无操作帮助及 autovacuum 提示均保留；不改变持久化、协议、清理／恢复权限或安装生命周期。 |
| `test_maintenance_script_boundary.py` → Windows Desktop job | 原 12 项完整脚本行为断言继续承担九个拒绝和三种合法 authority 的真实 PowerShell 验证；HTTP 拦截与合成 token 不变，不新增镜像测试。 |
| `repository_weight_powershell.ps1` → weight / Backend contracts | 使用既有 AST producer 对修改前后这个脚本定向测量；不改分析器、阈值、抑制或 selector。脚本原五个 CI scope、原 Desktop 测试收集入口保留。 |

仅授权修改维护脚本及本合同；短门为上述原 12 项、定向 AST 和 diff／原块一致性检查。完整云端资格仍须由主控在最终候选取得。

施工后：新增 `Resolve-MaintenanceUri(ServerUrl)` 只拥有原 URL 准入与已验证 URI 返回，唯一显式调用仍在环境 token 读取前。与固定 de 逐块比较，准入条件／异常块除缩进外一致，调用之后从 `ProjectRoot` 起的全部原代码一致，文件 BOM 和调用之前的编码设置也保留。因此三个维护出口、orphan query、重定向禁止、token 获取／发送顺序、帮助及 Vacuum 均未重写，没有另一份准入或凭据 owner。

实际短验证：原 `test_maintenance_script_boundary.py` **12 passed / 0 failed / 0 errors / 0 skipped（0.40 秒）**，完整脚本在 Windows PowerShell 中执行，合法请求仍仅由原 harness 拦截 confirmed/rejected 两路；orphan 分支由上述原代码一致性确认，没有执行真实清理。既有 `repository_weight_powershell.ps1` 在 PowerShell `5.1.26100.9168` 对 de 与工作稿定向解析：顶层 CC **21→12**，新具名边界 **10 / 20 行 / 1 个显式参数**；其余三个函数 CC 保持 **4、2、1**。本文件不再贡献阈值 15 以上的函数或超额，未更改计量口径。JUnit、原测试输出与前后 AST JSON 保存于仓库外 `gov-qualification-de8655ef-20260907` 证据目录。此结果仅证明本次原行为与定向体量，不替代新候选完整 weight、CI、CodeQL 或 Connected；父 Facts 已知失败仍由主控处理。


### 31234888 bounded review: maintenance authority spelling and current indexes

Formal fzf5R is a FIX: IPAddress.IsLoopback admits the IPv4 127/8 range, while the actual backend Host gate and extra-host configuration only admit 127.0.0.1, localhost and ::1 forms. The client must not promise that another numeric loopback spelling can become operable through the documented extra-host configuration. Before/after impact includes CLI/help/OriginalString authority, token read and all three maintenance POST consumers, no-action guidance, DATA_RETENTION custom-port help, the unchanged backend Host/peer owner and its configuration producer, and the existing intercepted-HTTP Windows PowerShell test. Add rejected literal/alias vectors before production; preserve all three currently supported authorities, HTTP(S), exact ports, original spelling, static errors, no redirect and no credential use on refusal. No real network/maintenance/DB or Windows lifecycle action is authorized here.

Formal fzf5U is a separate current-index correction: AUTHORITY_SOURCE_REGISTER and CORE_INVARIANTS still name the retired public-admin opt-in as an active nonconformance. Remove only that obsolete clause and keep their other unresolved authority concerns. The dated July audit remains historical evidence. This documentation change has no command, protocol or permission consumer.


The original full-script producer executes 17 cases before the fix: 4 fail and 13 pass, with zero errors. Other 127/8 addresses, shortened IPv4 and expanded IPv6 spelling wrongly pass; the mapped IPv6 control was already refused. The real backend extra-host predicate independently accepts all three supported spellings and rejects all five added vectors. Production replaces the generic IP range classifier with the backend-supported literal authority spellings, preserving the prior URI structural validation and OriginalString/port handling. Help and DATA_RETENTION list those supported spellings. All original code after the admission function, including environment-token reading, three fixed routes, orphan query, redirect prohibition and output, is identical after line-ending normalization; the script's BOM is retained. The same 17 cases then pass in 0.43 seconds with no failures/errors/skips. HTTP is intercepted and the token is synthetic. There is no real maintenance, service start, credential read, network or DB action.

Both current-index clauses now retain only their other existing unresolved concerns; the dated July audit is unchanged. Ruff, actual script execution/parser and diff checks pass. Original RED/GREEN XML lives outside the repository in gov-host-admission-31234888-20260907. This new source still needs exact cloud qualification; the successful Facts/main or preceding GOV candidate cannot formally qualify it.
