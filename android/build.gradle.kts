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

// Default to the cacheable Gradle user-home database. CI may override the
// directory to refresh an isolated candidate without mutating last-known-good data.
val dependencyCheckDataDir =
    providers.gradleProperty("dependencyCheckDataDir")
        .map { rootProject.file(it).absolutePath }
        .getOrElse(gradle.gradleUserHomeDir.resolve("dependency-check-data").absolutePath)
val dependencyCheckNvdValidForHours =
    providers.gradleProperty("dependencyCheckNvdValidForHours")
        .map(String::toInt)
        .getOrElse(24)

dependencyCheck {
    failBuildOnCVSS = 7.0f
    // Keep failOnError=true: unreadable data, scanner failures, and findings at
    // or above the threshold must all fail the audit rather than become a no-op.
    formats = listOf("HTML", "JSON")
    suppressionFile = file("config/dependency-check/suppressions.xml").takeIf { it.exists() }?.absolutePath
    // OWASP recommends an NVD API key to avoid throttling; CI injects it and
    // local runs can use either an environment variable or a Gradle property.
    nvd.apiKey = nvdApiKey.orEmpty()
    // CI forces this to zero only while producing a new daily candidate. Exact
    // cache hits and secretless fork PRs perform an offline scan of a bounded,
    // previously validated database copy.
    autoUpdate = dependencyCheckAutoUpdate.get()
    nvd.validForHours = dependencyCheckNvdValidForHours
    data.directory = dependencyCheckDataDir
}
