# 小票夹后端 · EXE / Inno 打包

把 FastAPI 后端冻结成 onedir EXE,并可进一步打成 ADR-0047 的 Windows 安装器:捆绑 PostgreSQL + 后端服务,每台机器跑自己的实例(隐私优先,不共享服务器),用自己的 Android App 连。

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

## 档 B:Inno 捆绑安装器(ADR-0047)

档 B 是正式分发路线:安装器把程序放进 `C:\Program Files\Ticketbox`,把数据放进 `C:\ProgramData\Ticketbox`,并注册两个 Windows 服务:

| 服务 | 账户 | 说明 |
|---|---|---|
| `TicketboxPg` | `NT SERVICE\TicketboxPg` | 捆绑 PostgreSQL 17,簇在 `...\pgdata` |
| `TicketboxBackend` | `NT SERVICE\TicketboxBackend` | Shawl 包 frozen backend,依赖 `TicketboxPg` |

构建前置:

1. 已生成 frozen backend:`backend\dist\ticketbox-backend\ticketbox-backend.exe`。
2. 已裁出捆绑 PG:`backend\packaging\vendor\pg\bin\pg_ctl.exe`。
3. 已放好 Shawl:`backend\packaging\vendor\shawl\shawl.exe`。
4. 构建机安装 Inno Setup 6,或用 `-InnoCompiler` 指定 `ISCC.exe`。
5. 仓库内置 Inno 简体中文语言文件:`backend\packaging\languages\ChineseSimplified.isl`。

命令:

```
cd backend
packaging\build_inno_installer.ps1 -CheckInputsOnly   # 无 Inno 时只校验输入
packaging\build_inno_installer.ps1                    # 原子发布完整版本目录
```

安装包版本只能从 `app/version.py` 的 `BACKEND_VERSION` 动态读取；构建工具版本只能从
`packaging/windows-build-toolchain.json` 读取；服务/数据库身份、默认/隔离端口、SCM 策略、
就绪等待、bootstrap 默认值和密钥强度只能从 `packaging/windows-release-config.json` 读取。构建脚本只把向导所需值
注入 Inno，升级预检、安装和卸载则通过 `windows_release_config.ps1` 读取并校验配置，不再从 Inno 重复传递服务名或
超时。覆盖升级在复制前读取已安装的 N-1 config 校验旧服务，并把该已验证配置保存到 Inno 临时快照，复制后仍用 N-1
策略完成旧服务删除，注册后才以 N config 验证新服务；服务名、数据库名和数据库角色
属于持久身份，变化必须有显式迁移，不能伪装成普通策略更新。`build_inno_installer.ps1` 是受支持的构建入口：它绑定实际
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

安装行为:

- 安装包使用小票夹图标和“小票夹后端服务”显示名,开始菜单会创建“打开小票夹 Web”和“数据目录”快捷方式。
- 安装器标准页面和按钮使用内置简体中文语言文件;自定义数据目录/端口页面也保持中文。
- 安装器只有一套脚本与配置真源,并同时兼容 Windows PowerShell 5.1 / PowerShell 7 两种宿主:只从 HKLM PowerShell Core 安装记录动态发现位于受保护 Program Files、Microsoft 签名有效、`PSEdition=Core`、主版本不低于 7 且为 64 位进程的机器级 `pwsh.exe`;候选按规范路径确定性选择,用户目录中的执行别名不会被提权运行。没有可信 PS7 时自动回退系统自带 5.1,普通用户无需额外安装运行时。
- 安装向导会先让用户确认程序目录、数据目录和本机服务端口;若默认 `5432/8000` 被占用,会自动预填开发机常用隔离端口 `5440/8001`,也可以在界面中改成其它空闲端口。
- 首次安装默认使用 `C:\ProgramData\Ticketbox\pgdata` + `C:\ProgramData\Ticketbox\app`；owner handoff 与 repair latch 放在从 OS `CommonProgramFiles` 动态解析的 `Ticketbox\installer-state` 机器生命周期域。
- `app\.env` 由脚本写成 UTF-8 no BOM,`DATABASE_URL` 指向配置中动态读取的应用角色；上传大小、OCR、API 文档等应用默认值继续由后端 `config.py` 单源负责，安装器不复制一份。SCM 注入的 DataRoot、两类 recovery guard、v2 marker 路径与 Volume GUID 属于宿主权威；frozen launcher 在任何写目录前要求四项全部存在，拒绝 reparse marker，并校验 marker 的完整 DataRoot/InstallDir、稳定 junction 最终目标与 Volume GUID。bootstrap recovery guard 与 marker 必须同经 machine-owned runtime junction 指向同一 Volume GUID DataRoot，不能继续使用可被复用的盘符路径；marker 对 backend 服务 SID 仅授予读取，不授予写、删除、改名或父目录删除权。只有非 frozen 源码模式可以不带这组宿主权威；加载 backend 可写 `.env` 后仍会恢复原值，`.env` 不能清空安装隔离、伪造卷身份或移动数据根。
- 覆盖升级会在 Inno **复制新程序文件之前**校验两个服务的完整 argv、虚拟服务账户和动态路径，停止后端，并证明 loopback `DATABASE_URL` 命中预期 PG 端口、数据库、角色和数据根。所有 `psql` / `pg_dump` 连接都要求 `SCRAM-SHA-256`；口令只进入创建时即受保护的短命 passfile，绝不进入参数、日志或 `PGPASSWORD`，命令结束后验证删除。升级快照写入后端服务账户无权删除的 `installer-backups`；复制前失败会恢复旧启动策略和运行态。
- 若旧版本已经卸载服务和 HKLM 安装登记、但明确保留了 ProgramData，修复安装只接受受保护 ACL、无 reparse、目标 PG major 匹配、可信 version floor 且 `.env` 指向所选本机数据库的 legacy 布局。常态 version floor 来自持久安装身份；从尚未生成该身份的旧安装首次升级时，只允许稳定 AppId、产品名、HKLM DataRoot/InstallDir 和 Inno DisplayVersion 全部互相绑定的一次性迁移，孤儿数据继续 fail closed。目标 PG 工具复制完成后，安装器先在回执记录清理义务，再以配置中的正式 PG 服务名注册 demand-start SCM 服务，并在 `NT SERVICE\<pg_service_name>` 虚拟账户下启动精确 DataRoot；toolset 的每层 ACL 与 completion 读取都必须携带同一个 recovery service ReadExecute SID。连接的数据根/端口和 `pg_dump` 通过后先停删临时服务、再移除该 SID，才允许推进回执，不能让清理校验拒绝自身合法 SID 并留下孤儿写者。若服务删除后在 SID 退役前中断，重试仍通过 `sc.exe showsid` 从服务名导出同一虚拟 SID，只接受 clean/clean+SID 的精确过渡 ACL 并幂等收敛，不能因 SCM 记录已缺失就提前返回。PG recovery 根、delete latch 与直属 staging 全部按 no-follow entry 分类；dangling reparse、file-shaped root、大小写变体、相似名称或权限漂移一律中止，不能因跟随查询或枚举器大小写敏感而静默漏过。断电后的下一次修复也必须先完成该清理；备份提交前不执行建表、业务迁移或 DataRoot ACL 收编。
- Inno 从启动到复制、服务后置配置和卸载全程持有 `{commoncf64}\Ticketbox\installer-lifecycle.lock`，并动态写入受保护的持锁进程记录。owner 身份不是可复用的 PID 文本，而是 PID + Windows 进程创建 FILETIME；Inno 在启动 holder 前冻结自身创建时间，holder 用 `OpenProcess` + `GetProcessTimes` 验证直接父进程并终身等待同一 `SafeWaitHandle`，后续轮询绝不按 PID 重开或重新解释进程。ready 再声明 holder PID + 创建 FILETIME，Inno 同样取得并持续持有匹配句柄。子 PowerShell 必须是该不可变 owner 身份对应进程的直接子进程、确认零共享锁仍被占用且运行在 64 位宿主中，才可复用安装器总锁。每个 mutation child 先取得独占 operation lock，再校验直接父进程和主锁；该 operation lock 是本次调用的委托租约，其路径必须是 no-follow 普通受保护文件，reparse、目录、不可读或其他 malformed 形态在 holder probe 中都视为 active/indeterminate，不能触发权威释放。DataRoot holder 在目录句柄、marker 与 ready IPC 都已创建、复读并绑定 holder 身份/nonce 之前持续持有启动方的 operation lease，只通过显式回调完成一次性交接；它也打开并等待同一个已验证 owner handle。失败路径不提前释放。交接后即使 Inno 在子进程返回前退出或请求 release，机器锁 holder 与 DataRoot lease holder 也会保留到活动 operation lock 释放，避免仍在执行的已授权 child 失去目录/事务屏障。holder 启动/预检失败时，只有在目录 guard 与 operation lease 均已释放后，才向仍匹配原 owner handle 的 Setup 原子提交并复读 `stopped`；Setup 收到确认前保留本地 holder 状态并拒绝同进程重试。正式安装/升级 mutation 必须同时带当前 Inno owner PID 与 lifecycle receipt；独立脚本只保留只读服务验证，不得自行提交安装。ready/release IPC 也只存在于该受保护机器根：holder 先验证机器根并拒绝 stale IPC，再向受保护 transient bootstrap 写入绑定当前 owner 身份的精确 `root_validated` 短命握手；Inno 收到该握手前不探测机器根子项，收到后才读取 ready。holder 随后生成 256-bit 随机 nonce，声明真实 PID/创建 FILETIME 与 PowerShell 单源解析的 installer-state 路径；release 必须回传 nonce。DataRoot 目录链 lease 采用同一身份/nonce 协议；缺失链节点从首次可见起即具有最终 SYSTEM/Administrators ACL，新建 DataRoot 会在发布 ready 前写入并复读安装 marker。预先存在却没有 marker 的空 DataRoot 会在 ready 前拒绝，不能对可能仍被低权限进程持有写句柄的目录做事后 ACL 收编；非空无 marker 布局在所有普通 install/repair/upgrade/preserved-data 路径都拒绝，只能交给未来独立隔离恢复/导入。没有委托操作时 owner handle 变为 signaled 会触发 holder 清理 IPC，有委托操作时则等 child 释放 operation lock 后再清理。Setup 不会从宽权限 `{tmp}` 直接提权执行 helper：14 项内嵌输入复制到受保护 transient bootstrap 后逐项核对构建时 SHA-256，复制边界前再全量复核。uninstall 的 holder 来自受保护 Program Files 安装目录，不把它冒充成重新校验的 14 项 bundle；setup/uninstall 的运行期动态 runner 都写入独立 transient bootstrap、收紧 ACL、记录并在调用前复核 SHA-256。该目录不承载任何 lock/receipt/handoff 权威，`root_validated` 只证明本次 holder 已完成根验证，不能授权 mutation。公开 `Global` mutex / Inno `AppMutex` 可被低权限进程预先占用，已从合同移除；受保护 holder/lock/owner/receipt 是 setup、repair、upgrade、uninstall 与 GUI 唯一共享的生命周期串行权威。
- DataRoot 长命权威单独归属 `hold_data_root_mutation_guard.ps1`；它不加载 release config、服务、数据库或 receipt，`prepare_bundled_upgrade.ps1` 只做短命升级准备。operation lock 路径的 no-follow 分类若因 sharing violation 或其他异常无法完成，一律视为 active/indeterminate，不释放机器/DataRoot 权威。pre-ready holder 死亡且没有 acknowledgement 时，Setup 只能通过同步 `-ConfirmStopped` 先取得 operation lock 并证明 ready absent；post-ready 死亡还必须复核 holder PID/creation FILETIME/nonce 和原身份已不存活。两条路径都在 guard/lease 全部释放后才清理 IPC 并向同一活 owner 原子提交 `stopped`。
- 缺失 DataRoot 的 holder 在已逐级验证并持有现存祖先句柄后、第一次创建目录前，采样 Windows Volume GUID 并把绑定 DataRoot/InstallDir/卷身份的 provisioning intent durable 到机器生命周期根；根句柄取得后和 marker 发布后再次核对卷身份，file/reparse 祖先或中途换卷都会保留 intent 并拒绝。目录或 marker 发布中断时，相同路径和卷只允许恢复精确 ACL 的空根并清理严格命名 staging。`ticketbox-data-root-v2` marker 以受保护 writer 从首次可见起获得最终 owner/ACL，并永久绑定规范 DataRoot、InstallDir 和 Volume GUID；只有复读 marker 且确认其卷身份仍等于当前挂载卷后才退役 intent。fresh prepare 同时校验 DataRoot 精确 ACL、marker no-follow 普通文件形态、精确 ACL/owner 和完整 v2 绑定；路径写对但权限不可信、位于替换卷或仍是 v1 的 marker 都不能授权收编。旧 v1 marker 可在既有安装证据验证后原子升级为受保护 v2；完全缺少 marker 的非空布局没有足够证据证明 PostgreSQL 树未被低权限主体改写，普通 installer 不认领、不补 ACL、不重新铸造权威。未来若要救回，只能通过独立隔离恢复/逻辑导入建立新的受保护 DataRoot。中断 intent 不自动改绑，改选路径必须进入显式 recovery，避免热插拔/VHD 或盘符复用制造第二个权威根。
- 正式 PG/backend SCM 路径不直接依赖可复用盘符。安装器从 OS `CommonApplicationData` 动态建立受保护 `TicketboxRuntimeBinding\data-root` junction，目标是 v2 marker 推导出的 Volume GUID DataRoot；PG `-D`、Shawl cwd/log 与 `TICKETBOX_DATA_DIR` 使用该稳定普通路径。binding 根只给两项服务 SID 继承 ReadExecute，junction target、ACL、marker 与当前卷每次都精确复核。lifecycle receipt v7 同时固化 `data_volume_identity`，stale recovery/commit/uninstall 在 mutation 前重验。创建根后未建 junction、只迁移一项服务、或删除 junction 后未删空根三个断点均可重入；只允许旧直连/新别名两种完整 SCM 合同，未知参数、错误 target、非空根或 ACL 漂移一律失败。
- 服务 argv 归属在 `windows_service_contract.ps1`，SCM 终态控制在 `windows_service_lifecycle.ps1`，机器锁 provider/验证/持有协议在 `windows_lifecycle_lock.ps1`，Inno 早期入口只通过 `hold_installer_lifecycle_lock.ps1` 启动专职 holder；holder 先原子创建或 no-follow 验证机器根，再创建 lock/owner，Pascal 不在验证前触碰机器根子路径。loopback libpq、口令隔离、数据库数据根和 dump 防护归属在 `windows_database_safety.ps1`，后端 deadline 就绪与首次 owner 创建归属在 `windows_backend_bootstrap.ps1`，监听器暴露后的停服轮换归属在 `windows_bootstrap_exposure_recovery.ps1`，路径/ACL/marker/删除边界归属在 `windows_installation_safety.ps1`。安装、升级、桌面 GUI 的服务控制和卸载都争用同一把机器锁；GUI 每次变更 SCM 前还会动态读取安装注册表中的服务名，并通过已安装的 `install_bundled_services.ps1 -ValidateInstalledServicesOnly` 复核 release config、ImagePath、虚拟账户、依赖、Shawl payload 与启动策略。各入口按动态策略与单调时钟 deadline 等待稳定态及 `running` / `stopped` / `absent`，服务记录缺失时也继续按登记端口和安装路径扫描孤儿进程。
- frozen backend 目录下本机运行生成的 `ticketbox-data\` 会从 Inno 输入中整目录排除,避免把开发机日志、配置或上传文件带进发布包。
- 数据根写 marker 前会拒绝根或任一祖先 junction/reparse point 并转 SYSTEM owner。根目录只给服务账户非继承 ReadExecute，PG/后端 FullControl 分别限制在 `pgdata` / `app` 子树，避免任一服务借父目录 `DELETE_CHILD` 删除兄弟目录；安装器在备份前就应用该拓扑，不会先给两服务跨树 FullControl。owner handoff 与单调 repair latch 位于机器生命周期锁目录下独立的 `installer-state`，仅 SYSTEM/Administrators 可访问，不随 DataRoot 备份、恢复或克隆回滚；已有有效 latch 只验证并保留第一次 reason/time，不被后续失败覆盖。安装事务另在从 OS `CommonApplicationData` 动态解析、与 DataRoot 不相交的 `TicketboxRuntimeState` 域发布无 secret 的 `installer-runtime-recovery-pending` 投影；目录从首次可见起即使用 SYSTEM/Administrators FullControl、backend 服务账户 ReadExecute 的精确 ACL，backend 不能删除或替换投影，旧 DataRoot restore 也不能让它倒退或消失。runtime-state 根必须是普通目录、guard 必须是普通文件；PowerShell 用 `FILE_FLAG_OPEN_REPARSE_POINT` no-follow 检查每级 entry，launcher 用 lexical `lstat` 检查整条祖先链。file-shaped root、directory-shaped guard、dangling junction/symlink、其他 reparse 或无法分类都不是“缺失”，卸载、修复和每个普通 HTTP 请求都必须 fail closed。Shawl 动态传入该路径，正式 commit 前普通业务统一返回 `503 installer_recovery_pending`，只放行安装 health 与一次性 owner bootstrap；commit 复读 completed receipt、清理已验证的 PG recovery toolset、提升服务策略、退役机器 latch，最后删除投影，服务无需重启即可恢复。安装成功还会原子写入仅 SYSTEM/Administrators 可读的持久安装身份，绑定 version floor、installation id、build manifest hash、路径、服务和端口；仅剩 PG 数据但该身份与旧安装证据都不可信时 fail closed。legacy 子项会递归重置 owner/显式 ACL；`initdb` 口令文件删不掉或删除后仍存在时安装立即中止，不会进入后端 ACL/启动阶段。
- 既有 backend/PG 在复制边界前已经 disabled；复制后的 backend SCM 记录也先以 disabled 创建或修复。machine runtime-state guard 创建、复读且 DataRoot ACL 收敛后，backend 才提升为 demand-start 供安装期受控启动。这样硬断电落在文件替换、服务注册与 guard 发布之间时 backend 仍不可启动，落在 demand-start 之后时 guard 已持久存在。下一次 repair 遇到 completed receipt 时先幂等续跑未完成的 tool cleanup、自启提升、latch 与 guard 退役，复读成功后才使旧 receipt 失效并开始新事务。
- 首次安装会通过一次性 HTTP bootstrap 创建 owner,凭证写入从机器生命周期锁目录动态派生、仅 SYSTEM/Administrators 可读的 `installer-state\owner-bootstrap.txt`,随后从 `.env` 清掉 bootstrap 开关。每一代 HTTP listener 一旦暴露，安装流程都会先原子写入同 ACL 的 guard/intent 并把 `.env` 切到无 secret 隔离态，之后才停服、离线轮换确定性凭据并撤销暴露窗口内增发的 token/link/device；停服失败也保留隔离证据。若 8 位 replacement pairing code 与历史记录碰撞，后端在任何凭证变更前返回专用内部结果，PowerShell 原子换代 replacement secret 后重试。维护失败还会原子留下不含 secret 的 `bootstrap-exposure-recovery-result.json`，父 PowerShell 只读取受保护、大小受限、schema/operation id 匹配的诊断结果。owner handoff v2 同时绑定 InstallDir、DataRoot、凭据文件 hash 与进入机器锁时已经验证并冻结的安装进程 PID/创建 FILETIME；marker writer 不在提交时重新按 PID 查询 StartTime，因此 PID 重用不能把无关进程写成新 owner。pending 首次发布只能 CreateNew，确认和死亡安装器接管只能在校验后原子替换；活的原 owner 不能被另一安装器接管，原 owner 崩溃后只能由持有生命周期锁的修复安装重绑。Inno 以 UTF-8 读取并在完成页真正展示一次绑定信息后才清除，避免晚失败永久跳过交付，也不把 token 放进命令行、日志或宽权限临时目录。
- 卸载默认只删除归属校验通过的服务和程序文件，**保留 ProgramData 数据、安装身份、PG recovery toolset 与同机 repair/reinstall 所需的 machine state**。卸载先严格分类 runtime-state 根与 guard 的实际形态，再校验并 disabled backend；只有普通目录/普通文件合同成立且服务 SID 仍可验证时才退役 guard 与空 runtime-state 目录，随后删除 backend SCM 记录。backend 服务缺失时，任何仍存在或形态异常的 runtime-state 都 fail closed，不能用 `Test-Path -PathType` 把 malformed 状态误报为 absent；安装身份已部分或全部删除的重试 resolver 只读裁决 intent/receipt/state，随后必须先走同一 runtime projection 校验，才能退役空 installer-state。完整身份主流程也先只读验证 installer-state，再校验 runtime projection；staging cleanup 与 PG recovery toolset save 均在 projection 通过后执行。生命周期锁为取得互斥权而清理自己严格命名的非权威临时写入不算业务状态迁移，不能借此删除 receipt/intent/identity。卸载前同时核对 SCM 稳定态与 `pg_ctl status -D`，服务/数据簇进程不一致即失败；删除 PG 服务前再次确认数据簇已停。普通保留数据卸载若存在 completed lifecycle receipt，必须先验证，并在两项服务都删除后退役它，避免下一次重装把旧 commit 当成待续跑事务；无 receipt 只兼容旧版保留数据卸载。手动 `-DeleteData` 还必须通过注册表 DataRoot、安装专属 JSON marker、无重解析点和 installer-state 绑定检查；停服并验证 completed lifecycle receipt 后，先原子写入绑定 receipt SHA-256/InstallDir/DataRoot 的 `delete-data-in-progress.json`，再退役 receipt 并删除可能承载其备份证据的数据根。DataRoot 精确删除把 `.ticketbox-data-root.json` 留到 payload 之后；marker 已删时，只有已验证 intent 才能收敛空根，非空残树拒绝。PG recovery 完整校验后另以 CreateNew 发布 `DELETE_IN_PROGRESS.json`，并把它作为最后删除的续跑 latch；既有 `BUILD_COMPLETE.json` 本身不授权删除。receipt 缺失而没有受保护意图、或 receipt 是目录/reparse/损坏文件时拒绝删除；所有分支先由共享 no-follow 分类器裁决 receipt，原生句柄对悬空目录 junction 返回路径缺失时会回退枚举父目录项，不能误报 retired。DataRoot 后依次退役恢复工具与注册身份，handoff/latch/delete intent 和空 installer-state 最后清理。注册身份已经部分或全部删除时只能从受保护 intent 恢复绑定 DataRoot；intent 已退役后只允许清理精确 ACL 且为空的 state 目录，任一步失败都按剩余权威证据幂等收敛。

当前升级边界:复制新文件前的失败可恢复旧服务状态;新文件复制已经开始后的二进制/schema 自动回滚尚未宣称完成。此时可验证数据库快照仍保留,但版本化程序目录、自动恢复和真实故障注入属于后续原子升级切片,不能用“`pg_restore --list` 通过”代替。

高级命令行参数仍可用于自动化安装(传给安装器 EXE):

```
Ticketbox-Setup-<version>.exe /TicketboxDataRoot="D:\TicketboxData" /TicketboxBackendPort=8000 /TicketboxPgPort=5432
```

开发机若已有本机 PostgreSQL/源码后端占用默认 `5432/8000`,直接双击安装器即可在“服务端口”页面看到自动预填的 `5440/8001`。安装器会在正式复制文件前检测所选端口;若端口已被占用,会停在向导页提示换端口,避免复制文件后后置服务脚本失败。

注意:当前发布工程明确不做代码签名,Windows SmartScreen 可能提示未知发布者;发布验收只保留未签名安装器的 SmartScreen walkthrough。

## 档 A:本机 PostgreSQL 一键安装(legacy)

已装好 PostgreSQL 后,把 `ticketbox-backend\` 文件夹、`install_ticketbox.ps1`、
`windows-release-config.json`、`windows_release_config.ps1`、
`windows_installation_safety.ps1`、`windows_lifecycle_lock.ps1` 和
`fix_table_owners.sql`(可选,属主修复兜底)放同一目录,右键
`install_ticketbox.ps1` →「用 PowerShell 运行」。向导会:

1. 定位 `psql.exe`(环境变量 `PG_BIN` → `PATH` → `C:\Program Files\PostgreSQL\<最高版本>\bin`);
2. 用超级用户(装库时设的 `postgres` 口令)**只建空角色 + 空库**(`OWNER=ticketbox`);
3. 生成 `ticketbox-data\.env`(**无 BOM**),`DATABASE_URL` 指向应用角色;
4. **首次启动 EXE 以应用角色 `ticketbox` 加载唯一 Alembic head 并执行 `upgrade`**——空库也只走迁移图建表，
   Alembic 缺失、lineage 非法或迁移后 revision 不等于 head 都 fail closed；表属主自然归位(堵 owner 错位陷阱，
   见 [POSTGRES_MIGRATION.md](../../docs/runbook/POSTGRES_MIGRATION.md) §3),随后自检非
   `ticketbox` 属主的表为 0,异常时跑 `fix_table_owners.sql` 归位;
5. 经一次性 HTTP bootstrap 创建 owner 身份,凭证 + **Android 配对码**写入
   `ticketbox-data\owner-bootstrap.txt`,随后清掉 `.env` 里的一次性 bootstrap 开关;
6. 注册开机自启任务计划(`-SkipScheduledTask` 可跳过)。

```
powershell -ExecutionPolicy Bypass -File install_ticketbox.ps1
# 可选参数:-Port 8000 -DbPort 5432 -PublicBaseUrl https://api.example.com
# 非交互模式:-NonInteractive
#             -PostgresSuperPasswordFile <受保护的一次性超级用户口令文件>
# 既有角色重跑时再加:
#             -PostgresRolePasswordFile <受保护的一次性应用角色口令文件>
```

交互模式会用安全输入框询问口令。非交互密码文件必须是单行 UTF-8、关闭 ACL 继承，
且只允许当前用户、`SYSTEM` 或 `Administrators` 读取；脚本读取后会验证删除。不要把
数据库口令直接放进命令行、批处理参数或 CI 日志。

红线:建角色/建库才用超级用户,**建表只能由应用角色连接**;`.env` 不带 BOM;不依赖
Docker/WSL/PS7。档 A 仍假设本机已装 PostgreSQL 服务,主要用于老用户/开发机临时安装;新分发优先用上面的档 B。

## 运行与数据

双击 `ticketbox-backend\ticketbox-backend.exe`,默认监听 `127.0.0.1:8000`(窗口化,不弹控制台窗口)。

档 A/直接双击时,所有**可写数据**放在 EXE 旁的 `ticketbox-data/`(onedir 程序文件夹内、与 `_internal\` 同级;冻结的 bundle 本身只读/临时):

```
ticketbox-backend/
├── ticketbox-backend.exe
├── _internal/          PyInstaller 运行时（依赖 + alembic.ini + migrations/ + 静态资源）
└── ticketbox-data/
    ├── uploads/            小票图片
    ├── logs/               运行日志（backend.log，窗口化无控制台时排查看这里；轮转 ~5MB×3）
    ├── backups/            PostgreSQL 备份归档（pg_dump .dump；Owner Console「备份」按钮 / 计划任务写到这里）
    └── .env                可选：用户覆盖配置（DATABASE_URL / PUBLIC_BASE_URL / OCR_* / 端口 等）
```

档 B/服务安装器会通过 Shawl 设置 `TICKETBOX_DATA_DIR=C:\ProgramData\Ticketbox\app`,所以同一套 `launch.py` 会把 `.env`、uploads、logs、backups 都落在 ProgramData,不会写入 Program Files。

`launch.py` 在 import `app.*` 之前把 `UPLOAD_DIR` 指向数据目录、并把 uvicorn + app 日志配到 `logs/backend.log`(windowed `console=False` 无 stdout,改写文件);若存在 `<data>\.env` 则**优先**采用其中的值(`override=True`)。`DATABASE_URL` 不在这里默认——后端是 PostgreSQL-only,要么在 `.env` 里设、要么回落到 `app.config` 的本机 PostgreSQL 默认(EXE 假设本机已装 PostgreSQL 服务)。

可用环境变量(或写进 `ticketbox-data/.env`):

| 变量 | 默认 | 说明 |
|---|---|---|
| `TICKETBOX_HOST` | `127.0.0.1` | bind host |
| `TICKETBOX_PORT` | `8000` | 端口 |
| `DATABASE_URL` | （`app.config` 本机 PostgreSQL 默认） | 数据库（PostgreSQL-only，见下） |
| `UPLOAD_DIR` | `<data>/uploads` | 上传目录 |
| `PUBLIC_BASE_URL` | （空） | 隧道公网地址（如有） |

### 备份与恢复

备份归档（`pg_dump -Fc` 的 `.dump`）写在 `ticketbox-data/backups/`（Owner Console 的「备份」按钮、计划任务都写这里——和 `app.config.DATA_ROOT` 一致）。数据库本身在本机 PostgreSQL 服务里，**不**在这个目录，恢复要用 `pg_restore`:

1. 停掉 `ticketbox-backend.exe`；
2. 用 `pg_restore` 把 `ticketbox-data/backups/` 里某个 `ticketbox-*.dump` 恢复到目标库（完整步骤见 [POSTGRES_MIGRATION.md](../../docs/runbook/POSTGRES_MIGRATION.md) §2）；
3. 重新双击 EXE。

源码/家庭服务器部署的备份脚本（`backend/scripts/backup_database.ps1`、`scripts/maintenance_ticketbox.ps1`）已改为**跟随数据根**:设了 `TICKETBOX_DATA_DIR` 用它、否则用 `backend/`,所以它们与 app 写备份的位置始终一致。诊断类脚本（`diagnose_ticketbox.ps1` 等）仍按源码 `backend/` 布局,是家庭服务器自用工具,不用于冻结 EXE。

## 冻结要点（给维护者）

- 入口 `packaging/launch.py`;spec `packaging/ticketbox-backend.spec`。
- 形态:**onedir + `console=False`**(ADR-0047 §8)。`EXE(exclude_binaries=True)` + `COLLECT(...)` → `dist/ticketbox-backend/`(EXE + `_internal/`)。窗口化进程无 `sys.stdout/stderr`,所以 `launch.py` 在起 uvicorn 前用 `logging.config.dictConfig` 把 uvicorn + app 日志接到 `DATA_ROOT/logs/backend.log`(`RotatingFileHandler`),并给 uvicorn 传 `log_config=None`——否则 uvicorn 默认配置会写 `ext://sys.stdout`,`None.write` 崩。
- `app/config.py`、`app/database` 用 `Path(__file__).parents[N]` 解析路径,冻结后指向 `sys._MEIPASS`(onedir 下即 `_internal/` 目录)。所以 spec 把 `alembic.ini` 和 `migrations/` 打到 **bundle 根**(`backend_root`),`static/` `templates/` 留在 `app/` 下。
- 首次启动:`init_db()` 必须先加载打包的 `alembic.ini` + `migrations/` 并解析唯一 head；空库通过 Alembic `upgrade` 建立 schema，既有库先做 lineage/compatibility 检查并在写入前生成可验证备份，再升级到该 head。Alembic 缺失、lineage 非法或迁移后 revision 不等于 head 都会 fail closed，不再 `create_all` 或“优雅跳过”。
- 动态导入(uvicorn 的 loop/protocol、`app.*` 路由、postgresql 方言 + psycopg 驱动)由 spec 的 `collect_submodules` + `hiddenimports` 兜底;新增依赖若运行时报 `ModuleNotFoundError`,在 spec 的 `hiddenimports` 补一行再重建。
- PyInstaller 冻结 EXE 可能触发杀软误报(无签名)。正式分发建议代码签名。

## 与 GUI 管理器的关系

`desktop/` 的后端管理器已支持两种运行态:源码模式继续监督 `python -m uvicorn`;检测到 `HKLM\Software\Ticketbox` 后切到正式安装模式,通过 Windows SCM 管理 `TicketboxPg` / `TicketboxBackend`,并从 ProgramData 读取配置和日志。把管理器冻结成 EXE 并纳入 Inno 仍是下一打包切片。
