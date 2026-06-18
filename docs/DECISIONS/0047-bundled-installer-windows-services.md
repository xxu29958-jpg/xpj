# 0047 后端分发形态：捆绑安装器 + Windows 服务化（PG + 后端）+ 主机管理器

* Status: accepted（owner 2026-06-18 拍板；同日联网验证修订；**运行时未实现**——落地分片见 Rollout）
* Date: 2026-06-13 提出（portable PG 版）；2026-06-18 改写为 Windows 服务化 + 联网验证修订
* Decision makers: owner / 项目维护者
* 相关规则 / ADR: ENGINEERING_RULES §5 / §6 / §9 / §14（不依赖 Docker/WSL/PS7），[[0030]]、[[0041]]（PG-only 不可逆），[[0046]]（窄平台裁量先例）

## Context and Problem Statement

owner 要把后端**发给亲友独立自用**（对方自己当 owner、自己数据、自己家的 Windows 机器），不是教对方按 runbook 装。现状安装链对非工程师有 4 步死墙：装 PostgreSQL 服务、psql 建应用角色与库（owner 错位陷阱曾致生产静默停机 4 天）、手写无 BOM `.env`、配 Cloudflare Tunnel。仓库已有 PyInstaller 后端 EXE + 桌面管理器雏形。两个未决：**PostgreSQL 怎么到对方机器并稳定常驻**，以及**网络暴露谁来配**。

## Decision Drivers

* 对方零命令行、零数据库知识；第一印象 = 双击安装器。
* 数据正确性第一（§0）：建库以应用角色 `ticketbox` 进行，堵 owner 错位陷阱复发。
* **常驻要稳**：家用「服务器」要开机自启（无人登录）、崩溃重启、有序关机、依赖排序——这是成熟 OS 能力，不该手写。
* [[0041]] PG-only 不可逆；§14 不依赖 Docker / WSL / PowerShell 7；§9 依赖治理（不引入弃维依赖）。
* 升级 = 覆盖装 / 管理器一键；对方不会 git、不会 pg_upgrade。
* 自托管本意：网络暴露是**用户自己的决定**，产品不替他做网络魔法。

## Considered Options

**A. 要求对方自装系统 PG 服务**（现状）—— 4 步死墙之首，拒。

**B. 捆绑 portable PG + 桌面管理器双进程监督**（原 0047 选项）—— 管理器当 parent 监督「后端 EXE + `pg_ctl` 起的 PG」。**否决**：手写进程守护去重做 Windows SCM 已成熟提供的事（开机自启需另注册、守护被杀子进程孤儿、有序关机/依赖排序自己实现），且 portable PG 的 initdb/起停自管是脆点。

**C. 换嵌入式 DB** —— 违 [[0041]]，拒。

**D. PG + 后端各注册为 Windows 服务，EXE 当主机管理器（SCM 监督）** —— **选定**。

## Decision Outcome

**Chosen: D。安装器注册两个 Windows 服务（PG + 后端），EXE 是控制台式「主机管理器」（不在关键路径），PG 对用户隐形，网络由用户自配。** 以下要点经 2026-06-18 联网验证修订。

1. **双服务，SCM 当守护**：安装器（提权一次）注册 ① PG 服务 ② 后端服务，用 **Shawl** 包 PyInstaller 后端 EXE（Rust 单文件、维护中、专为「子进程只需响应 ctrl-C/SIGINT」设计 = uvicorn 最佳契合；**NSSM 否决——末版 2017 已弃维，违 §9**；WinSW v2 作 .NET 兜底）。后端服务 `depend=` PG 服务。`start= delayed-auto` 避早启动竞争 + 显式 `sc failure` 重启退避策略（如 5s/10s/60s，reset 3600s）。开机自启免登录、崩溃恢复、有序关机交 SCM，**不手写守护**。
2. **PG 隐形 + connect-retry 必需（非 best-effort）**：`depend=` 只保证 PG 服务到 SERVICE_RUNNING，**不保证已接受连接**（经典 SCM 竞争）→ 后端启动必须**有界退避重试直到 PG 接受连接**（杀现 `start_backend`「4 秒连不上判死」bug）。安装后以应用角色 `ticketbox` 建库/迁移——EDB 默认以 postgres 超级用户建 cluster（正是 owner 错位陷阱），故角色初始化是 cluster 建好后**必跑**的一步。用户从不配 DATABASE_URL、不知有 PG。
3. **EXE = 主机管理器，不在关键路径**：GUI 控制台（起停/状态/健康/LAN 地址+二维码/serve APK/引导式网络面板）；关掉它服务照跑；经 SCM 控制服务（需提权）。bootstrap owner、显示绑定码也在此（GUI 化，写入面比 /owner HTTP 端点更窄）。捆 APK：宿主机 serve APK + 二维码。
4. **网络 = 用户自己配（自托管本意）**：**硬不变量——永不在任何 plain-http origin（LAN 或 loopback）设 `Secure`/`__Host-` cookie；cookie 会话只存在于用户配的 HTTPS 后面**。默认**局域网开箱即用**：手机 App↔PC 同 Wi-Fi（bearer/http，LAN 半可信，token 可撤销）；`/web`+`/owner` 在宿主机 loopback **免 cookie**（§14；故本就不需在 loopback http 设 cookie，`__Host-` 需 HTTPS 的事实不咬本设计）。**远程默认推荐 Tailscale**（手机+PC 装 app，零 DNS/防火墙配置，MagicDNS 稳定地址，**顺带解决 DHCP IP 漂移**）；**Cloudflare named tunnel = 「自有域名 + 把 nameserver 迁到 Cloudflare + 要公网浏览器 URL」的进阶路径，非默认**（验证纠正：原 ADR 严重低估其摩擦——非专家多日工程，且 quick tunnel 永不作产品入口）。**LAN 发现**：主机管理器播 mDNS 服务 + Android 用 `NsdManager`（NSD API）**连接时重发现当前 IP**（自愈 DHCP 漂移），而非持久化二维码里的裸 IP；`.local` 浏览器解析仅 Android 12+，兜底 = DHCP 保留 / 重扫配对二维码。
5. **PG 交付 = 捆绑 PG 二进制 + `pg_ctl register`**（轻、可控、避 EDB 专有 EULA 范围；裁掉 docs/pgAdmin/symbols/stackbuilder，把 ~330MB 的 EDB「binaries without installer」zip 削到最小 server+initdb+psql 集；pin 安装路径使 `postgres.exe` 留在 `<prefix>/17/bin`，否则服务无 stdio 时启动失败）。**PG major 钉死 17**，minor/patch 随新安装器换二进制；major 升级（17→N）另开 ADR（pg_upgrade），显式 defer。保留 PostgreSQL License notice（permissive，准予 bundle）。
6. **代码签名 = 默认不签**（验证修订）。理由：签名（OV/EV/**Azure Trusted Signing**）自 2024-03 起**都不消除首下 SmartScreen 警告**——靠下载量攒信誉，本分发规模（几个家人）永远到不了阈值，故为此花钱+折腾不值。经典 SmartScreen「更多信息→仍要运行」一键即过（**安装向导图文 walkthrough 必备**）。唯一边界：**全新 Win11 的 Smart App Control 可能硬拦、无『仍要运行』** → 文档写明「关掉 SAC 或联系维护者」，属小概率子集（仅全新装+SAC 开着）。**可逆回收口**：真有人卡 SAC，再上 Azure Trusted Signing（~$10/mo、无硬件 token、个人开发者可注册）——非现在不可。AV 误报另说：用 onedir + PyInstaller 保持最新 + 必要时按 hash 提交 Defender WDSI（每次重建重交；SmartScreen 与 Defender-AV 是两套系统、两种补救）。
7. **打包链**：PyInstaller（**onedir 非 onefile**——服务常驻、重启快、AV 更友好；安装器本就发文件夹）+ Shawl（服务包装）+ Inno Setup（向导/卸载器/服务注册）。**PyInstaller 硬化清单**（进 Slice 2/3 验收，别在家人机器上才发现）：`workers=1` / `reload=False` / `console=False` 时补 uvicorn 日志（否则 isatty None 崩溃）/ `multiprocessing.freeze_support()` / `collect_submodules('uvicorn')` 等隐藏导入 / **`psycopg[binary]`**（自带 libpq）。工具选型按惯例不单开 ADR，记此 + 同步 `docs/rules/DEPENDENCIES.md`（Shawl 版本 pin、PostgreSQL License）。

## Consequences

Good：「发给别人」成立（双击安装器=运行时+DB+管理器）；常驻稳（SCM 成熟守护 > 手写）；数据正确性内建；网络自配契合自托管本意且化解 cookie/HTTPS 矛盾；Tailscale 给低摩擦远程；对现状是升级（后端 Windows 计划任务→真服务）。

Bad / Costs：**安装包 ~200-350MB**（PG 二进制 ~330MB 可裁，**非「数十 MB」**）；安装需提权注册服务（对固定家用 PC 反而更稳更白）；Shawl 第三方二进制入包（§9 已记，维护中）；**未签名 → 首下 SmartScreen 警告（一键过）+ 全新 Win11 SAC 可能硬拦（关 SAC）+ AV 误报按 hash 管**；**LAN-first 根本约束**——PC 须开机+同 Wi-Fi，远程靠用户配 Tailscale/tunnel；给别人用=维护者成技术支持；PG major 升级显式推迟。

Reversibility：卸载=停删两服务（**数据目录默认保留** + 明示）；回「系统 PG」只需 DATABASE_URL 指回，应用层零改；不签→签只是加 Trusted Signing；服务化叠加在既有 §8 config 化上。

## Confirmation

落地完成判据（缺一不算）：
* 干净 Windows 机：双击安装器 → 注册两服务 → 管理器首启向导（建角色建库 → 迁移 → bootstrap owner → 显示绑定码 + LAN 地址）→ 手机同 Wi-Fi 绑定 → 记一笔。全程零命令行（未签名时含一次「更多信息→仍要运行」）。
* **graceful-shutdown 不变量**：服务停产生干净 uvicorn lifespan shutdown（日志可见），非 TerminateProcess 硬杀；达不成则记为「PG-only 可容忍的已知 fallback」（配 `--timeout-graceful-shutdown` + Shawl ctrl-C / `CREATE_NEW_PROCESS_GROUP` / 进程内 SIGBREAK 处理），不得是静默默认。
* **`depend=` 保证启动序、不保证就绪 → connect-retry 必需**；PG 未就绪时后端不「4 秒死」。
* owner 错位回归：全业务表 owner=`ticketbox`（`fix_table_owners.sql` 检查 SQL 进首启自检）。
* **clean 无 Python 的 Windows 机**跑 frozen 后端 + 连 PG（repo CI runner 有 Python，抓不到缺隐藏导入 / 缺 libpq）。
* LAN 重发现：DHCP 换 IP 后 App 经 `NsdManager` 自愈重连。
* 覆盖升级演练（旧数据无损 + Alembic 自动）；卸载演练（数据目录保留提示 + 两服务干净注销无孤儿）。

## Rollout Slices

* Slice 0：本 ADR（已 accepted）。
* Slice 1：硬编码 / 可迁移审计（EXE 化前清机器假设，task #17 第一步）。
* Slice 2：PG 二进制层（裁 EDB zip / `pg_ctl register` / pin 路径 / 应用角色初始化堵 owner 陷阱）+ 后端 Shawl 服务化（`depend=`PG + connect-retry）+ PyInstaller 硬化（onedir / 隐藏导入 / `psycopg[binary]` / console 日志补丁）。
* Slice 3：主机管理器 EXE（服务起停/状态/LAN mDNS + 二维码/`NsdManager` 重发现/serve APK/bootstrap owner GUI/引导式网络面板：LAN 默认 + Tailscale 引导 + named tunnel 进阶）。
* Slice 4：Inno Setup（注册两服务 / 卸载留数据 / 覆盖升级）+ 干净机全链验收 + graceful-shutdown 验证 + 未签名向导 SmartScreen walkthrough。

## Non-goals

不做：便携双进程守护（否决，交 SCM）；NSSM（弃维）；代码签名（默认不签，可逆）；FCM / 推送；Docker / WSL；PG major 自动升级（另 ADR）；quick tunnel 产品化；多实例 / SaaS；Linux / macOS 安装器（Windows 先行）；产品侧 LAN-TLS（网络由用户自配，远程走 Tailscale/tunnel 的 HTTPS）。
