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

val dependencyCheckNvdValidForHours =
    providers.gradleProperty("dependencyCheckNvdValidForHours")
        .map {
            val hours = it.toInt()
            require(hours == 0 || hours == 24) {
                "dependencyCheckNvdValidForHours must be 0 or 24"
            }
            hours
        }
        .orElse(24)

val requestedDependencyCheckTasks =
    gradle.startParameter.taskNames
        .map { it.substringAfterLast(':') }
        .filter { it.startsWith("dependencyCheck") }
val dependencyCheckDataValidationRequested =
    "dependencyCheckValidateNvd" in requestedDependencyCheckTasks
if (dependencyCheckDataValidationRequested) {
    require(requestedDependencyCheckTasks == listOf("dependencyCheckValidateNvd")) {
        "dependencyCheckValidateNvd cannot be combined with another dependency-check task"
    }
}
val dependencyCheckPolicyCvssThreshold = 7.0f
val dependencyCheckPayloadValidationCvssThreshold = 11.0f
val dependencyCheckFailBuildOnCvss =
    if (dependencyCheckDataValidationRequested) {
        dependencyCheckPayloadValidationCvssThreshold
    } else {
        dependencyCheckPolicyCvssThreshold
    }
val dependencyCheckRuntimeConfigurations =
    listOf(
        "grayDebugRuntimeClasspath",
        "grayReleaseRuntimeClasspath",
        "internalDebugRuntimeClasspath",
        "internalReleaseRuntimeClasspath",
    )
val dependencyCheckRuntimeInventoryFile =
    layout.buildDirectory.file("reports/dependency-check-runtime-inventory.json")

// Keep the NVD database under Gradle user home so trusted CI events can
// refresh one cache while pull requests consume it read-only.
val dependencyCheckDataDir =
    gradle.gradleUserHomeDir.resolve("dependency-check-data").absolutePath

dependencyCheck {
    failBuildOnCVSS = dependencyCheckFailBuildOnCvss
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
    // A trusted producer overrides both properties to force a real refresh.
    // Existing CI keeps the warm-cache default until the read-only consumer
    // replaces it, so the staged rollout never creates two forced writers.
    autoUpdate = dependencyCheckAutoUpdate.get()
    nvd.validForHours = dependencyCheckNvdValidForHours.get()
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
            check(dependencyCheck.autoUpdate == dependencyCheckAutoUpdate.get()) {
                "dependency-check autoUpdate drifted from its runtime property"
            }
            check(dependencyCheck.nvd.validForHours == dependencyCheckNvdValidForHours.get()) {
                "dependency-check NVD freshness drifted from its runtime property"
            }
            if (dependencyCheckDataValidationRequested) {
                check(dependencyCheck.failBuildOnCVSS == 11.0f) {
                    "dependency-check payload validation must not adjudicate CVE policy"
                }
            } else {
                check(dependencyCheck.failBuildOnCVSS == 7.0f) {
                    "dependency-check policy scans must fail at CVSS 7 or above"
                }
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

tasks.register("dependencyCheckValidateNvd") {
    group = "verification"
    description = "Validates NVD data and report scope without adjudicating CVE policy."
    dependsOn("dependencyCheckAggregate")
}
