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
- **杀 PG 进程只按 ephemeral 自己的 PID 定向**，PID 从该实例 datadir 的 `postmaster.pid` 第一行读，不按路径筛。`stop_test_pg.ps1` 就是这么做的：

  ```powershell
  $pidfile = Join-Path $DataDir "postmaster.pid"
  $pmpid = (Get-Content $pidfile -TotalCount 1)
  & taskkill /F /T /PID $pmpid          # 只杀这个实例的进程树
  ```

- **建 / 删测试库只在 throwaway 实例上**。本机跑套件 / 验迁移用 `backend\scripts\start_test_pg.ps1`（默认 `:5438`，幂等；`teardown` 走 `stop_test_pg.ps1`）。`:5433` 留给 CI 的 `initdb` 临时实例，本机别手搓。
- 两个脚本都在入口硬拒危险端口，是这条铁律的编译期化身：

  ```powershell
  if ($Port -eq 5432 -or $Port -eq 5433) {
      throw "Refusing port ${Port}: 5432 is prod, 5433 is CI. Use a dedicated test port (default 5438)."
  }
  ```

- `start_test_pg.ps1` 还会校验「端口上的监听者确实是我们的实例」（datadir 下有 `postmaster.pid`），不把别的进程占的端口误当自己的。

### 铁律
**杀 PG 进程只按 ephemeral PID（读 `postmaster.pid`），绝不按二进制路径；建 / 删 / DDL 只对 `:5438` throwaway 实例，永不碰 `:5432` 生产、`:5433` CI。**

---

## 坑 3：本地 `:5438` 测试库一次只能跑一个 pytest 进程

### 症状（怎么踩中）
两个 pytest 进程并发打同一个 `:5438` 测试库（如「后台全量套件」+「前台针对性验证」同时跑），冒出**大片 ERROR**——注意是 setup 阶段的 **ERROR 不是 FAILED**。同一文件单独串行跑立即全绿。实测出现过：针对性测试 55 假 ERROR、全量套件被反向污染数个假 ERROR。看到这个形状先怀疑并发撞库，别当真 bug 调。

### 根因
PG 测试 lane 的隔离单位是「测试」不是「进程」：session-scoped `_isolation_schema` fixture 在会话开头 **建一次 schema + base seed**，之后 `_db_isolation` 把每个测试包进一个回滚事务（`@pytest.mark.real_db` 的测试走整库 reset 例外）。这套设计假设**独占库**。两个进程并发时，一个进程重建 / reset schema，另一个进程在途的查询全炸。

### 正确做法
- 全量套件在跑（尤其后台任务）时，**绝不再起第二个 pytest**。针对性验证要么在全量前跑、要么等全量完。
- 串行跑即可，不需要多库：

  ```powershell
  cd E:\projects\xiaopiaojia\backend
  .\scripts\start_test_pg.ps1
  .\.venv\Scripts\python.exe -m pytest          # 默认就连 :5438/xpj_test
  ```

- 本地 `:5438` 抖动 / 偶发 ERROR 以 CI 的 `Backend (PostgreSQL)` lane 为权威——CI 跑全量、单 runner 串行，不会自撞。

### 铁律
**同一时刻只能有一个 pytest 打 `:5438`；满屏 ERROR（非 FAILED）先当并发撞库，串行重跑别当 bug 调。**

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

## 记忆勘误

逐站点核验后，与真实文件不符 / 需澄清的记忆陈述：

- `project_gitea_runner_pg_isolation` 称本地 throwaway datadir 在 `$env:TEMP\xpj_pg_ci_<run_id>`——那是 **CI** 临时实例（`:5433`）的命名。本地 `start_test_pg.ps1`（`:5438`）的 datadir 实际是 `$env:TEMP\xpj_pg_test<Port>`（如 `xpj_pg_test5438`）。两者是不同实例、不同命名，本文按真实脚本写。
- 同条记忆称「`start_test_pg.ps1` 脚本自身拒 5432/5433」——已核实属实：两个脚本入口均有 `if ($Port -eq 5432 -or $Port -eq 5433) { throw ... }`。
- `feedback_backend_start_runs_migrations_on_user_db` 称起后端 = `init_db` 跑 alembic 到 head——属当时启动行为描述，本文按「documented 启动行为」呈现；操作面以「先覆盖 `DATABASE_URL` 到 `:5438`」这条可执行护栏为准，未逐行复核 lifespan 当前实现。

文件落点确认：`docs/runbook/POSTGRES_MIGRATION.md` 已有 §3「表属主（owner）排查」节，本 runbook 的坑 4 与其互为印证、不冲突，可交叉引用。
