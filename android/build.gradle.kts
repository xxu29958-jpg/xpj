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

// CI 提速 + 治本 NVD 520/524 flake(#26/#27 都栽在这):把 NVD H2 库放进 Gradle user home 下
// 的固定目录,让 CI 能缓存它(见 .github/workflows/ci.yml 的 "Cache OWASP NVD database" step)。
val dependencyCheckDataDir =
    gradle.gradleUserHomeDir.resolve("dependency-check-data").absolutePath

dependencyCheck {
    failBuildOnCVSS = 7.0f
    // failOnError 保持默认 true(不设 false):corrupt/unreadable 的缓存 H2 库会让 new Engine 抛
    // DatabaseException,12.1.0 的 AbstractAnalyze 仅在 failOnError 为 true 时重抛、否则记日志并跳过
    // 整个分析块——那会让扫描静默 no-op 却 exit 0,绕过 CVE 阈值检查。保持 true → 这类失败仍红,
    // 由 ci.yml 的 OWASP「Enforce」门按 gradle 日志精确区分:仅 NVD 数据断供(No documents exist /
    // NoDataException)放过,真 CVE 发现与其它致命失败(含 corrupt DB)一律红。
    formats = listOf("HTML", "JSON")
    suppressionFile = file("config/dependency-check/suppressions.xml").takeIf { it.exists() }?.absolutePath
    // OWASP recommends an NVD API key to avoid throttling; CI injects it and
    // local runs can use either an environment variable or a Gradle property.
    nvd.apiKey = nvdApiKey.orEmpty()
    // 缓存 + 24h 有效期:命中缓存(<24h)时插件直接跳过 NVD 更新调用,不再每次去 NVD 拉整库
    // (~7min 全量下载正是 520/524 网关超时 flake 的根源)。rerun/同日多跑 = 零 NVD 调用 = 不再被坑;
    // 仅首跑(空缓存)或跨日(>24h)做一次增量更新。CVE 数据日级新鲜对自用财务 App 足够。
    nvd.validForHours = 24
    data.directory = dependencyCheckDataDir
}
