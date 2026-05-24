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

dependencyCheck {
    failBuildOnCVSS = 7.0f
    formats = listOf("HTML", "JSON")
    suppressionFile = file("config/dependency-check/suppressions.xml").takeIf { it.exists() }?.absolutePath
    // OWASP recommends an NVD API key to avoid throttling; CI injects it and
    // local runs can use either an environment variable or a Gradle property.
    nvd.apiKey = nvdApiKey.orEmpty()
}
