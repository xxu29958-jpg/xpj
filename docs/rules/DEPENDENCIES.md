# 依赖管理

小票夹依赖策略是“稳定、可维护、可复现”，不要为了追新引入 alpha、beta、rc、next、canary 或来源不明的库。

## 基本规则

- 后端 Python 依赖固定在 `backend/requirements.txt` 和 `backend/requirements-dev.txt`。
- Android 依赖版本集中在 `android/gradle/libs.versions.toml`。
- 不在业务模块里散写第三方版本号。
- 默认使用稳定版；预发布版本必须有明确理由，并写入 ADR。
- 新增库前先确认维护状态、许可证、平台兼容性和必要性。
- 新依赖不是绝对禁止；必须能证明收益大于包体、维护、离线部署、安全和验证成本，并优先复用现有平台能力。
- 依赖升级必须跑完整验证，不能只改版本号。

## 审计脚本

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_dependency_versions.ps1
```

默认行为：

- 读取 Android Version Catalog。
- 查询 Android 库、Gradle 插件在 Google Maven 和 Maven Central 的 `maven-metadata.xml`。
- 读取后端 requirements。
- 查询 PyPI JSON API。
- 排除 alpha、beta、rc、snapshot、dev、eap、preview、next、canary 等预发布版本。
- 只报告结果，不自动升级。

如果需要让落后依赖直接失败：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_dependency_versions.ps1 -FailOnOutdated
```

## 升级流程

1. 先运行依赖审计脚本。
2. 查对应库的官方 release notes。
3. 只升级一组相关依赖，例如 AndroidX 一组、Room 一组、后端 FastAPI 一组。
4. 更新锁定版本或 Version Catalog。
5. 跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

6. 如果涉及数据模型、Room、API 行为或安全边界，补文档和 ADR。

## CI 策略

CI 执行依赖审计脚本，但默认不因为“发现新稳定版本”失败。原因是上游发布新版本不应该让主线突然红掉。

真正升级依赖时，必须在本地和 CI 都跑完整验证。

## 捆绑原生二进制（ADR-0047 Option D Windows 分发）

后端「双击安装器」分发（[ADR-0047](../DECISIONS/0047-bundled-installer-windows-services.md) Option D）要把两个**非 PyPI / 非 Maven 的原生二进制**打进 Windows 安装包。它们不进 `requirements.txt` / `libs.versions.toml`，也**不进 git**（落 `backend/packaging/vendor/`，已被 `.gitignore` 忽略、可重建）；版本 pin 与校验和集中在 `backend/packaging/build_pg_bundle.ps1` 顶部 + 本节，换版本时两处同步改。

### PostgreSQL（捆绑数据库）

- 形态：EDB「binaries without installer」zip，由 `build_pg_bundle.ps1` 裁出最小集（保留 `bin`/`lib`/`share` + `server_license.txt`，裁掉 pgAdmin/doc/include/StackBuilder + 非白名单客户端 EXE；~800MB 解包 → **~127MB**，bin 留 9 个 EXE：postgres/initdb/pg_ctl/psql/pg_dump/pg_restore/pg_isready/pg_controldata/pg_resetwal + 全部 DLL）。
- 版本：**17.10-1**（major **钉死 17**，ADR §6；minor/patch 随新 zip 换，major 升级 17→N 另开 ADR 走 pg_upgrade）。
- 来源：`https://get.enterprisedb.com/postgresql/postgresql-17.10-1-windows-x64-binaries.zip`
- zip sha256：`f9aafca58e7026a1ef2caeee711acf761671e57904d430adc85f468374f5a821`（脚本启动即校验，不匹配拒绝使用）。
- 许可证：**PostgreSQL License**（permissive，BSD/MIT 式，准予 bundle）；裁剪后保留 `server_license.txt` 满足「copyright + 许可 + 免责三段须随副本」。EDB 的 binaries-without-installer zip **不附带** EDB 专有 EULA（clickwrap 只约束完整图形安装器 / StackBuilder / pgAdmin，本裁剪已去除这些）。

### Shawl（后端服务包装器，2-D 接线）

- 用途：把 PyInstaller 冻结后端 EXE 包装成 Windows 服务（SCM 守护，ADR §1/§8）。
- 版本：**v1.9.0**（2026-05-03，§9 pin exact）；来源 `https://github.com/mtkennerly/shawl/releases/download/v1.9.0/shawl-v1.9.0-win64.zip`。
- zip sha256：`f883c5d09c9beae2efaeabd8513e7d3f57cd1d0864cec3df4f4a7b6ee904351c`；`shawl.exe` sha256：`0985555b71e7f943b8f3fc639952a9890aa62e66617942a2d0996985fe8e7c6d`。
- 许可证：**MIT**。维护：活跃（~18 个月 4 个 release，无 archived/deprecated）；Rust 单文件自洽 `shawl.exe`，**无 .NET / VC++ 运行时依赖**。选它而非 NSSM（2017 弃维违 §9）/ WinSW 见 ADR §1。
- 2-D 接线要点（2026-06-28 真机实测）：env 经 `shawl add --env KEY=value` 注入；依赖用 `shawl add --dependencies TicketboxPg`（无需另跑 `sc config depend=`）；`--stop-timeout` 调到 **25000ms** 匹配 uvicorn `timeout_graceful_shutdown`。当前 `console=False`（窗口化，2-B 已设）冻结 EXE **收不到** Shawl Ctrl-C，backend.log 不出现 uvicorn lifespan shutdown，停服务在 stop-timeout 后强杀；按 ADR Confirmation 记为「PG-only 可容忍 fallback」（后端 lifespan shutdown 不写业务状态，PG 靠 WAL/断连回滚保完整性）。服务账户切换用 `sc config <svc> obj= "NT SERVICE\<svc>"`，**不要**传 `password= ""`：Windows PowerShell 5.1 会吞尾随空字符串，使 `sc.exe` 返回 1639 并保持 LocalSystem；脚本必须检查 `sc.exe` 返回码。

### Inno Setup（安装包构建工具，Slice 4）

- 用途：把 frozen backend、裁剪 PG、Shawl 和服务注册脚本打成单个 Windows 安装器（`backend/packaging/ticketbox-installer.iss`，由 `build_inno_installer.ps1` 调 `ISCC.exe` 编译）。这是**构建期工具**，不进最终安装目录，也不进 git。
- 稳定线：**Inno Setup 6.x**。官方当前稳定版 **6.7.3**（2026-05-26）；7.x 当前仍有 beta 线，按 §9 不引入预发布。
- 来源/安装：官方下载页 `https://jrsoftware.org/isdl.php`；也可按官方命令 `winget install --id JRSoftware.InnoSetup -e -s winget -i` 交互安装。构建脚本优先找 PATH，再找用户级 `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`，再找 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` / `C:\Program Files\Inno Setup 6\ISCC.exe`。
- 许可证：**Inno Setup License**（官方称 open-source；商业使用官方建议购买商业 license，项目分发前按实际用途处理）。构建脚本只依赖 `ISCC.exe`，不改运行时依赖树。
- 验证要求：无 Inno 的机器跑 `packaging\build_inno_installer.ps1 -CheckInputsOnly`；有 Inno 的构建机还要实际生成 `dist\installer\Ticketbox-Setup-<version>.exe`，并在干净 Windows 机验证安装/启动/卸载保留数据/升级前备份。
