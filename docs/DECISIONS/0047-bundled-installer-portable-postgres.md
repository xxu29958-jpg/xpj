# 0047 后端分发形态：捆绑安装器 + portable PostgreSQL

* Status: proposed（待 owner 确认；产品方向已由 owner 2026-06-13 口头定调「我是要发给别人用」）
* Date: 2026-06-13
* Decision makers: 项目维护者
* 适用快照: `main` / `6e47c5f2`
* 相关规则 / ADR: ENGINEERING_RULES §5 / §6 / §9 / §14（不依赖 Docker/WSL/PS7），[[0030]]、[[0041]]（PG-only 不可逆）、[[0046]]（窄平台能力裁量先例）

## Context and Problem Statement

owner 要把小票夹后端**分发给亲友独立使用**（对方自己当 owner、自己的数据、自己家的 Windows 机器），不是教对方按 runbook 装。现状安装链 9 步，其中 4 步非工程师必死：装 PostgreSQL 服务、psql 建应用角色与库（owner 错位陷阱曾致生产静默停机 4 天）、手写无 BOM `.env`、配 Cloudflare Tunnel。

仓库已有一半地基：`backend/packaging/` 的 PyInstaller 单文件 EXE（数据落 EXE 旁 `ticketbox-data/`）与 `desktop/backend_manager/` 的 SyncTrayzor 式进程管理器（监督/树 kill/健康重启/LAN 地址/一键开 /owner），二者 README 均已写明合流意图。**唯一未解决的硬骨头是 PostgreSQL**——EXE 当前假设本机已装 PG 服务，而「发给别人」不可能附带这个前提。

问题：分发形态下，PostgreSQL 怎么到对方机器上？

## Decision Drivers

* 对方零命令行、零数据库知识；第一印象=双击安装器。
* 数据正确性第一（§0）：建库/灌库必须以应用角色 `ticketbox` 进行，杜绝 owner 错位陷阱复发。
* [[0041]] PG-only 不可逆——换嵌入式数据库不在选项内。
* §14 铁律：不依赖 Docker / WSL / PowerShell 7。
* 升级路径必须是「下载新安装包覆盖装 / 管理器内检查更新」级别；对方不会 git、不会 pg_upgrade。
* 局域网默认（手机与后端同 Wi-Fi 直连）；Cloudflare 公网是二期可选，quick tunnel 因 URL 漂移与安全门明确排除为产品入口。

## Considered Options

**A. 要求对方自装系统 PostgreSQL 服务** — 即现状。对「发给别人」直接不成立（4 步死墙之首），拒。

**B. 捆绑 portable PostgreSQL（EDB 官方"binaries without installer" zip）** — 安装器内置 PG 17 二进制；首启由桌面管理器 `initdb` 建数据目录、`pg_ctl -D` 起本地实例（免管理员、免系统服务、loopback only）。这是 PostgreSQL 官方下载页明示「供打进第三方安装器」的钦定路径。

**C. 换嵌入式数据库（SQLite 等）** — 违反 [[0041]] 不可逆决定，拒。

## Decision Outcome

**Chosen: B。捆绑 portable PostgreSQL，由桌面管理器统一监督「后端 EXE + PG 实例」双进程。**

边界与要点：

1. **数据目录布局**：`<安装目录>/ticketbox-data/`（沿 EXE 既有约定）下增 `pg/`（cluster）；备份目录、uploads 同根。卸载器默认**保留**数据目录（明示提醒）。
2. **初始化即正确**：首启 `initdb` 后由管理器以超级用户（仅 portable 实例内部）创建应用角色 `ticketbox` 并以该角色建库、跑迁移——owner 错位陷阱在源头堵死；对外（含 /owner、App）只暴露应用角色连接。
3. **实例边界**：portable PG 只绑 127.0.0.1、端口默认 5432 冲突时自动让位（管理器探测）；绝不注册 Windows 服务；生命周期完全由管理器管理（树 kill 无孤儿、健康感知重启的既有不变量扩到双进程）。
4. **PG 大版本钉死 17**：本 ADR 冻结 major=17；minor/patch 随新安装器二进制更新（同 major 直接换二进制，cluster 兼容）。**major 升级（17→N）= 未来另开 ADR**（届时裁 pg_upgrade 由安装器自动跑还是导出/导入），不在本 ADR 偿还范围——显式 defer 最难的问题，避免现在过度设计。
5. **打包工具链**：PyInstaller（已有）+ Inno Setup 套安装向导（开始菜单/卸载器/可选开机自启）。工具选型按惯例不单开 ADR，记录于此即可；依赖结论同步 `docs/rules/DEPENDENCIES.md`。
6. **代码签名**：无签名 EXE 会被 SmartScreen/Defender 拦——这是分发第一印象的真实失败点。是否购证书（Certum 开源 ~€69/年）是 owner 的钱包决策，**本 ADR 不裁**；未签名期安装向导须自带「更多信息→仍要运行」图文预告。
7. **公网边界不变**：分发版默认局域网模式；/owner loopback、上传链允许 LAN;Cloudflare named tunnel 留作二期向导（quick tunnel 永不作为产品入口）。`PUBLIC_BASE_URL` 未配时上传链接向导给 LAN 地址形态。

## Consequences

Good：「发给别人」成立——一个安装包=运行时+数据库+管理器;数据正确性内建;升级=覆盖装（Alembic 迁移本就自动）;不破任何既有铁律。

Bad / Costs：安装包体积 +数十 MB（PG 二进制）;管理器从单进程升双进程监督（supervisor 扩展+测试）;portable cluster 的磁盘/杀软兼容性需真机器验证;PG major 升级被显式推迟（17 生命周期内无虞,EOL 前必须回头）。

Reversibility：卸载=删安装目录（数据目录可保留）;回到「系统 PG」模式只需 DATABASE_URL 指回服务实例,应用层零改动。

## Confirmation

落地完成的判据（缺一不算）：
* 干净 Windows 虚拟机/真机上：双击安装器→管理器首启向导（initdb→建角色建库→迁移→bootstrap owner→显示绑定码与 LAN 地址）→ 手机同 Wi-Fi 绑定成功→记一笔。全程零命令行。
* owner 错位回归测试：portable 实例内全部业务表 owner=ticketbox（fix_table_owners.sql 的检查 SQL 自动化进首启自检）。
* 管理器双进程不变量测试：树 kill 无孤儿（PG 含）、崩溃重启、端口冲突让位、收养已有实例。
* 覆盖安装升级演练：旧版数据目录在,新安装器装完数据无损、迁移自动完成。
* 卸载演练：数据目录保留提示生效。

## Rollout Slices

* Slice 0：本 ADR 确认。
* Slice 1：portable PG 运行时层——下载/校验 EDB zip 进 packaging、`initdb`/`pg_ctl` 封装、应用角色初始化（堵 owner 陷阱）、端口探测。
* Slice 2：管理器双进程监督扩展 + 首启配置向导（含 bootstrap owner GUI 化——吸收 owner-GUI 方案的 D 轴拍板①，在管理器内做而非 /owner HTTP 端点,写入面更窄）。
* Slice 3：Inno Setup 安装器 + 卸载器 + 升级覆盖装演练。
* Slice 4：分发验收（干净机全链 + SmartScreen 文档/签名决策落地）。

## Non-goals

不做：FCM/推送、Docker/WSL、PG major 自动升级（另 ADR）、quick tunnel 产品化、多实例/多用户 SaaS 化、Linux/macOS 安装器（Windows 先行）。
