# 项目结构

项目根目录：

```text
E:\projects\xiaopiaojia\
  backend\           # FastAPI 服务端（含 /web 浏览器端与 /owner 管理台）
  android\           # Android App（Compose）
  desktop\           # 桌面后端管理器（进程监督 + 状态可视，见 desktop/README.md）
  docs\
  infra\             # 基础设施配置（Cloudflare Tunnel ingress 等）
  scripts\           # 项目级运维 / 构建 / 检查脚本（全部 .ps1；用法见 docs/runbook/ 各文）
    check_text_encoding.ps1      # 编码红线（CI / verify 都跑）
    maintenance_ticketbox.ps1    # 备份等计划任务入口
    start_backend.ps1 …          # 启停 / 诊断 / 安装任务 / 验收等同级脚本
    verify_project.ps1           # 本地全套验证入口
  .github\
    workflows\
      cloud-ci.yml               # GitHub 云端主 CI
      android-connected-cloud.yml # GitHub 云端模拟器 lane
  .gitea\
    workflows\
      windows-ci.yml             # 本地降级四 job CI
      android-connected.yml      # 本地降级 path-filtered 模拟器 lane
  .editorconfig
  .gitattributes
  .gitignore
  AGENTS.md          # agent 工作规则入口（CLAUDE.md 经 import 读同一套）
  CLAUDE.md
  LICENSE            # 木兰宽松许可证 v2
  README.md
```

## backend

```text
backend\
  app\
    main.py
    config.py
    database.py
    models.py
    schemas.py
    auth.py
    errors.py
    routes\
      auth.py
      bootstrap.py
      admin.py
      budgets.py
      dashboard.py
      owner_console.py
      duplicates.py
      expenses.py
      goals.py
      imports.py
      maintenance.py
      reports.py
      rules.py
      settings.py
      stats.py
      uploads.py
      web_app.py
      web_reports.py
      web_goals.py
    services\
      admin_service.py
      owner_console_service.py
      category_service.py
      classify_service.py
      cleanup_service.py
      csv_import_batch_service.py
      budget_service.py
      dashboard_service.py
      duplicate_service.py
      expense_service.py
      expense_split_service.py
      file_service.py
      goal_service.py
      ocr_service.py
      receipt_item_service.py
      receipt_parse_service.py
      receipt_parse_amount.py
      receipt_parse_merchant.py
      receipt_parse_time.py
      receipt_parse_category.py
      server_settings_service.py
      reports_service.py
      stats_service.py
      thumb_service.py
      time_service.py
    middleware\
      logging.py
    templates\
      owner\
        base.html
        index.html
        devices.html
        pairing.html
        upload_links.html
        diagnostics.html
      web\
        dashboard.html
        import_export.html
        import_batch.html
        reports.html
        goals.html
    static\
      owner\
        owner.css
      shared\
        tokens.css
      web\
        web.css
        reports.js
        vendor\
          echarts.min.js
    log_sanitize.py
    version.py
  data\
    .gitkeep
  uploads\
    .gitkeep
  logs\
    .gitkeep
  backups\
    .gitkeep
  tests\
    conftest.py
    api_contract_helpers.py
    test_auth_bootstrap.py
    test_uploads.py
    test_expenses.py
    test_expense_items.py
    test_expense_splits.py
    test_csv_import_batches.py
    test_tenant_isolation.py
    test_stats_filters.py
    test_maintenance.py
    test_reports.py
    test_goals.py
    test_dashboard_cards.py
    test_v09_reports_goals_integration.py
    test_web_reports_goals.py
  scripts\
    backup_database.ps1
    export_confirmed.ps1
    install_startup_task.ps1
    setup_backend.ps1
    start_backend.ps1
    uninstall_startup_task.ps1
    smoke_test.py
  .env.example
  requirements.txt
  requirements-dev.txt
  run.bat
  setup.bat
  README.md
```

## android

```text
android\
  settings.gradle.kts
  build.gradle.kts
  gradlew
  gradlew.bat
  install_debug_apk.bat
  gradle\wrapper\
  scripts\
    install_debug_apk.ps1
  README.md
  app\
    build.gradle.kts
    build\outputs\apk\gray\debug\app-gray-debug.apk
    build\outputs\apk\internal\debug\app-internal-debug.apk
    build\outputs\apk\gray\release\app-gray-release.apk
    src\main\
      AndroidManifest.xml
      java\com\ticketbox\
        MainActivity.kt
        TicketboxApplication.kt
        AppContainer.kt
        data\
        domain\
          model\BackgroundSettings.kt
          model\DefaultCategories.kt
        security\
        ui\
          background\BackgroundImageStore.kt
          background\ImmersiveBackground.kt
        viewmodel\
      res\
    src\test\
      java\com\ticketbox\
        domain\model\BackgroundSettingsTest.kt
        domain\model\DefaultCategoriesTest.kt
        ui\background\ImmersiveBackgroundTest.kt
```

## desktop

Windows 桌面后端管理器（仿 SyncTrayzor 模式：只做进程壳，不重造后端管理功能）。
CI 的 desktop-manager job 对它跑 compileall / ruff / pytest。详见 [desktop/README.md](../../desktop/README.md)。

```text
desktop\
  backend_manager\
    supervisor.py        # 后端进程监督（独占、崩溃重启、树 kill）
    control_server.py
    ui.html
  tests\
  pyproject.toml
```

## docs

文档按读者意图分到子目录。完整导览见 [docs/README.md](../README.md)。

```text
docs\
  README.md                  # 文档导览（入口）
  rules\                     # 开发规范（必读）
    ENGINEERING_RULES.md
    CODE_QUALITY_STANDARDS.md
    DEPENDENCIES.md
    REFERENCES.md
    ERROR_MESSAGE_MAPPING.md
  architecture\              # 系统契约与架构
    ARCHITECTURE.md
    PROJECT_STRUCTURE.md
    ACCOUNT_SYSTEM.md
    API.md
    openapi_contract.json    # OpenAPI snapshot（check_api_contract.py 对账）
    SECURITY.md
    VERSION.md
    DATA_RETENTION.md
    OCC_ROW_VERSION.md
    ANDROID_STATE_FLOW.md
    ANDROID_UPLOAD.md
    ANDROID_APPEARANCE_BACKGROUND.md
  runbook\                   # 部署与运维
    BOOTSTRAP.md
    CI.md
    CLOUDFLARE_TUNNEL.md
    WINDOWS_SERVICE_RUNBOOK.md
    WINDOWS_BACKUP_TASK.md
    REAL_DEVICE_RUNBOOK.md
    RELEASE_PACKAGING.md
    GRAY_ACCEPTANCE_EXECUTION.md
    ROLLBACK.md
    POSTGRES_MIGRATION.md
    IOS_SHORTCUT.md
  roadmap\                   # 产品规划与设计
    POST_BETA_DEVELOPMENT_ROADMAP.md
    MONARCH_CAPABILITY_ROADMAP.md
    MONARCH_INSPIRED_UI.md
    TRI_SURFACE_INFORMATION_ARCHITECTURE.md
    V2_ROADMAP.md
  current\                   # 当前版本资产
    CHANGELOG.md
    AUDIT_BASELINE_v1.2.0.md
    V0_9_DESIGN_FUNCTION_TABLE.md
    V0_9_DESIGN_TOKEN_REFERENCE.md
  DECISIONS\                 # ADR（编号 0001-0049，0018 撤回）
  design_reference\          # 设计稿真值（图片与说明）
```

## 当前初始化范围

后端已经包含稳定闭环和灰度版增量 API：账本隔离、受保护缩略图、Android 上传、OCR retry 入口、重复检测、分类规则、固定支出、标签、商家别名、服务端预算、v0.9 Reports、Goals、Dashboard 卡片配置、生活化统计和窄维护清理接口，并有 pytest API 契约测试、v0.9 集成测试与 smoke 测试。Android 已拆成 `gray` 和 `internal` 两个 flavor，包含 Compose 工程、ViewModel、Repository、Retrofit、Room、Keystore、BiometricPrompt、Photo Picker 上传、自定义背景与沉浸模式、受保护图片预览、重复保留、OCR retry、生活化统计、报表图表、Goals 摘要、Dashboard 卡片管理、分类规则管理和本地单元测试。内部联调能力只进入 `internal` 版。

v0.9 之后的主线增量（至 2026-06，决策记录在 [docs/DECISIONS/](../DECISIONS/)）：数据库切换为 PostgreSQL-only（ADR-0041，SQLite 退役）；新增 `/web` 浏览器端（Cloudflare Access + session cookie，ADR-0028）与桌面后端管理器（`desktop/`）；多币种汇率与家庭拆账（ADR-0029）、收入计划、请求幂等键（ADR-0042）、标签管理（ADR-0043）、Android string-resourcing（ADR-0044）、per-install CSRF 签名密钥（ADR-0045）、Android 固定支出提醒边界（ADR-0046）、捆绑安装器方向（ADR-0047）、Rive 吉祥物运行时（ADR-0048）、Debt 欠款/负债领域契约（ADR-0049）；CI 现以 GitHub Actions 云端为主、自托管 Gitea 为本地降级（含备份恢复演练与 instrumented 模拟器 lane，见 [docs/runbook/CI.md](../runbook/CI.md)）。
