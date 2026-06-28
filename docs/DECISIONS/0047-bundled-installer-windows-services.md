# 0047 后端分发形态：捆绑安装器 + Windows 服务化（PG + 后端）+ 主机管理器

* Status: accepted（owner 2026-06-18 拍板 + 同日联网验证修订 + 同日补强服务身份/数据目录/ACL/升级前置；**运行时未实现**——落地分片见 Rollout）
* Date: 2026-06-13 提出（portable PG 版）；2026-06-18 改写为 Windows 服务化 + 联网验证 + 补强
* Decision makers: owner / 项目维护者
* 相关规则 / ADR: ENGINEERING_RULES §5 / §6 / §9 / §14；[[0028]]（/owner loopback）、[[0030]]、[[0041]]（PG-only 不可逆）、[[0045]]（per-install 密钥）、[[0046]]（窄平台裁量先例）

## Context and Problem Statement

owner 要把后端**发给亲友独立自用**（对方自己当 owner、自己数据、自己家的 Windows 机器），不是教对方按 runbook 装。现状安装链对非工程师有 4 步死墙：装 PostgreSQL 服务、psql 建应用角色与库（owner 错位陷阱曾致生产静默停机 4 天）、手写无 BOM `.env`、配 Cloudflare Tunnel。仓库已有 PyInstaller 后端 EXE（`backend/packaging/launch.py`）+ 桌面管理器雏形。两个未决：**PostgreSQL 怎么到对方机器并稳定常驻**，以及**网络暴露谁来配**。

## Decision Drivers

* 对方零命令行、零数据库知识；第一印象 = 双击安装器。
* 数据正确性第一（§0）：建库以应用角色 `ticketbox` 进行，堵 owner 错位陷阱复发。
* **常驻要稳**：家用「服务器」要开机自启（无人登录）、崩溃重启、有序关机、依赖排序——这是成熟 OS 能力，不该手写。
* **数据/密钥安全**：机器级服务数据（DB + per-install 密钥）不能让登录用户随手读到。
* [[0041]] PG-only 不可逆；§14 不依赖 Docker / WSL / PowerShell 7；§9 依赖治理（不引入弃维依赖）。
* 升级 = 覆盖装 / 管理器一键，且**升级前必有可回退快照**；对方不会 git、不会 pg_upgrade。
* 自托管本意：网络暴露是**用户自己的决定**，产品不替他做网络魔法。

## Considered Options

**A. 要求对方自装系统 PG 服务**（现状）—— 4 步死墙之首，拒。

**B. 捆绑 portable PG + 桌面管理器双进程监督**（原 0047 选项）—— 管理器当 parent 监督「后端 EXE + `pg_ctl` 起的 PG」。**否决**：手写进程守护去重做 Windows SCM 已成熟提供的事（开机自启需另注册、守护被杀子进程孤儿、有序关机/依赖排序自己实现），且 portable PG 的 initdb/起停自管是脆点。

**C. 换嵌入式 DB** —— 违 [[0041]]，拒。

**D. PG + 后端各注册为 Windows 服务，EXE 当主机管理器（SCM 监督）** —— **选定**。

## Decision Outcome

**Chosen: D。** 架构角色坚定为四层，职责互不串：

* **Windows SCM = 真正的守护者**：开机自启免登录 / 崩溃重启 / 有序关机 / 依赖排序——不手写进程守护。
* **PG 服务 = 数据底座**：对用户隐形。
* **后端服务 = API / runtime**：`depend=` PG。
* **主机管理器 EXE = 控制台 / 状态 / 配网 / 二维码 / 装后向导，不在关键路径**：关掉它服务照跑。

以下要点经 2026-06-18 联网验证 + 补强。

1. **双服务，SCM 当守护 + 有界停机**：安装器（提权一次）注册 PG 服务 + 后端服务，后端用 **Shawl** 包 PyInstaller EXE（Rust 单文件、维护中，专为「子进程响应 ctrl-C/SIGINT」设计；**NSSM 否决——末版 2017 弃维违 §9**；WinSW v2 作 .NET 兜底）。依赖排序：**`sc config <后端服务> depend= <PG服务>`**（Shawl 自身不设依赖，须 sc.exe 配）+ `start= delayed-auto` 避早启动竞争 + `sc failure` 重启退避（如 5s/10s/60s，reset 3600s）。Shawl `--stop-timeout` 默认仅 **3000ms（太短）→ 调大（如 25000ms）**并让 uvicorn 设 `timeout_graceful_shutdown` 匹配。**Slice 2-D 真机实测（2026-06-28）**：当前 onedir `console=False` 窗口化 EXE 收不到 Shawl Ctrl-C，服务停机在 stop-timeout 后强杀，backend.log 不出现 uvicorn lifespan shutdown；这是本 ADR 接受的「PG-only 可容忍 fallback」（后端 lifespan shutdown 不写业务状态，PG 独立进程靠 WAL/断连回滚保完整性），但不得静默默认，必须在验收日志中显式记录。

2. **服务身份 + 数据目录 + ACL（写死策略，不写死用户不能选路径）**：
   * **服务身份**：PG 与后端各用**独立 Windows 虚拟服务账户**（`NT SERVICE\TicketboxPg` / `NT SERVICE\TicketboxBackend`，自动管理无密码、互相隔离、最小权限）。PG 9.2+ 官方安装默认 `NetworkService`，但它跨进程共享、安全性差，故改用专属虚拟账户；**PG 服务不得以管理员 / LocalSystem 运行**。
   * **数据目录默认 `C:\ProgramData\Ticketbox\`**（机器级服务数据：**不放 Program Files**〔只读、写需提权〕，**不绑登录用户目录**〔桌面 / 下载 / profile〕）。其下 `pgdata\`（PG 簇，`initdb -D`）+ `app\`（= `TICKETBOX_DATA_DIR`：`.env` / uploads / backups，单写根已存在于 `config.py`）。**这改写现 `packaging/launch.py` 把 data 放「EXE 旁边」的默认**——服务模式下 EXE 在 Program Files 写不了。
   * **用户可选但不强问**：安装器给「**高级：更改数据位置**」（D 盘 / 其它本地盘等）；普通用户不问、直接 ProgramData。**选定即写入服务配置**（PG `-D` + 后端 `TICKETBOX_DATA_DIR` / `UPLOAD_DIR`）。
   * **ACL**：建目录即断继承（`icacls <dir> /inheritance:r`）+ 只授 SYSTEM、Administrators、对应服务账户全控（`/grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\TicketboxPg:(OI)(CI)F"`），**移除 ProgramData 默认的 Users 读权**（数据含 DB + per-install 密钥）。
   * **升级不偷换目录**（覆盖装读现服务配置里的现路径）；**覆盖升级前置**：管理器先 `backup_service.create_manual_backup()` 打一个 `pre_upgrade` 标记快照（`pg_dump -Fc`，已存在），**快照失败即中止、不进 Alembic**（别等迁移炸了再救）。
   * **卸载默认保留数据目录**，仅当用户显式勾选「删除全部本地数据」才删（明示二次确认）。
   * **迁移走管理器**：停服务（后端先于 PG）→ 迁移数据（robocopy /COPYALL 保 ACL）→ 改服务配置 + 重设新位置 ACL → 起服务；**绝不让用户手动拖文件夹**（PG 数据目录权限错 → PG 拒启）。

3. **PG 隐形 + connect-retry 必需（非 best-effort）+ 应用角色建库**：`depend=` 只保证 PG 服务到 RUNNING，**不保证已接受连接**（经典 SCM 竞争）→ 后端启动必须**有界退避重试直到 PG 接受连接**（杀现 `start_backend` 历史「4 秒判死」类 bug；启动期会跑 Alembic [[feedback_backend_start_runs_migrations_on_user_db]]，故重试要包住启动期 DB 访问）。安装后以应用角色 `ticketbox` 建库 / 迁移——cluster 默认以 postgres 超级用户建（正是 owner 错位陷阱 [[project_pg_cutover_table_owner_trap]]），故角色初始化是 cluster 建好后**必跑**步（`fix_table_owners.sql` 自检进首启）。用户从不配 DATABASE_URL、不知有 PG。

4. **EXE = 主机管理器，不在关键路径（bootstrap / 配设备全走 loopback API，二维码只塞短期码）**：GUI 控制台（起停 / 状态 / 健康 / LAN 地址 + 二维码 / serve APK / 引导式网络面板）；关掉它服务照跑；经 SCM 控制服务（需提权）。
   * **bootstrap owner = 调 loopback `POST /api/bootstrap/owner`（已存在：`enable_http_bootstrap` + 一次性 `http_bootstrap_secret`，用后消费），非直接写 DB**；一次性 secret 即「一次性凭证用后失效」机制。
   * **配新设备 = 调 loopback `POST /api/bootstrap/pairing-codes`（已存在，admin + loopback 边界），二维码只塞短时单次 `PairingCode`**（模型已有 `expires_at` NOT NULL + `used_at` 单次、只存 hash）——**绝不塞长期 token**。设备拿 pairing code 换 `AuthToken`（绑 `Device`、有 `revoked_at` / `expires_at`，可单设备撤销）。
   * **`/owner` 永远 loopback-only**（已由 `require_owner_console_local` TCP peer + Host 头双检强制，[[0028]] / §14；无公网模式，不随分发形态放宽）。

5. **网络 = 用户自己配（自托管本意）**：**硬不变量——永不在任何 plain-http origin（LAN 或 loopback）设 `Secure` / `__Host-` cookie；cookie 会话只存在于用户配的 HTTPS 后面**。默认**局域网开箱即用**：手机 App↔PC 同 Wi-Fi（bearer/http，LAN 半可信，token 可撤销）；`/web` + `/owner` 在宿主机 loopback **免 cookie**（§14；故 loopback http 本就不需设 cookie，`__Host-` 需 HTTPS 的事实不咬本设计）。**远程默认推荐 Tailscale**（手机 + PC 装 app，零 DNS / 防火墙配置，MagicDNS 稳定地址，顺带解决 DHCP IP 漂移）；**Cloudflare named tunnel = 「自有域名 + nameserver 迁到 Cloudflare + 要公网浏览器 URL」的进阶路径，非默认**（验证纠正：原案严重低估其摩擦；quick tunnel 永不作产品入口）。**LAN 发现**：主机管理器播 mDNS 服务 + Android 用 `NsdManager` **连接时重发现当前 IP**（自愈 DHCP 漂移），而非持久化二维码里的裸 IP；`.local` 浏览器解析仅 Android 12+，兜底 = DHCP 保留 / 重扫配对二维码。

6. **PG 交付 = 捆绑 PG 二进制 + `pg_ctl register`**（轻、可控、避 EDB 专有 EULA 范围；裁掉 docs/pgAdmin/symbols/stackbuilder，把 ~330MB 的「binaries without installer」zip 削到最小 server + initdb + psql 集；pin 安装路径使 `postgres.exe` 留在 `<prefix>/17/bin`，否则服务无 stdio 时启动失败）。**PG major 钉死 17**，minor/patch 随新安装器换二进制；major 升级（17→N）另开 ADR（pg_upgrade），显式 defer。保留 PostgreSQL License notice（permissive，准予 bundle）。

7. **代码签名 = 默认不签**（验证修订）。签名（OV/EV / **Azure Trusted Signing**）自 2024-03 起**都不消除首下 SmartScreen 警告**——靠下载量攒信誉，本分发规模（几个家人）永远到不了阈值，为此花钱 + 折腾不值。经典 SmartScreen「更多信息 → 仍要运行」一键即过（**安装向导图文 walkthrough 必备**）。唯一边界：**全新 Win11 的 Smart App Control 可能硬拦、无『仍要运行』** → 文档写明「关掉 SAC 或联系维护者」，属小概率子集。**可逆回收口**：真有人卡 SAC，再上 Azure Trusted Signing（~$10/mo、无硬件 token、个人开发者可注册）。AV 误报另说：onedir + PyInstaller 保持最新 + 必要时按 hash 提交 Defender WDSI。

8. **打包链 + PyInstaller 硬化 + Slice 2 临时服务脚本**：PyInstaller（**onedir 非 onefile**——服务常驻、重启快、AV 更友好）+ Shawl（服务包装）+ Inno Setup（向导 / 卸载器 / 服务注册）。**PyInstaller 硬化清单**（进 Slice 2/3 验收）：`workers=1` / `reload=False` / `console=False` 时补 uvicorn 日志（否则 isatty None 崩溃）/ `multiprocessing.freeze_support()` / `collect_submodules('uvicorn')` 等隐藏导入 / **`psycopg[binary]`**（自带 libpq）。**Slice 2 交付一个临时 PowerShell 服务安装脚本（不发给用户、仅 dev 验证）**：`shawl add --name TicketboxBackend --stop-timeout 25000 -- <launch.exe>` + `sc config TicketboxBackend depend= TicketboxPg` + `sc failure ...` 退避 + `sc config ... start= delayed-auto`，使 Shawl / `depend=` / connect-retry / 优雅关停在 Inno（Slice 4）之前就能验证。工具选型按惯例不单开 ADR，记此 + 同步 `docs/rules/DEPENDENCIES.md`（Shawl 版本 pin、PostgreSQL License）。

## Consequences

Good：「发给别人」成立（双击安装器 = 运行时 + DB + 管理器）；常驻稳（SCM 成熟守护 > 手写）；数据正确性内建；**虚拟服务账户 + ACL 加固 = DB / per-install 密钥不被登录用户读到**；**升级前 `pre_upgrade` 快照 = Alembic 出事可回退**；网络自配契合自托管本意且化解 cookie/HTTPS 矛盾；Tailscale 给低摩擦远程；对现状是升级（后端 Windows 计划任务 → 真服务）。

Bad / Costs：**安装包 ~200-350MB**（PG 二进制 ~330MB 可裁，**非「数十 MB」**）；安装需提权注册服务（对固定家用 PC 反而更稳更白）；Shawl 第三方二进制入包（§9 已记，维护中）；**未签 → 首下 SmartScreen 警告（一键过）+ 全新 Win11 SAC 可能硬拦（关 SAC）+ AV 误报按 hash 管**；**LAN-first 根本约束**——PC 须开机 + 同 Wi-Fi，远程靠用户配 Tailscale/tunnel；给别人用 = 维护者成技术支持；PG major 升级显式推迟。

Reversibility：卸载 = 停删两服务（**数据目录默认保留** + 明示）；数据目录迁移走管理器（停 → 移 → 修 ACL → 起），不锁死在初装位置；回「系统 PG」只需 DATABASE_URL 指回，应用层零改；不签 → 签只是加 Trusted Signing；服务化叠加在既有 §8 config 化上。

## Confirmation

落地完成判据（缺一不算）：
* 干净 Windows 机：双击安装器 → 注册两服务（独立虚拟账户）→ 数据落 `C:\ProgramData\Ticketbox`（**非 EXE 旁**）→ 管理器首启向导（建应用角色 + 建库 → 迁移 → 经 loopback `POST /api/bootstrap/owner` 建 owner → 经 loopback `POST /api/bootstrap/pairing-codes` 显示**短期 pairing code** 二维码 + LAN 地址）→ 手机同 Wi-Fi 扫码绑定 → 记一笔。全程零命令行（未签名时含一次「更多信息 → 仍要运行」）。
* **二维码只含短期单次 pairing code、不含任何 token**；bootstrap / 配设备全走 loopback API（无直接 DB 写）；`/owner` 公网请求仍 403。
* **ACL 验证**：数据目录断继承、Users 无读权、仅 SYSTEM / Administrators / 服务账户可访问。
* **覆盖升级前置**：先打 `pre_upgrade` 快照成功**才**进 Alembic；旧数据无损 + Alembic 自动到 head。
* **`depend=` 保证启动序、不保证就绪 → connect-retry 必需**；PG 未就绪时后端不「4 秒死」。
* **停机行为已验证**：当前 console=False Shawl 服务 build 不能收到 Ctrl-C/SIGINT，停服务等待 `--stop-timeout=25000` 后强杀；验收日志必须记录该 WARN。判定为「PG-only 可容忍的已知 fallback」：只可能丢失在途可重试请求和日志尾部，后端 lifespan shutdown 不写业务状态，PG 独立进程靠 WAL/断连回滚保数据完整性。若未来改为 console=True service build 或独立停机路径，需重新验证并更新本条。
* owner 错位回归：全业务表 owner = `ticketbox`（`fix_table_owners.sql` 检查进首启自检）。
* **clean 无 Python 的 Windows 机**跑 frozen 后端 + 连 PG（repo CI runner 有 Python，抓不到缺隐藏导入 / 缺 libpq）。
* LAN 重发现：DHCP 换 IP 后 App 经 `NsdManager` 自愈重连。
* 数据目录迁移演练（停 → 移 → 修 ACL → 起，PG 起得来、数据无损）；卸载演练（数据目录保留提示 + 两服务干净注销无孤儿）。

## Rollout Slices

* Slice 0：本 ADR（已 accepted）。
* Slice 1：硬编码 / 可迁移审计（EXE 化前清机器假设，task #17 第一步）。
* Slice 2：PG 二进制层（裁 EDB zip / `pg_ctl register` / pin 路径 / 虚拟服务账户 + ACL / 应用角色初始化堵 owner 陷阱）+ 后端 Shawl 服务化（`depend=` PG + connect-retry + graceful shutdown）+ PyInstaller 硬化（onedir / 隐藏导入 / `psycopg[binary]` / console 日志补丁 / data 落 ProgramData）+ **临时 PowerShell 服务安装脚本（shawl add + sc config depend= + sc failure，dev 验证用，不发用户）**。
* Slice 3：主机管理器 EXE（服务起停 / 状态 / LAN mDNS + 二维码〔短期 pairing code〕/ `NsdManager` 重发现 / serve APK / bootstrap owner 走 loopback API / 引导式网络面板：LAN 默认 + Tailscale 引导 + named tunnel 进阶 / 高级改数据位置 + 迁移流程）。
* Slice 4：Inno Setup（注册两服务 + 虚拟账户 + ACL / 默认 ProgramData + 高级改位置 / 覆盖升级先 `pre_upgrade` 快照 / 卸载留数据）+ 干净机全链验收 + graceful-shutdown 验证 + 未签名向导 SmartScreen walkthrough。

Slice 4 落地状态（2026-06-28）：仓库已有 Inno `.iss`、`build_inno_installer.ps1`、正式 `install_bundled_services.ps1` / `uninstall_bundled_services.ps1`。本片覆盖打包输入校验、ProgramData 数据根、服务注册、虚拟服务账户、ACL、首次 owner bootstrap、升级前 `pg_dump -Fc` 快照、卸载默认留数据。仍待在装有 Inno 的干净 Windows 机上执行完整安装/升级/卸载与 SmartScreen walkthrough。

## Non-goals

不做：便携双进程守护（否决，交 SCM）；NSSM（弃维）；代码签名（默认不签，可逆）；FCM / 推送；Docker / WSL；PG major 自动升级（另 ADR）；quick tunnel 产品化；多实例 / SaaS；Linux / macOS 安装器（Windows 先行）；产品侧 LAN-TLS（网络由用户自配，远程走 Tailscale/tunnel 的 HTTPS）。
