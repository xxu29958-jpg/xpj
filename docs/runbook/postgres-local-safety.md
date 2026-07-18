# 本地 PostgreSQL 安全(测试库/属主/迁移)

home-server 后端跑在本机 PostgreSQL 上（ADR-0041，PG-only，SQLite 已退役）。本篇把几条「真用过会踩」的本地 PG 工具坑收成一份操作手册：怎么踩中、为什么、怎么做对、一句话铁律。

**做这几类活前先读本篇**：在本机跑 pytest / 验迁移、起本地后端做预览或配对、灌库或恢复备份、cut-over、任何对 PG 跑 `CREATE`/`DROP`/`ALTER`/`init_db` 的操作。核心红线只有一条：**三个 PG 实例必须分清——`:5432` 是生产、`:5433` 留给 CI、`:5438` 才是本地一次性测试库**；任何写操作只对 `:5438` 的 throwaway 实例做。

---

## 坑 1：起本地后端 = 对 `DATABASE_URL` 指向的库跑 Alembic 迁移到 head

### 症状（怎么踩中）
为做预览 / 配对 / 调试随手起后端，没先看 `backend\.env` 的 `DATABASE_URL`——它默认指向用户真库 `localhost:5432/ticketbox`（不是 SQLite）。启动时 `init_db` 对这个库跑 alembic 升级到 head，撞到 `ALTER TABLE`（应用角色无 DDL 权限）挂掉，把**用户 dev/prod 库的迁移状态弄坏**。失败迁移**不保证**干净回滚（部分操作可能 autocommit、中途 kill 留半态 / 锁），事后不能脑补「PG 事务性 → 回滚了 → 没事」。

### 根因
后端启动 lifespan 调 `init_db`，它会把 alembic 升到 head。库由 `DATABASE_URL` 决定，默认就是用户真库。

### 正确做法
起任何本地后端前，先把 `DATABASE_URL` 覆盖到一次性 throwaway 库再起：

```powershell
cd E:\projects\xiaopiaojia\backend
.\scripts\start_test_pg.ps1                    # 幂等起 :5438 隔离实例，自建 xpj_test / xpj_smoke
$env:DATABASE_URL = "postgresql+psycopg://postgres@localhost:5438/xpj_smoke"
# ...起后端做预览 / 配对...
.\scripts\stop_test_pg.ps1                      # 用完销毁
```

预览用 `xpj_smoke`，别占跑测试的 `xpj_test`。真把用户的库弄坏了就直说、别淡化；要修（`backend/scripts/reset_dev_db.ps1`）先问用户再动。

### 铁律
**起后端前先确认 `DATABASE_URL` 指哪——默认它是用户真库；预览 / 调试一律先覆盖成 `:5438` 一次性库，绝不对用户配置的 DB 跑迁移。**

---

## 坑 2：CI runner 和生产 PG 同机——按二进制路径杀进程会误伤生产库

### 症状（怎么踩中）
自托管 gitea act_runner 就跑在用户家 PC 上，和生产 PostgreSQL（`:5432`，库 `ticketbox`）**同一台机**。在 CI 或本机脚本里用 `Get-Process postgres | Where Path -like "*PostgreSQL*"` 来杀「测试 postmaster」，会**同时命中生产 postmaster**，一刀杀掉生产库。同理对 `:5432/ticketbox` 跑 `CREATE`/`DROP`/`init_db` 直接动生产数据。

### 根因
三个 PG 共享同一套二进制：生产服务（`:5432`）、CI 临时 `initdb` 实例（`:5433`）、本地 throwaway 实例（`:5438`）。按「二进制路径」筛 postgres 进程无法区分实例。

### 正确做法
- 本地和 CI 只调用同一组 `start_test_pg.ps1` / `stop_test_pg.ps1` 生命周期入口；`:5438` 属于 `local`，`:5433` 只有显式 `ci` 用途可以使用，`:5432` 永久拒绝。
- 新集群先写同父目录 staging receipt，再在唯一 staging 中完成 `initdb`、marker 与 system identifier 验证，最后原子发布；后续只回收 receipt、进程代际和路径边界均可证明的中断残留。
- 数据目录只有同时满足脚本创建的 ownership marker、marker 内 PostgreSQL system identifier 与 `pg_controldata` 一致，才被视为可处置测试集群。已有但无 marker 的目录一律保留并拒绝。
- 数据目录必须由当前 runner 身份持有，ACL 只保留当前身份、SYSTEM、Administrators；启动期间持有目录身份句柄，路径替换、reparse 或宽松写权限均不能越过验证。
- credential、marker 和 lifecycle receipt 创建时即带受保护 ACL；libpq 只读取由 credential 真源派生的短命 passfile，并为每次正常连接强制 `require_auth=scram-sha-256`。旧 `trust` 集群仅在生命周期锁内使用一次显式 `no-challenge bootstrap` 会话完成迁移；`require_auth=none` 只证明服务端未发起认证 challenge，不单独充当 HBA 条目证明。
- 运行态还必须证明 `postmaster.pid` 的目录、端口、PID、进程启动代际和 loopback listener 一致；随后在同一个 `psql` 会话核对 `data_directory`、`pg_control_system().system_identifier`、端口和监听地址，验证完成后才允许建测试库。
- 新 postmaster 在 Job Object 中原子出生，只继承明确的三个标准句柄；创建时返回的进程句柄才是 commit 前身份权威，PID 文件允许短暂为空且不用于杀进程。
- 停机只对上述已验证集群调用 `pg_ctl stop`。离线身份再次吻合后，先持久化包含随机 `instance_id` 的删除 receipt，再以不共享 DELETE 的目录句柄锁住该实例、复核身份并按句柄改名为唯一 tombstone；路径在复核与改名之间无法被替换。后续只删除再次验明身份的 tombstone，receipt 最后删除，进程死在任一阶段都可重入。`pg_controldata`、`initdb`、`pg_ctl` 和递归清理均有显式超时；超时进程由 Job Object 整树终止。禁止 `taskkill`、按二进制路径杀进程或直接删除未知目录。

### 铁律
**进程、目录和数据库操作都必须先证明 marker + system identifier + postmaster 代际 + 在线身份；本地只动 `:5438`，CI 只动 `:5433`，永不触碰 `:5432`。**

---

## 坑 3：stateful lane 必须跨顶层 runner 互斥

### 症状（怎么踩中）
同时启动两个顶层测试 runner（如「后台全量套件」+「前台针对性验证」）时，两条 `stateful_serial` lane 不能同时改 `xpj_test`、角色或迁移状态。单个 runner 内出现多个 pytest worker 是正常行为。

### 根因
普通 lane 由 `run_test_lanes.py` 启动 xdist，每个 worker 使用本次 run uid 派生的独立 `xpj_test_<run>_gwN` 数据库。migration、恢复、集群角色、schema 重建和共享宿主锁测试进入 `stateful_serial` lane，仍共享基础库与集群级资源，因此 runner 会在 PostgreSQL 上持有项目级 advisory lock 后才启动它。

### 正确做法
- 使用统一 runner，让它内部安全并行普通测试、随后串行状态生命周期：

  ```powershell
  cd E:\projects\xiaopiaojia\backend
  .\scripts\start_test_pg.ps1
  .\.venv\Scripts\python.exe scripts\run_test_lanes.py full  # 并行普通测试，再串行状态生命周期
  ```

- 需要可重复的 smoke / 全项目验证时用 `start_test_pg.ps1 -ResetDatabases`；普通本地启动默认保留测试库，避免每次编辑循环都付重建成本。重置只在在线身份验证通过后的同一 `psql` 会话执行。

- 普通编辑循环可执行 `.\.venv\Scripts\python.exe scripts\run_test_lanes.py impacted --base-ref origin/main --include-worktree`。选择器只在能证明依赖闭包时缩小测试集；数据库、模型、迁移、依赖、脚本、删除/重命名和任何证据缺口自动回退 `full`。当前云端仅输出影子计划，完整双 lane 仍是阻断门。

- start、stop、完整 verify 和 Gitea lane 使用同一个 Windows lifecycle mutex；每个真实数据库消费者分别持有自己创建并锁定的进程级 lease，不继承父进程锁。start 在同一 writer 临界区内完成“服务就绪 → 首个 lease”交接，因此不存在已启动但尚未登记消费者的窗口。即使外层 PowerShell 意外死亡，重置和停机仍须等待存活的 runner、pytest worker、smoke 或恢复进程退出，并确认没有其他活动数据库会话。同一计划内部的普通 worker 使用独立数据库并行，stateful lane 再通过 PostgreSQL 锁串行。

### 铁律
**runner 内部 xdist worker 按 run 隔离数据库；stateful lane 必须持有 PG 集群锁并以 `-n 0` 独占执行。**

---

## 坑 4：超级用户灌库导致表 owner 错位——首个 `ALTER` 迁移在启动时被拒，静默停机

### 症状（怎么踩中）
用 `postgres` 超级用户给 `ticketbox` 库灌数据 / 建表（恢复、cut-over、手工 psql）后，对象 owner 是 `postgres`，应用角色 `ticketbox` 只剩 DML 权限。**日常读写一切正常**（所以能跑好几天没人发现），直到 **cut-over 后第一个要 `ALTER` 既有表的 Alembic 迁移**被「必须是表的属主」拒绝 → uvicorn lifespan 失败 → 进程退出 → 后端**静默停机**（本机 `:8000` 拒连、公网 502、自启任务 `LastTaskResult=1`）。实战中这样静默停机过 4 天。

### 根因
cut-over / 恢复那一刀的 owner 没归位，是潜伏到「第一个 ALTER 迁移 + 服务启动」最坏时点才爆的隐藏债。`pg_restore --no-owner` 只把对象「归到连接角色」——**连接角色若是超级用户，照样错位**。

### 正确做法
**真证据在 PostgreSQL 服务端日志（`...\PostgreSQL\17\data\log\`），不在应用 `err.log`**（stderr 缓冲吞了尾巴，应用侧只看到「止于某迁移行」）。一查即现：

```sql
-- 任意角色可跑，错位对象应为 0 行
SELECT tablename, tableowner FROM pg_tables
WHERE schemaname = 'public' AND tableowner <> 'ticketbox';
```

修复用幂等脚本（把 database / schema / 全部表 / 序列 / 视图 owner 归位到 `ticketbox`，自带 0 行自检），**必须超级用户或当前 owner 身份跑**（database owner / 应用账户都不够）：

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" `
    -U postgres -h 127.0.0.1 -d ticketbox -f backend\scripts\fix_table_owners.sql
```

预防（恢复 / 灌库时两者缺一不可）：`pg_restore --no-owner` **且以应用角色 `ticketbox` 连接**——见 `docs/runbook/POSTGRES_MIGRATION.md` §2 / §3。

> postgres 密码丢失时的执行法（trust 窗口）属安全弱化，分类器会拦，须用户授权或用户亲跑：备份 `pg_hba.conf` → 把 `127.0.0.1/32` 两行临时改 `trust` → 重启服务 → 免密跑 SQL → **finally 无条件还原 `pg_hba` 并重启**（绝不能留 `trust`）。临时脚本纯 ASCII、不进 git、跑完即删，并设 `$env:PGCLIENTENCODING=UTF8`。详见 `project_pg_cutover_table_owner_trap` 记忆。

### 铁律
**任何向 `ticketbox` 灌数据 / 建表都以应用角色 `ticketbox` 连接、`pg_restore` 带 `--no-owner`；「迁移失败 / 启动止于迁移行」先查 PG 服务端日志 + `pg_tables` owner，错位用 `fix_table_owners.sql` 归位。**

---

## 坑 5：PG-only 之后唯一存活的方言约束——新增 SQLite 分支 = 回潮

### 症状（怎么踩中）
PG-only 瘦身后 SQLite 方言分支已全删。若再写 `if dialect == "sqlite"` 分支、或依赖被删的 dialect-proofing 习惯，就是违反 PG-only 政策的回潮——这类改动没有对应的 lane 兜底（方言收敛审计 `_audit_dialect_convergence.py` 已随单方言退役）。

### 根因
当年 dialect-proofing（ADR-0041）的大半约束随 SQLite 退役历史化，但**两条语义约束仍然活着**，新代码踩了会出真 bug：

- **session 时区必须钉 UTC**：home-server 跑 `Asia/Shanghai`，PG 把 naive 字面量按 session `TimeZone` 解释；不钉 UTC，`timestamptz` 范围查询（date-filter、`COALESCE(expense_time, confirmed_at)` 统计、软删窗口）整体偏移 8h。`_core.py` 用 libpq `options=-c timezone=utc` 在连接启动设（不被事务回滚），且仅 `startswith("postgresql")` 时传——护住 `check_api_contract` 的 never-connect `sqlite://` 内省引擎。
- **OCC = 整数 `row_version` CAS**：`optimistic_concurrency.claim_row_with_token` 注入 SQL `row_version+1` 表达式，Python 端算不出新值，所以读回方必须 `db.expire_all()`（`expire_on_commit=False`）；不读回的调用方显式传 `synchronize_session=False`。

### 正确做法
- 不新增任何 `sqlite` 方言分支。
- 改连接 / session 配置时保住 UTC 钉法；写 OCC 路径时走 `claim_row_with_token` helper，并按上面规则处理 expire / `synchronize_session`。
- 唯一仍活的方言静态守护是 `scripts/_audit_partial_index_pg_where.py`（分区唯一索引必须带 `postgresql_where`，否则退化成全表 UNIQUE）。

### 铁律
**PG 是唯一方言，别加 SQLite 分支；session 钉 UTC、OCC 走 `row_version` 整数 CAS + `expire_all`，这两条是 dialect-proofing 留下的唯一活约束。**

---

## 当前目录合同

- 本地：`$env:TEMP\xpj_pg_test5438`，`-Purpose local`，默认保留数据库以加速重复开发。
- local-Gitea：`$env:TEMP\xpj_pg_ci_5433`，`-Purpose ci -ResetDatabases`，固定宿主目录用于异常中断后的可验证接管；目录 ACL 在任何 PostgreSQL 代码执行前收紧，每次 run 重建数据库。
- `docs/runbook/POSTGRES_MIGRATION.md` §3 继续负责生产对象属主排查；本脚本只管理 marker-owned 测试集群。
