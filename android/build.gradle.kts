import com.android.build.api.variant.ApplicationAndroidComponentsExtension
import groovy.json.JsonOutput
import org.owasp.dependencycheck.dependency.Confidence
import org.owasp.dependencycheck.dependency.Dependency
import org.owasp.dependencycheck.dependency.naming.CpeIdentifier
import org.owasp.dependencycheck.dependency.naming.PurlIdentifier
import org.owasp.dependencycheck.xml.suppression.SuppressionParser

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

// Default to Gradle user home for local use. CI always overrides this with either
// an immutable main artifact copy or an isolated per-run refresh directory.
val dependencyCheckDataDir =
    providers.gradleProperty("dependencyCheckDataDir")
        .map { rootProject.file(it).absolutePath }
        .getOrElse(gradle.gradleUserHomeDir.resolve("dependency-check-data").absolutePath)
val dependencyCheckNvdValidForHours =
    providers.gradleProperty("dependencyCheckNvdValidForHours")
        .map(String::toInt)
        .getOrElse(24)
val dependencyCheckFailBuildOnCvss =
    providers.gradleProperty("dependencyCheckFailBuildOnCVSS")
        .map(String::toFloat)
        .getOrElse(7.0f)
val dependencyCheckSuppressionFile =
    file("config/dependency-check/suppressions.xml")

data class DependencyCheckScope(
    val projectPath: String,
    val projectName: String,
    val configurationName: String,
)

val dependencyCheckApplicationProjects = mutableListOf<String>()
val dependencyCheckScanScopes = mutableListOf<DependencyCheckScope>()
val dependencyCheckReportDirectory =
    layout.buildDirectory.dir("reports/dependency-check")
val dependencyCheckReportFile =
    dependencyCheckReportDirectory.map { it.file("dependency-check-report.json") }
val dependencyCheckReportRelativePath =
    dependencyCheckReportFile.map { it.asFile.relativeTo(projectDir).invariantSeparatorsPath }
val dependencyCheckScopeContract =
    layout.buildDirectory.file("reports/dependency-check-scope.json")

subprojects {
    val applicationProject = this
    pluginManager.withPlugin("com.android.application") {
        dependencyCheckApplicationProjects += applicationProject.path
        val androidComponents =
            extensions.getByType(ApplicationAndroidComponentsExtension::class.java)
        androidComponents.onVariants(
            androidComponents.selector().withBuildType("release"),
        ) { variant ->
            dependencyCheckScanScopes +=
                DependencyCheckScope(
                    applicationProject.path,
                    applicationProject.name,
                    variant.runtimeConfiguration.name,
                )
        }
    }
}

fun resolvedDependencyCheckApplicationProjects(): List<String> {
    val resolved = dependencyCheckApplicationProjects.distinct().sorted()
    check(resolved.isNotEmpty()) { "No Android application projects were discovered." }
    check(resolved.size == dependencyCheckApplicationProjects.size) {
        "Android application projects were discovered more than once."
    }
    return resolved
}

fun resolvedDependencyCheckScanScopes(): List<DependencyCheckScope> {
    val resolved =
        dependencyCheckScanScopes
            .distinct()
            .sortedWith(
                compareBy(
                    DependencyCheckScope::projectPath,
                    DependencyCheckScope::configurationName,
                ),
            )
    check(resolved.isNotEmpty()) { "No Android application release variants were discovered." }
    check(resolved.size == dependencyCheckScanScopes.size) {
        "Android application release variants produced duplicate runtime configurations."
    }
    val ambiguousProjectNames =
        resolved
            .groupBy(DependencyCheckScope::projectName)
            .filterValues { scopes ->
                scopes.map(DependencyCheckScope::projectPath).distinct().size > 1
            }
            .keys
            .sorted()
    check(ambiguousProjectNames.isEmpty()) {
        "Dependency-Check reports project names, so Android application module names must be unique: " +
            ambiguousProjectNames.joinToString()
    }
    return resolved
}

dependencyCheck {
    failBuildOnCVSS = dependencyCheckFailBuildOnCvss
    // Keep failOnError=true: unreadable data, scanner failures, and findings at
    // or above the threshold must all fail the audit rather than become a no-op.
    formats = listOf("HTML", "JSON")
    outputDirectory.set(dependencyCheckReportDirectory)
    suppressionFile = dependencyCheckSuppressionFile.takeIf { it.exists() }?.absolutePath
    // OWASP recommends an NVD API key to avoid throttling; CI injects it and
    // local runs can use either an environment variable or a Gradle property.
    nvd.apiKey = nvdApiKey.orEmpty()
    // CI forces this to zero only while producing or directly refreshing data.
    // Artifact consumers disable updates and scan a bounded, validated copy.
    autoUpdate = dependencyCheckAutoUpdate.get()
    nvd.validForHours = dependencyCheckNvdValidForHours
    data.directory = dependencyCheckDataDir
}

gradle.projectsEvaluated {
    dependencyCheck {
        scanProjects = resolvedDependencyCheckApplicationProjects()
        scanConfigurations =
            resolvedDependencyCheckScanScopes()
                .map(DependencyCheckScope::configurationName)
                .distinct()
                .sorted()
    }
}

val writeDependencyCheckScopeContract =
    tasks.register("writeDependencyCheckScopeContract") {
        val projectReferences =
            provider {
                resolvedDependencyCheckScanScopes().map { scope ->
                    "${scope.projectName}:${scope.configurationName}"
                }
            }
        inputs.property("projectReferences", projectReferences)
        inputs.property("reportPath", dependencyCheckReportRelativePath)
        outputs.file(dependencyCheckScopeContract)
        doLast {
            val output = dependencyCheckScopeContract.get().asFile
            output.parentFile.mkdirs()
            output.writeText(
                JsonOutput.prettyPrint(
                    JsonOutput.toJson(
                        mapOf(
                            "projectReferences" to projectReferences.get(),
                            "reportPath" to dependencyCheckReportRelativePath.get(),
                        ),
                    ),
                ) + "\n",
            )
        }
    }

val verifyDependencyCheckSuppressionContract =
    tasks.register("verifyDependencyCheckSuppressionContract") {
        inputs.file(dependencyCheckSuppressionFile)
        doLast {
            val rules =
                SuppressionParser().parseSuppressionRules(dependencyCheckSuppressionFile)

            fun sqliteDependency(artifact: String): Dependency =
                Dependency(true).apply {
                    addSoftwareIdentifier(
                        PurlIdentifier(
                            "maven",
                            "androidx.sqlite",
                            artifact,
                            "2.6.2",
                            Confidence.HIGHEST,
                        ),
                    )
                    addVulnerableSoftwareIdentifier(
                        CpeIdentifier("sqlite", "sqlite", "2.6.2", Confidence.HIGHEST),
                    )
                    rules.forEach { rule -> rule.process(this) }
                }

            for (artifact in listOf("sqlite-android", "sqlite-framework-android")) {
                check(sqliteDependency(artifact).vulnerableSoftwareIdentifiersCount == 0) {
                    "The AndroidX SQLite false-positive suppression does not match " +
                        "Dependency-Check's runtime CPE representation for $artifact."
                }
            }
            check(sqliteDependency("sqlite-bundled-android").vulnerableSoftwareIdentifiersCount == 1) {
                "The AndroidX SQLite false-positive suppression is broader than its " +
                    "reviewed API/framework package boundary."
            }
        }
    }

tasks.named("dependencyCheckAggregate") {
    doNotTrackState(
        "The external NVD database and resolved dependency graph must be scanned on every invocation.",
    )
    dependsOn(
        writeDependencyCheckScopeContract,
        verifyDependencyCheckSuppressionContract,
    )
}
