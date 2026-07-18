import groovy.json.JsonOutput
import java.security.MessageDigest
import org.gradle.api.artifacts.component.ModuleComponentIdentifier

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
        .orNull

val dependencyCheckAutoUpdate =
    providers.gradleProperty("dependencyCheckAutoUpdate")
        .map { it.toBoolean() }
        .orElse(true)

val dependencyCheckRuntimeConfigurations =
    listOf(
        "grayDebugRuntimeClasspath",
        "grayReleaseRuntimeClasspath",
        "internalDebugRuntimeClasspath",
        "internalReleaseRuntimeClasspath",
    )
val dependencyCheckRuntimeInventoryFile =
    layout.buildDirectory.file("reports/dependency-check-runtime-inventory.json")

// Keep the NVD database under Gradle user home so the protected producer can
// refresh one cache while pull requests consume and revalidate it read-only.
val dependencyCheckDataDir =
    gradle.gradleUserHomeDir.resolve("dependency-check-data").absolutePath

dependencyCheck {
    failBuildOnCVSS = 7.0f
    // Keep this explicit: corrupt/unreadable cache data must never become a
    // successful report-shaped no-op when an upstream default changes.
    failOnError = true
    // Corrupt or unreadable H2 data must fail the task instead of producing a
    // report-shaped no-op that bypasses the CVSS policy.
    formats = listOf("HTML", "JSON")
    // The plugin is applied at the root only. Aggregate is the multi-project
    // task and this explicit scope prevents a green root-only no-op.
    scanProjects = listOf(":app")
    // Scan only dependencies that can enter a shipped APK. AGP also exposes
    // compiler, KSP, lint, detekt, and other build-tool configurations; those
    // belong to build-provenance auditing, not the Android runtime CVE gate.
    scanConfigurations = dependencyCheckRuntimeConfigurations
    suppressionFile = file("config/dependency-check/suppressions.xml").takeIf { it.exists() }?.absolutePath
    // OWASP recommends an NVD API key to avoid throttling. It enters Gradle
    // only through the process environment so it never appears in command
    // arguments or project properties.
    nvd.apiKey = nvdApiKey.orEmpty()
    // This lane has one vulnerability-data authority: the certified NVD
    // payload. OSS Index requires separate Sonatype credentials and remote
    // availability, so it must not be enabled implicitly by plugin defaults.
    analyzers.ossIndex.enabled = false
    // The hosted feed is a second mutable suppression authority. All accepted
    // suppressions must instead be reviewable in the committed local file.
    hostedSuppressions.enabled = false
    autoUpdate = dependencyCheckAutoUpdate.get()
    nvd.validForHours = 24
    data.directory = dependencyCheckDataDir
}

val verifyDependencyCheckContract =
    tasks.register("verifyDependencyCheckContract") {
        group = "verification"
        description = "Verifies the effective OWASP dependency-check runtime contract."
        doLast {
            check(dependencyCheck.failOnError == true) {
                "dependency-check must fail when its data or analyzer fails"
            }
            check(dependencyCheck.scanProjects == listOf(":app")) {
                "dependency-check must scan exactly :app"
            }
            check(
                dependencyCheck.scanConfigurations ==
                    dependencyCheckRuntimeConfigurations
            ) {
                "dependency-check must scan exactly the four shipped runtime classpaths"
            }
            check(dependencyCheck.formats == listOf("HTML", "JSON")) {
                "dependency-check must produce HTML and JSON reports"
            }
            check(dependencyCheck.failBuildOnCVSS == 7.0f) {
                "dependency-check policy must fail at CVSS 7 or above"
            }
            check(dependencyCheck.autoUpdate == dependencyCheckAutoUpdate.get()) {
                "dependency-check autoUpdate drifted from its runtime property"
            }
            check(dependencyCheck.nvd.validForHours == 24) {
                "dependency-check NVD freshness drifted from its runtime property"
            }
            check(dependencyCheck.data.directory == dependencyCheckDataDir) {
                "dependency-check data directory drifted from the shared cache contract"
            }
            check(dependencyCheck.analyzers.ossIndex.enabled == false) {
                "dependency-check must not add an unauthenticated OSS Index data source"
            }
            check(dependencyCheck.hostedSuppressions.enabled == false) {
                "dependency-check must use only committed suppression policy"
            }
        }
    }

val exportDependencyCheckRuntimeInventory =
    tasks.register("exportDependencyCheckRuntimeInventory") {
        group = "verification"
        description = "Exports the independently resolved Android runtime dependency inventory."
        outputs.file(dependencyCheckRuntimeInventoryFile)
        outputs.upToDateWhen { false }
        doLast {
            fun sha256(file: File): String {
                val digest = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) {
                            break
                        }
                        digest.update(buffer, 0, count)
                    }
                }
                return digest.digest().joinToString("") {
                    (it.toInt() and 0xff).toString(16).padStart(2, '0')
                }
            }

            val appProject = project(":app")
            val configurations =
                linkedMapOf<String, List<Map<String, String>>>()
            for (configurationName in dependencyCheckRuntimeConfigurations) {
                val artifacts =
                    appProject.configurations
                        .getByName(configurationName)
                        .incoming
                        .artifacts
                        .artifacts
                        .map { artifact ->
                            val component =
                                artifact.id.componentIdentifier
                                    as? ModuleComponentIdentifier
                                    ?: error(
                                        "runtime artifact is not a versioned module: " +
                                            artifact.id.displayName
                                    )
                            val file = artifact.file
                            check(file.isFile) {
                                "runtime artifact is not a regular file: $file"
                            }
                            linkedMapOf(
                                "group" to component.group,
                                "name" to component.module,
                                "version" to component.version,
                                "fileName" to file.name,
                                "sha256" to sha256(file),
                            )
                        }.distinct()
                        .sortedWith(
                            compareBy<Map<String, String>>(
                                { it.getValue("group") },
                                { it.getValue("name") },
                                { it.getValue("version") },
                                { it.getValue("fileName") },
                                { it.getValue("sha256") },
                            )
                        )
                check(artifacts.isNotEmpty()) {
                    "$configurationName resolved no runtime artifacts"
                }
                configurations["app:$configurationName"] = artifacts
            }

            val document =
                linkedMapOf<String, Any>(
                    "schema" to 1,
                    "project" to rootProject.name,
                    "configurations" to configurations,
                )
            val output = dependencyCheckRuntimeInventoryFile.get().asFile
            output.parentFile.mkdirs()
            output.writeText(
                JsonOutput.prettyPrint(JsonOutput.toJson(document)) + "\n",
                Charsets.UTF_8,
            )
        }
    }

tasks.named("dependencyCheckUpdate") {
    dependsOn(verifyDependencyCheckContract)
}

tasks.named("dependencyCheckAggregate") {
    dependsOn(verifyDependencyCheckContract)
    dependsOn(exportDependencyCheckRuntimeInventory)
}
