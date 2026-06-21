plugins {
    alias(libs.plugins.android.application) apply false
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
    // NVD 数据源不可用(空缓存 + NVD 网关 520/524/超时)会让分析引擎抛异常,默认 failOnError=true
    // 时整个构建红——这正是 CI 上「无法更新缓存的网络数据源...分析失败了」那次 13m 红的根因。
    // 设为 false:把「拉不到数据/分析异常」降级为告警而非构建失败;真实漏洞门不受影响——
    // failBuildOnCVSS(上一行)在 NVD 数据可用时照常拦 CVSS>=7.0。代价:NVD 不可达那次扫描查不到东西
    // (无数据)而静默通过,对自用财务 App + 日级缓存可接受(本就把 OWASP 当告警面,非合并硬门)。
    failOnError = false
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
