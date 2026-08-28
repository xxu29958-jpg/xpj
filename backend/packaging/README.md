# 小票夹后端 · EXE / Inno 打包

把 FastAPI 后端冻结成 onedir EXE，并可进一步打成 Windows 安装器：捆绑 PostgreSQL + 后端服务，每台机器跑自己的实例（隐私优先，不共享服务器），用自己的 Android App 连。旧 ADR 及旧 release config 只是审计/兼容输入，当前发布语义以官方 Windows/SCM 合同、当前 release config 和真实目标机证据为准。

## 构建

```
cd backend
scripts\build_backend_exe.ps1          # 增量
scripts\build_backend_exe.ps1 -Clean   # 额外清理旧版共享 .venv-build
```

产物:文件夹 `backend\dist\ticketbox-backend\`(内含 `ticketbox-backend.exe` + `_internal\`;onedir,**窗口化 console=False**,ADR-0047 §8)。整个文件夹一起拷贝/分发,不能只拿出 exe。

每次构建都在 `build\` 下创建**进程私有且用后即删的精确 venv**，不复用 `.venv-build`，也不污染运行时 `.venv`。
Python、uv、PyInstaller 的精确版本只从
`packaging/windows-build-toolchain.json` 动态读取；传递依赖只从带 hash 的 `requirements-build.lock` 同步。构建会拒绝
本机版本、配置/锁、完整 Python/site-packages 执行树或冻结期间环境漂移；同一仓库的冻结构建由机器级 mutex 串行化，
只把校验通过的 staging 目录原子发布到 `dist\ticketbox-backend`，发布失败会恢复上一份完整目录。实际可执行文件 hash、
完整执行树和分发快照写入 backend provenance。该证据用于追溯，不宣称 frozen 字节可重复。**不含 OCR**
(rapidocr/onnxruntime/opencv 太重且可选)——需要 OCR 的话另装 `requirements-ocr.txt` 跑源码版。

## 档 B：Inno 捆绑安装器

档 B 是正式分发路线：安装器把程序放进 `C:\Program Files\Ticketbox`，把数据放进 `C:\ProgramData\Ticketbox`，并按两个独立进程/故障/停机边界注册两个 Windows SCM 服务：

| 服务 | SCM 登录账户 (`StartName`) | 每服务 SID / ACL 主体 | 说明 |
|---|---|---|---|
| `TicketboxPg` | `NT AUTHORITY\LocalService` | `NT SERVICE\TicketboxPg` (`unrestricted`) | 捆绑 PostgreSQL 17，簇在 `...\pgdata` |
| `TicketboxBackend` | `NT AUTHORITY\LocalService` | `NT SERVICE\TicketboxBackend` (`unrestricted`) | Shawl 包 frozen backend，依赖 `TicketboxPg` |

这是两个 SCM 服务，**不是两个虚拟登录账户**。`NT SERVICE\<name>` 只在服务启用 service SID 后作为进程 token 中的每服务 SID 及 ACL 资源主体，不会作为当前 `CreateService` / `ChangeServiceConfig` 的登录账户。v1 虚拟登录账户形态只能作为严格形状化的历史审计/迁移输入；新建和常规 SCM 配置边界均拒绝重新发布它。
该区分直接对齐 Microsoft 的 [Service User Accounts](https://learn.microsoft.com/windows/win32/services/service-user-accounts)、[LocalService Account](https://learn.microsoft.com/windows/win32/services/localservice-account) 和 [`SERVICE_SID_INFO`](https://learn.microsoft.com/windows/win32/api/winsvc/ns-winsvc-service_sid_info) 语义，不从旧 ADR 推导。

构建前置:

1. 已生成 frozen backend:`backend\dist\ticketbox-backend\ticketbox-backend.exe`。
2. 已裁出捆绑 PG:`backend\packaging\vendor\pg\bin\pg_ctl.exe`。
3. 已放好 Shawl:`backend\packaging\vendor\shawl\shawl.exe`。
4. 构建机安装 Inno Setup 6,或用 `-InnoCompiler` 指定 `ISCC.exe`。
5. 仓库内置 Inno 简体中文语言文件:`backend\packaging\languages\ChineseSimplified.isl`；它显式使用 `Microsoft YaHei UI`，确保 en-US UI 的干净 Windows 不会把简中向导绑定到无中文字形的 `Segoe UI`。

命令:

```
cd backend
packaging\build_inno_installer.ps1 -CheckInputsOnly   # 无 Inno 时只校验输入
packaging\build_inno_installer.ps1                    # 原子发布完整版本目录
```

安装包版本只能从 `app/version.py` 的 `BACKEND_VERSION` 动态读取；构建工具版本只能从
`packaging/windows-build-toolchain.json` 读取；服务/数据库身份、默认/隔离端口、SCM 策略、
就绪等待、bootstrap 默认值和密钥强度只能从 `packaging/windows-release-config.json` 读取。构建脚本只把向导所需值
注入 Inno；current shipment 只资格化 Fresh install，不提供 upgrade、uninstall 或 N-1 lifecycle。
旧版本配置、服务删除与迁移设计只保留在下方历史审计段，不能作为当前入口或产品承诺。
`build_inno_installer.ps1` 是受支持的构建入口：它绑定实际
ISCC defines，编译后重新读取 backend/PG/Shawl/recipe/Git/ISCC 证据，再把 EXE、SHA-256 旁车、provenance 和完成标记作为
一个 staging 单元验证并原子发布到 `dist\installer\Ticketbox-Setup-<version>\`；并发构建由同一机器级构建锁串行化，替换失败
会恢复上一份完整发布单元。编译入口还在释放同一构建锁前，把内存中的 installer SHA-256 写到 publish unit 外的 runner step
output，后续 `-VerifyOnly` 必须从该 compile step output 接收精确值；compile step 只能包含这一构建命令及其原生失败传播，禁止
后续第二次写 `GITHUB_OUTPUT` 覆盖 hash。GitHub 与 Gitea 都先验证本地发布单元并上传完整目录，再在 upload 后、download 前创建
随机唯一且已证明为空的临时目录，并用同一外部 hash 复核下载字节；transport 临时目录名不是发布身份，`VerifyOnly` 对外部下载
副本校验精确文件集、version/provenance 与锁定 hash，不要求目录叶名仍等于本地 canonical publish unit。上传/下载 action 固定到精确
commit。CI gap gate 以 Windows 大小写不敏感语义合并 workflow/job/step env，并锁定 compile/pre-upload/post-download verifier 为
“唯一命令 + 唯一原生失败传播”；动态 version resolver 的完整 source 必须紧邻 upload，fresh resolver 必须紧邻 download。
固定假 hash、step 内重绑 hash、重复 output writer、缺失 output、从 `BUILD_COMPLETE.json` 回读 hash、publish/download env 重绑、
死分支/输出文本伪造准备、复用下载目录或把 verifier 改绑
其他来源都会失败。只同步改写 EXE、旁车和
`BUILD_COMPLETE.json` 不能为替换产物重新授权。普通方式直接调用
`.iss` 不提供这些必需 defines/provenance，会被脚本的常规入口契约拒绝；该约束不是对任意本机管理员的密码学防篡改声明。
`release_audit` 在 CI 中只接受可解析且严格早于 HEAD 的精确基线。GitHub PR/push 使用事件
基线；默认分支 `repository_dispatch` 资格运行由 scope 选择 `HEAD^1`，Backend 与 Android
只消费同一输出。Gitea manual workflow 继续使用 canonical merge-base。自比较、非祖先、
歧义或不可解析基线均失败；只有无 CI marker 的本地探索可跳过比较。

## 历史实现审计（非当前能力）

以下长项只保留旧 lifecycle/安全机制的审计背景，不是 current shipment、用户入口或可调用
Owner。当前正式能力与 HOLD 边界只看后文“运行与数据”和“数据保护当前边界”；其中出现的
backup、restore、repair、upgrade、uninstall 或 `-DeleteData` 现在时描述均不得作为产品承诺。

- 安装包使用小票夹图标和“小票夹后端服务”显示名,开始菜单会创建“打开小票夹 Web”和“数据目录”快捷方式。
- 安装器标准页面和按钮使用内置简体中文语言文件，并显式绑定可覆盖简中文字形的 Windows UI 字体；自定义数据目录/端口页面也保持中文。
- 安装器只有一套脚本与配置真源,并同时兼容 Windows PowerShell 5.1 / PowerShell 7 两种宿主:只从 HKLM PowerShell Core 安装记录动态发现位于受保护 Program Files、Microsoft 签名有效、`PSEdition=Core`、主版本不低于 7 且为 64 位进程的机器级 `pwsh.exe`;候选按规范路径确定性选择,用户目录中的执行别名不会被提权运行。没有可信 PS7 时自动回退系统自带 5.1,普通用户无需额外安装运行时。
- 安装向导会先让用户确认程序目录、数据目录和本机服务端口;若默认 `5432/8000` 被占用,会自动预填开发机常用隔离端口 `5440/8001`,也可以在界面中改成其它空闲端口。
- 首次安装默认使用 `C:\ProgramData\Ticketbox\pgdata` + `C:\ProgramData\Ticketbox\app`；当前 owner pairing handoff 与 repair latch 放在从 OS `CommonProgramFiles` 动态解析的 `Ticketbox\installer-state` 机器生命周期域。fresh install 会先原子建立并复核该目录的 SYSTEM/Administrators owner/ACL。旧 `owner-bootstrap.txt` / `owner-handoff-pending` 只按 no-follow 类型记录为审计对象：不读取内容、不迁移、不删除、不展示、不参与当前身份判断，也不能阻断新协议。只有当前协议自己的权威对象冲突、ACL 漂移或 reparse 才 fail closed。
- 每个提权 PowerShell 子步骤都写入独立受保护日志；Inno 先用 `SaveStringsToUTF8File` 建立带 UTF-8 BOM 的机器可读头（schema、installer owner PID、单调序号、context），再由 Windows PowerShell 5.1 或 PowerShell 7 `Start-Transcript -Append` 追加。这样两种宿主都保留同一可关联语义和可读中文，不依赖机器活动代码页。
- `app\.env` 由脚本写成 UTF-8 no BOM,`DATABASE_URL` 指向配置中动态读取的应用角色；上传大小、OCR、API 文档等应用默认值继续由后端 `config.py` 单源负责，安装器不复制一份。SCM 注入的 DataRoot、两类 recovery guard、v2 marker 路径与 Volume GUID 属于宿主权威；frozen launcher 在任何写目录前要求四项全部存在，拒绝 reparse marker，并校验 marker 的完整 DataRoot/InstallDir、稳定 junction 最终目标与 Volume GUID。bootstrap recovery guard 与 marker 必须同经 machine-owned runtime junction 指向同一 Volume GUID DataRoot，不能继续使用可被复用的盘符路径；marker 对 backend 服务 SID 仅授予读取，不授予写、删除、改名或父目录删除权。只有非 frozen 源码模式可以不带这组宿主权威；加载 backend 可写 `.env` 后仍会恢复原值，`.env` 不能清空安装隔离、伪造卷身份或移动数据根。
- 历史切片曾设计复制前备份、服务校验和停服机制；current Fresh shipment 不调用这些旧备份或升级准备 Owner。当前 preinstall 只允许无服务、无 PG 数据、无 `.env`、无 installed manifest/receipt/CURRENT 的真首装，或同一 immutable active intent 的重试；任何既有安装证据都在首笔 generation intent 前 fail closed。
- 保留数据 repair/reinstall、跨 release 升级和孤儿数据收编尚未实现。旧 lifecycle/C07 producer 已退役，不能通过旧 stage、READY、receipt 或 historical evidence 绕回 current/publication authority。
- Inno 从启动到复制、服务后置配置和卸载全程持有 `{commoncf64}\Ticketbox\installer-lifecycle.lock`，并动态写入受保护的持锁进程记录。owner 身份不是可复用的 PID 文本，而是 PID + Windows 进程创建 FILETIME；Inno 在启动 holder 前冻结自身创建时间，holder 用 `OpenProcess` + `GetProcessTimes` 验证直接父进程并终身等待同一 `SafeWaitHandle`，后续轮询绝不按 PID 重开或重新解释进程。ready 再声明 holder PID + 创建 FILETIME，Inno 同样取得并持续持有匹配句柄。子 PowerShell 必须是该不可变 owner 身份对应进程的直接子进程、确认零共享锁仍被占用且运行在 64 位宿主中，才可复用安装器总锁。每个 mutation child 先取得独占 operation lock，再校验直接父进程和主锁；该 operation lock 是本次调用的委托租约，其路径必须是 no-follow 普通受保护文件，reparse、目录、不可读或其他 malformed 形态在 holder probe 中都视为 active/indeterminate，不能触发权威释放。DataRoot holder 在目录句柄、marker 与 ready IPC 都已创建、复读并绑定 holder 身份/nonce 之前持续持有启动方的 operation lease，只通过显式回调完成一次性交接；它也打开并等待同一个已验证 owner handle。失败路径不提前释放。交接后即使 Inno 在子进程返回前退出或请求 release，机器锁 holder 与 DataRoot lease holder 也会保留到活动 operation lock 释放，避免仍在执行的已授权 child 失去目录/事务屏障。holder 启动/预检失败时，只有在目录 guard 与 operation lease 均已释放后，才向仍匹配原 owner handle 的 Setup 原子提交并复读 `stopped`；Setup 收到确认前保留本地 holder 状态并拒绝同进程重试。正式安装 mutation 必须同时带当前 Inno owner PID 与 lifecycle receipt；独立脚本只保留只读服务验证，不得自行提交安装。ready/release IPC 也只存在于该受保护机器根：holder 先验证机器根并拒绝 stale IPC，再向受保护 transient bootstrap 写入绑定当前 owner 身份的精确 `root_validated` 短命握手；Inno 收到该握手前不探测机器根子项，收到后才读取 ready。所有已原子发布的 lifecycle/DataRoot coordination artifact 读取均使用固定 `40 x 50 ms` 上限：PowerShell 只重试 Win32 sharing/lock violation `32/33`，ACL、格式、身份或内容错误立即失败；Inno 的读取 API 不返回 native code，因此只在这一受保护、不可原地修改的 IPC 层做同样的 2 秒有界读取重试，超时仍保留原 fail-closed 错误。holder 随后生成 256-bit 随机 nonce，声明真实 PID/创建 FILETIME 与 PowerShell 单源解析的 installer-state 路径；release 必须回传 nonce。DataRoot 目录链 lease 采用同一身份/nonce 协议；缺失链节点从首次可见起即具有最终 SYSTEM/Administrators ACL，新建 DataRoot 会在发布 ready 前写入并复读安装 marker。预先存在却没有 marker 的空 DataRoot 会在 ready 前拒绝，不能对可能仍被低权限进程持有写句柄的目录做事后 ACL 收编；非空无 marker 布局在所有普通安装路径都拒绝，只能交给未来独立隔离恢复/导入。Setup 不会从宽权限 `{tmp}` 直接提权执行 helper：manifest-bound 的受保护 bootstrap 输入集复制到 transient bootstrap 后逐项核对构建时 SHA-256，复制边界前再全量复核；输入数量不作为合同。uninstall holder 来自受保护 Program Files 安装目录，不冒充 bootstrap bundle。该目录不承载 lock/receipt/handoff 权威，`root_validated` 只证明本次 holder 已完成根验证，不能授权 mutation。
- DataRoot 长命权威单独归属 `hold_data_root_mutation_guard.ps1`；它不加载 release config、服务、数据库或 receipt，`prepare_bundled_upgrade.ps1` 只做短命升级准备。operation lock 路径的 no-follow 分类若因 sharing violation 或其他异常无法完成，一律视为 active/indeterminate，不释放机器/DataRoot 权威。pre-ready holder 死亡且没有 acknowledgement 时，Setup 只能通过同步 `-ConfirmStopped` 先取得 operation lock 并证明 ready absent；post-ready 死亡还必须复核 holder PID/creation FILETIME/nonce 和原身份已不存活。两条路径都在 guard/lease 全部释放后才清理 IPC 并向同一活 owner 原子提交 `stopped`。
- 缺失 DataRoot 的 holder 在已逐级验证并持有现存祖先句柄后、第一次创建目录前，采样 Windows Volume GUID 并把绑定 DataRoot/InstallDir/卷身份的 provisioning intent durable 到机器生命周期根；根句柄取得后和 marker 发布后再次核对卷身份，file/reparse 祖先或中途换卷都会保留 intent 并拒绝。目录或 marker 发布中断时，相同路径和卷只允许恢复精确 ACL 的空根并清理严格命名 staging。`ticketbox-data-root-v2` marker 以受保护 writer 从首次可见起获得最终 owner/ACL，并永久绑定规范 DataRoot、InstallDir 和 Volume GUID；只有复读 marker 且确认其卷身份仍等于当前挂载卷后才退役 intent。fresh prepare 同时校验 DataRoot 精确 ACL、marker no-follow 普通文件形态、精确 ACL/owner 和完整 v2 绑定；路径写对但权限不可信、位于替换卷或仍是 v1 的 marker 都不能授权收编。旧 v1 marker 可在既有安装证据验证后原子升级为受保护 v2；完全缺少 marker 的非空布局没有足够证据证明 PostgreSQL 树未被低权限主体改写，普通 installer 不认领、不补 ACL、不重新铸造权威。未来若要救回，只能通过独立隔离恢复/逻辑导入建立新的受保护 DataRoot。中断 intent 不自动改绑，改选路径必须进入显式 recovery，避免热插拔/VHD 或盘符复用制造第二个权威根。
- 正式 PG/backend SCM 路径不直接依赖可复用盘符。安装器从 OS `CommonApplicationData` 动态建立受保护 `TicketboxRuntimeBinding\data-root` junction，目标是 v2 marker 推导出的 Volume GUID DataRoot；PG `-D`、Shawl cwd/log 与 `TICKETBOX_DATA_DIR` 使用该稳定普通路径。binding 根只给两项服务 SID 继承 ReadExecute，junction target、ACL、marker 与当前卷每次都精确复核。当前 lifecycle receipt v9 固化 `data_volume_identity` 并绑定唯一 Database Generation CURRENT；stale recovery/commit/uninstall 在 mutation 前重验。创建根后未建 junction、只迁移一项服务、或删除 junction 后未删空根三个断点均可重入；只允许旧直连/新别名两种完整 SCM 合同，未知参数、错误 target、非空根或 ACL 漂移一律失败。
- PostgreSQL 活体宿主权威统一归属 `windows_database_safety.ps1`：解析器只接受当前安装目录内的精确 `pg_ctl runservice` SCM 合同，并从 `postmaster.pid` 复核 PID、端口与数据目录。legacy 物理 `DataRoot\pgdata` 仍执行整条祖先 no-reparse 校验；新 runtime 路径只在共享安装安全层两次验证专用 junction、Volume GUID target、v2 marker、ACL 与 PG/backend 服务 SID 后接受，不能把任意 reparse 当成受管路径。当前宿主合同使用 `ticketbox-postgresql-host-authority-v1`；C07-named 函数仅是待退役的产品 policy adapter，不拥有 Windows 路径/SCM 判定。失败统一投影为 `postgres_host_authority_validation_failed` / `TBX-INSTALL-POSTGRES-HOST`。
- 服务 argv 归属在 `windows_service_contract.ps1`，SCM 终态控制在 `windows_service_lifecycle.ps1`，SCM 登录账户与每服务 SID 的分离合同在 `windows_service_identity.ps1`，机器锁 provider/验证/持有协议在 `windows_lifecycle_lock.ps1`，Inno 早期入口只通过 `hold_installer_lifecycle_lock.ps1` 启动专职 holder；holder 先原子创建或 no-follow 验证机器根，再创建 lock/owner，Pascal 不在验证前触碰机器根子路径。loopback libpq、口令隔离、数据库数据根和 dump 防护归属在 `windows_database_safety.ps1`，后端 deadline 就绪与首次 owner 创建归属在 `windows_backend_bootstrap.ps1`，监听器暴露后的停服轮换归属在 `windows_bootstrap_exposure_recovery.ps1`，路径/ACL/marker/删除边界归属在 `windows_installation_safety.ps1`。安装、升级、桌面 GUI 的服务控制和卸载都争用同一把机器锁；GUI 每次变更 SCM 前还会动态读取安装注册表中的服务名，并通过已安装的 `install_bundled_services.ps1 -ValidateInstalledServicesOnly` 复核 release config、ImagePath、SCM 登录账户、每服务 SID、依赖、Shawl payload 与启动策略。各入口按动态策略与单调时钟 deadline 等待稳定态及 `running` / `stopped` / `absent`，服务记录缺失时也继续按登记端口和安装路径扫描孤儿进程。
- 面向 Inno UI/支持人员的 `ticketbox-install-public-failure-v3` 是 Windows 安装唯一通用失败投影，固定包含 support code、lifecycle stage、operation identity、显式的 installation identity 分配状态、retry class、独立的 database mutation state 与 protected/public log 路径；身份尚未安全建立时发布 `not_assigned` 和空 ID，不伪造占位身份。旧 C07 failure-summary publisher 已物理退役，历史文件不再参与当前安装、重试或恢复裁决。
- frozen backend 目录下本机运行生成的 `ticketbox-data\` 会从 Inno 输入中整目录排除,避免把开发机日志、配置或上传文件带进发布包。
- 数据根写 marker 前会拒绝根或任一祖先 junction/reparse point 并转 SYSTEM owner。根目录只给服务账户非继承 ReadExecute，PG/后端 FullControl 分别限制在 `pgdata` / `app` 子树，避免任一服务借父目录 `DELETE_CHILD` 删除兄弟目录；安装器在备份前就应用该拓扑，不会先给两服务跨树 FullControl。owner handoff 与单调 repair latch 位于机器生命周期锁目录下独立的 `installer-state`，仅 SYSTEM/Administrators 可访问，不随 DataRoot 备份、恢复或克隆回滚；已有有效 latch 只验证并保留第一次 reason/time，不被后续失败覆盖。安装事务另在从 OS `CommonApplicationData` 动态解析、与 DataRoot 不相交的 `TicketboxRuntimeState` 域发布无 secret 的 `installer-runtime-recovery-pending` 投影；目录从首次可见起即使用 SYSTEM/Administrators FullControl、backend 服务账户 ReadExecute 的精确 ACL，backend 不能删除或替换投影，旧 DataRoot restore 也不能让它倒退或消失。runtime-state 根必须是普通目录、guard 必须是普通文件；PowerShell 用 `FILE_FLAG_OPEN_REPARSE_POINT` no-follow 检查每级 entry，launcher 用 lexical `lstat` 检查整条祖先链。file-shaped root、directory-shaped guard、dangling junction/symlink、其他 reparse 或无法分类都不是“缺失”，卸载、修复和每个普通 HTTP 请求都必须 fail closed。Shawl 动态传入该路径，正式 commit 前普通业务统一返回 `503 installer_recovery_pending`，只放行安装 health 与一次性 owner bootstrap；commit 复读 completed receipt、清理已验证的 PG recovery toolset、提升服务策略、退役机器 latch，最后删除投影，服务无需重启即可恢复。安装成功还会原子写入仅 SYSTEM/Administrators 可读的持久安装身份，绑定 version floor、installation id、build manifest hash、路径、服务和端口；仅剩 PG 数据但该身份与旧安装证据都不可信时 fail closed。legacy 子项会递归重置 owner/显式 ACL；`initdb` 口令文件删不掉或删除后仍存在时安装立即中止，不会进入后端 ACL/启动阶段。
- 既有 backend/PG 在复制边界前已经 disabled；复制后的 backend SCM 记录也先以 disabled 创建或修复。machine runtime-state guard 创建、复读且 DataRoot ACL 收敛后，backend 才提升为 demand-start 供安装期受控启动。这样硬断电落在文件替换、服务注册与 guard 发布之间时 backend 仍不可启动，落在 demand-start 之后时 guard 已持久存在。下一次 repair 遇到 completed receipt 时先幂等续跑未完成的 tool cleanup、自启提升、latch 与 guard 退役，复读成功后才使旧 receipt 失效并开始新事务。
- 正式 Windows 首装通过 `/api/bootstrap/installation-owner` 在一个 PostgreSQL 事务中创建 installation owner claim 与一个 8 位、短期、一次性的 pairing child。claim 持久绑定同一 `operation_id` / `installation_id`；同一事务重试重放同一有效 child，过期后只换代 child 并递增 generation，不伪造新的安装 operation。响应不含 admin token、upload key 或任何用户长期 bearer。安装器把 pairing-only 结果原子发布为唯一的 `installation-owner-handoff-v2.txt`，文件同时绑定 claim generation、derivation index 与已冻结的安装器 PID/创建时间；崩溃修复只在持有同一生命周期锁并证明旧 owner 已死亡后原地重绑该文件。Inno 严格解析后只展示 8 位码与到期时间；完成安装时退役该短期文件，再以 `ExecAsOriginalUser` 启动普通用户的 Desktop Manager。Manager 消费 pairing code，并由该普通用户进程把新桌面 session 写入其自己的 Windows Credential Manager。提权安装器不会创建、复制或保存用户长期凭据。每一代 bootstrap listener 的暴露、隔离、停服轮换和失败回执仍由受保护 guard/intent 约束；日志与公开回执不得包含 secret。
- 卸载默认只删除归属校验通过的服务和程序文件，**保留 ProgramData 数据、安装身份、PG recovery toolset 与同机 repair/reinstall 所需的 machine state**。卸载先严格分类 runtime-state 根与 guard 的实际形态，再校验并 disabled backend；只有普通目录/普通文件合同成立且服务 SID 仍可验证时才退役 guard 与空 runtime-state 目录，随后删除 backend SCM 记录。backend 服务缺失时，任何仍存在或形态异常的 runtime-state 都 fail closed，不能用 `Test-Path -PathType` 把 malformed 状态误报为 absent；安装身份已部分或全部删除的重试 resolver 只读裁决 intent/receipt/state，随后必须先走同一 runtime projection 校验，才能退役空 installer-state。完整身份主流程也先只读验证 installer-state，再校验 runtime projection；staging cleanup 与 PG recovery toolset save 均在 projection 通过后执行。生命周期锁为取得互斥权而清理自己严格命名的非权威临时写入不算业务状态迁移，不能借此删除 receipt/intent/identity。卸载前同时核对 SCM 稳定态与 `pg_ctl status -D`，服务/数据簇进程不一致即失败；删除 PG 服务前再次确认数据簇已停。普通保留数据卸载若存在 completed lifecycle receipt，必须先验证，并在两项服务都删除后退役它，避免下一次重装把旧 commit 当成待续跑事务；无 receipt 只兼容旧版保留数据卸载。手动 `-DeleteData` 还必须通过注册表 DataRoot、安装专属 JSON marker、无重解析点和 installer-state 绑定检查；停服并验证 completed lifecycle receipt 后，先原子写入绑定 receipt SHA-256/InstallDir/DataRoot 的 `delete-data-in-progress.json`，再退役 receipt 并删除可能承载其备份证据的数据根。DataRoot 精确删除把 `.ticketbox-data-root.json` 留到 payload 之后；marker 已删时，只有已验证 intent 才能收敛空根，非空残树拒绝。PG recovery 完整校验后另以 CreateNew 发布 `DELETE_IN_PROGRESS.json`，并把它作为最后删除的续跑 latch；既有 `BUILD_COMPLETE.json` 本身不授权删除。receipt 缺失而没有受保护意图、或 receipt 是目录/reparse/损坏文件时拒绝删除；所有分支先由共享 no-follow 分类器裁决 receipt，原生句柄对悬空目录 junction 返回路径缺失时会回退枚举父目录项，不能误报 retired。DataRoot 后依次退役恢复工具与注册身份，handoff/latch/delete intent 和空 installer-state 最后清理。注册身份已经部分或全部删除时只能从受保护 intent 恢复绑定 DataRoot；intent 已退役后只允许清理精确 ACL 且为空的 state 目录，任一步失败都按剩余权威证据幂等收敛。

这组历史细节不声明升级能力：旧备份/停服源码没有 current caller，也不进入 frozen shipment；版本化程序目录、跨 release 恢复和真实故障注入继续 HOLD，不能用源码检查或 `pg_restore --list` 冒充完成。

高级命令行参数仍可用于自动化安装(传给安装器 EXE):

```
Ticketbox-Setup-<version>.exe /TicketboxDataRoot="D:\TicketboxData" /TicketboxBackendPort=8000 /TicketboxPgPort=5432
```

开发机若已有本机 PostgreSQL/源码后端占用默认 `5432/8000`,直接双击安装器即可在“服务端口”页面看到自动预填的 `5440/8001`。安装器会在正式复制文件前检测所选端口;若端口已被占用,会停在向导页提示换端口,避免复制文件后后置服务脚本失败。

注意:当前发布工程明确不做代码签名,Windows SmartScreen 可能提示未知发布者;发布验收只保留未签名安装器的 SmartScreen walkthrough。

## 运行与数据

正式 Windows 分发只支持 Inno 安装器注册的 Shawl/SCM 服务宿主。直接双击 frozen backend、
手工创建空库或旧式 PowerShell 一键安装不再是受支持入口；数据库初始化只在安装器持有的
Fresh generation 动作中执行。

Generation Owner 当前只闭合全新机器上的 `empty source -> target -> candidate -> CURRENT`
首次安装；它要求不存在 predecessor/current，并执行冻结的 Alembic program。完整数据集备份/恢复、
既有安装升级、保留数据 repair/reinstall、跨 release 未完成事务和二进制/schema 降级尚未实现，均继续
`QUALIFIED_HOLD`；旧 C07 READY/stage/current 代码不是兼容入口，也不得重新启用。

服务宿主通过 Shawl 把 `TICKETBOX_DATA_DIR` 设置为 machine-owned
`{commonappdata}\TicketboxRuntimeBinding\data-root\app` junction；v2 DataRoot marker 与
Volume GUID 把它绑定到安装器选择的物理 `<DataRoot>\app`。因此 `.env`、uploads、logs
等当前 backend 运行时文件位于物理 DataRoot，不会写入 Program Files，也不直接依赖可复用盘符。

`launch.py` 在 import `app.*` 之前把 `UPLOAD_DIR` 指向数据目录、并把 uvicorn + app 日志配到 `logs/backend.log`(windowed `console=False` 无 stdout,改写文件);若存在 `<data>\.env` 则**优先**采用其中的值(`override=True`)。`DATABASE_URL` 不在这里默认——后端是 PostgreSQL-only,要么在 `.env` 里设、要么回落到 `app.config` 的本机 PostgreSQL 默认(EXE 假设本机已装 PostgreSQL 服务)。

服务环境可用变量（或写进受安装器保护的 `<DataRoot>\app\.env`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `TICKETBOX_HOST` | `127.0.0.1` | bind host |
| `TICKETBOX_PORT` | `8000` | 端口 |
| `DATABASE_URL` | （`app.config` 本机 PostgreSQL 默认） | 数据库（PostgreSQL-only，见下） |
| `UPLOAD_DIR` | `<data>/uploads` | 上传目录 |

`PUBLIC_BASE_URL` 不再属于 Generation、restore 或 `.env` authority。正式安装首次启动由
backend-owned store 以 create-only 默认值发布 service-owned runtime projection；此后只能在
Owner Console 修改。安装重试只校验并复用已有值，不覆盖 operator 设置。

### 数据保护当前边界

正式安装的桌面管理器只连接产品内 CSV 导入与已确认流水 CSV 导出，不出货或调用完整数据集
备份/恢复 mutation。backend 中保留的 complete-dataset 源码和 PostgreSQL 演练只作审计与演进输入，
不会被收进 frozen runtime，也不是当前 Windows 产品能力。

[POSTGRES_MIGRATION.md](../../docs/runbook/POSTGRES_MIGRATION.md) 的直接 `pg_restore` 只用于
源码/测试 scratch。没有同一 exact-head EXE 的干净 Windows VM 全生命周期证据前，仍为
`QUALIFIED_HOLD`。

## 冻结要点（给维护者）

- 入口 `packaging/launch.py`;spec `packaging/ticketbox-backend.spec`。
- 形态:**onedir + `console=False`**(ADR-0047 §8)。`EXE(exclude_binaries=True)` + `COLLECT(...)` → `dist/ticketbox-backend/`(EXE + `_internal/`)。窗口化进程无 `sys.stdout/stderr`,所以 `launch.py` 在起 uvicorn 前用 `logging.config.dictConfig` 把 uvicorn + app 日志接到 `DATA_ROOT/logs/backend.log`(`RotatingFileHandler`),并给 uvicorn 传 `log_config=None`——否则 uvicorn 默认配置会写 `ext://sys.stdout`,`None.write` 崩。
- `app/config.py`、`app/database` 用 `Path(__file__).parents[N]` 解析路径,冻结后指向 `sys._MEIPASS`(onedir 下即 `_internal/` 目录)。所以 spec 把 `alembic.ini` 和 `migrations/` 打到 **bundle 根**(`backend_root`),`static/` `templates/` 留在 `app/` 下。
- 构建先从受控源码快照编译并哈希 `DATABASE_GENERATION_PROGRAM.json`；安装 helper、provenance、installed payload lease 与 frozen backend `init_db()` 都消费这一个 base→head 程序。该程序拥有允许执行的目标、lineage 与 revision bytes，Alembic 在 caller-owned transaction 内拥有 revision graph 执行和 `alembic_version` 状态推进；普通 backend 不拥有安装期 DDL，也不能在程序外另选 target。程序、revision bytes、lineage 或最终 revision 不一致时一律 fail closed。
- 动态导入(uvicorn 的 loop/protocol、`app.*` 路由、postgresql 方言 + psycopg 驱动)由 spec 的 `collect_submodules` + `hiddenimports` 兜底;新增依赖若运行时报 `ModuleNotFoundError`,在 spec 的 `hiddenimports` 补一行再重建。
- PyInstaller 冻结 EXE 可能触发杀软误报(无签名)。正式分发建议代码签名。

## 与 GUI 管理器的关系

`desktop/` 的后端管理器支持源码监督与正式安装模式；正式模式通过 Windows SCM 管理服务，并连接
配对、上传入口、产品 Web、CSV 导入/导出与诊断等当前已资格能力。完整备份/恢复 owner 不属于当前
Inno/provenance 出货集合。
