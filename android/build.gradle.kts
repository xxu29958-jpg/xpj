plugins {
    alias(libs.plugins.android.application) apply false
    // issue #64 A1: declared apply-false at the root so the :macrobenchmark and
    // :app modules can apply them; versions come from the catalog.
    alias(libs.plugins.android.test) apply false
    alias(libs.plugins.androidx.baselineprofile) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.owasp.dependency.check)
}

// v1.1 Batch 3: OWASP dependency-check configuration.
// Failure threshold: any CVSS score >= 7.0 fails the build. We keep the
// suppression file under config/dependency-check/ so new findings get
// explicit triage instead of being silently ignored.
val nvdApiKey: String? =
    providers.environmentVariable("NVD_API_KEY")
        .orElse(providers.gradleProperty("nvdApiKey"))
        .orElse(providers.environmentVariable("ORG_GRADLE_PROJECT_nvdApiKey"))
        .orNull

val dependencyCheckAutoUpdate =
    providers.gradleProperty("dependencyCheckAutoUpdate")
        .map { it.toBoolean() }
        .orElse(true)

// Keep the NVD database under Gradle user home so trusted CI events can
// refresh one cache while pull requests consume it read-only.
val dependencyCheckDataDir =
    gradle.gradleUserHomeDir.resolve("dependency-check-data").absolutePath

dependencyCheck {
    failBuildOnCVSS = 7.0f
    // Keep this explicit: corrupt/unreadable cache data must never become a
    // successful report-shaped no-op when an upstream default changes.
    failOnError = true
    // corrupt/unreadable 的缓存 H2 库会让 new Engine 抛
    // DatabaseException,12.1.0 的 AbstractAnalyze 仅在 failOnError 为 true 时重抛、否则记日志并跳过
    // 整个分析块——那会让扫描静默 no-op 却 exit 0,绕过 CVE 阈值检查。保持 true → 缺失/损坏的
    // NVD 数据、真实 CVE 发现与其它致命失败都保持红灯；ci.yml 只允许“更新失败但使用七天内
    // 已验证缓存完成离线分析”降级为告警，不允许无数据或过期数据伪绿。
    formats = listOf("HTML", "JSON")
    // The plugin is applied at the root only. Aggregate is the multi-project
    // task and this explicit scope prevents a green root-only no-op.
    scanProjects = listOf(":app")
    suppressionFile = file("config/dependency-check/suppressions.xml").takeIf { it.exists() }?.absolutePath
    // OWASP recommends an NVD API key to avoid throttling; CI injects it and
    // local runs can use either an environment variable or a Gradle property.
    nvd.apiKey = nvdApiKey.orEmpty()
    // A trusted refresh must actually contact/check NVD before it renews the
    // seven-day marker. Pull-request scans override autoUpdate=false and never
    // receive the NVD credential.
    autoUpdate = dependencyCheckAutoUpdate.get()
    nvd.validForHours = 0
    data.directory = dependencyCheckDataDir
}
