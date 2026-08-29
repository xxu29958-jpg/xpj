import java.time.Duration
import java.util.Properties
import java.util.concurrent.TimeUnit

val ticketboxVersionCode = 10200000
val ticketboxVersionName = "1.2.0"
val ticketboxJavaLanguageVersion =
    rootProject.file(".java-version").readText().trim().toIntOrNull()
        ?: error("android/.java-version must contain one Java major version.")

val ticketboxLocalProperties: Properties = Properties().also { props ->
    val propsFile = rootProject.file("local.properties")
    if (propsFile.exists()) {
        propsFile.inputStream().use { stream -> props.load(stream) }
    }
}

fun ticketboxLocalProperty(name: String): String? =
    ticketboxLocalProperties.getProperty(name)?.trim()?.takeIf { it.isNotBlank() }

fun ticketboxEnvOrLocal(envName: String, propertyName: String): String? =
    System.getenv(envName)?.trim()?.takeIf { it.isNotBlank() } ?: ticketboxLocalProperty(propertyName)

// v1.1 Batch 2: local unlock is the safer default for release.
// Owner can opt out per build (debug, internal flavor) via env var
// TICKETBOX_REQUIRE_LOCAL_UNLOCK=true|false or local.properties
// ticketbox.requireLocalUnlock=...
val ticketboxRequireLocalUnlockDebug: Boolean =
    ticketboxEnvOrLocal(
        "TICKETBOX_REQUIRE_LOCAL_UNLOCK",
        "ticketbox.requireLocalUnlock",
    )?.lowercase()?.let { it == "1" || it == "true" || it == "yes" } ?: false
val ticketboxRequireLocalUnlockRelease: Boolean =
    ticketboxEnvOrLocal(
        "TICKETBOX_REQUIRE_LOCAL_UNLOCK",
        "ticketbox.requireLocalUnlock",
    )?.lowercase()?.let { it == "1" || it == "true" || it == "yes" } ?: true

fun ticketboxBooleanEnvOrLocal(envName: String, propertyName: String): Boolean {
    val raw = ticketboxEnvOrLocal(envName, propertyName)?.lowercase() ?: return false
    return raw == "1" || raw == "true" || raw == "yes"
}

val ticketboxAllowRealDeviceConnectedTest: Boolean =
    ticketboxBooleanEnvOrLocal(
        "TICKETBOX_ALLOW_REAL_DEVICE_CONNECTED_TEST",
        "ticketbox.allowRealDeviceConnectedTest",
    )

data class TicketboxDebugSigning(
    val keystorePath: String,
    val keyAlias: String,
    val storePassword: String,
    val keyPassword: String,
)

// Server URL precedence:
//   1. ENV: TICKETBOX_SERVER_URL
//   2. local.properties: ticketbox.serverUrl=...
//   3. fallback: https://api.example.com (debug only; release builds reject this — see hook below)
val ticketboxServerUrlPlaceholder = "https://api.example.com"
val ticketboxServerUrl: String =
    ticketboxEnvOrLocal("TICKETBOX_SERVER_URL", "ticketbox.serverUrl") ?: ticketboxServerUrlPlaceholder

// Release builds must point at a real backend. Refuse to assemble/bundle a release APK/AAB while
// DEFAULT_SERVER_URL still falls back to the api.example.com placeholder — shipping that to gray
// users is a release blocker (codex P1 #5). Debug builds keep the placeholder for local dev.
gradle.taskGraph.whenReady {
    val hasReleasePackagingTask = allTasks.any { task ->
        val n = task.name
        n.contains("Release", ignoreCase = true) && (n.startsWith("assemble") || n.startsWith("bundle"))
    }
    if (hasReleasePackagingTask && ticketboxServerUrl == ticketboxServerUrlPlaceholder) {
        error(
            "Refusing to package a release APK/AAB with DEFAULT_SERVER_URL=$ticketboxServerUrlPlaceholder " +
                "placeholder. Set TICKETBOX_SERVER_URL (env) or local.properties ticketbox.serverUrl=... " +
                "to your real backend before assembleRelease / bundleRelease. Debug builds are unaffected."
        )
    }
}
val ticketboxDebugKeystorePath: String? =
    ticketboxEnvOrLocal("TICKETBOX_DEBUG_KEYSTORE_PATH", "ticketbox.debug.keystore")
val ticketboxDebugKeyAlias: String? =
    ticketboxEnvOrLocal("TICKETBOX_DEBUG_KEY_ALIAS", "ticketbox.debug.keyAlias")
val ticketboxDebugKeystorePassword: String? =
    ticketboxEnvOrLocal("TICKETBOX_DEBUG_KEYSTORE_PASSWORD", "ticketbox.debug.storePassword")
val ticketboxDebugKeyPassword: String? =
    ticketboxEnvOrLocal("TICKETBOX_DEBUG_KEY_PASSWORD", "ticketbox.debug.keyPassword")
val ticketboxAllowCustomDebugSigning: Boolean =
    ticketboxBooleanEnvOrLocal(
        "TICKETBOX_ALLOW_CUSTOM_DEBUG_SIGNING",
        "ticketbox.debug.allowCustomSigning",
    )
val ticketboxCanonicalDebugSigning = TicketboxDebugSigning(
    keystorePath = "config/debug/ticketbox-debug.keystore",
    keyAlias = "ticketbox-debug",
    storePassword = "ticketbox-debug",
    keyPassword = "ticketbox-debug",
)
val ticketboxExternalDebugSigningValues = listOf(
    ticketboxDebugKeystorePath,
    ticketboxDebugKeyAlias,
    ticketboxDebugKeystorePassword,
    ticketboxDebugKeyPassword,
)
val ticketboxDebugSigning: TicketboxDebugSigning =
    if (ticketboxExternalDebugSigningValues.all { it != null }) {
        if (!ticketboxAllowCustomDebugSigning) {
            error(
                "Custom debug signing is disabled by default because it breaks adb install -r " +
                    "replacement between local builds and CI artifacts. Remove the " +
                    "TICKETBOX_DEBUG_* / ticketbox.debug.* signing overrides to use the " +
                    "repository debug key, or explicitly set TICKETBOX_ALLOW_CUSTOM_DEBUG_SIGNING=true " +
                    "or ticketbox.debug.allowCustomSigning=true.",
            )
        }
        TicketboxDebugSigning(
            keystorePath = ticketboxDebugKeystorePath!!,
            keyAlias = ticketboxDebugKeyAlias!!,
            storePassword = ticketboxDebugKeystorePassword!!,
            keyPassword = ticketboxDebugKeyPassword!!,
        )
    } else if (ticketboxExternalDebugSigningValues.any { it != null }) {
        error(
            "Debug signing config is incomplete. Set all TICKETBOX_DEBUG_KEYSTORE_PATH, " +
                "TICKETBOX_DEBUG_KEY_ALIAS, TICKETBOX_DEBUG_KEYSTORE_PASSWORD, and " +
                "TICKETBOX_DEBUG_KEY_PASSWORD, or remove them to use the repository debug key.",
        )
    } else {
        ticketboxCanonicalDebugSigning
    }
val ticketboxDebugKeystoreFile = rootProject.file(ticketboxDebugSigning.keystorePath)
if (!ticketboxDebugKeystoreFile.exists()) {
    error("Debug keystore does not exist: ${ticketboxDebugKeystoreFile.path}")
}

plugins {
    alias(libs.plugins.android.application)
    // issue #64 A1: consumer side — creates the `baselineProfile` configuration
    // and merges the generated baseline-prof.txt into release builds. Generation
    // is device-only and off by default (automaticGenerationDuringBuild=false), so
    // ordinary debug/release builds and CI never spin up a device.
    alias(libs.plugins.androidx.baselineprofile)
    alias(libs.plugins.detekt)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.ticketbox"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.ticketbox"
        minSdk = 28
        targetSdk = 36
        versionCode = ticketboxVersionCode
        versionName = ticketboxVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        resValue("string", "app_version_name", ticketboxVersionName)
        resValue("integer", "app_version_code", ticketboxVersionCode.toString())
        buildConfigField("Boolean", "SHOW_ADVANCED_TOOLS", "false")
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"${ticketboxServerUrl}\"")
        manifestPlaceholders["appLabel"] = "小票夹"
    }

    flavorDimensions += "audience"
    productFlavors {
        create("gray") {
            dimension = "audience"
            manifestPlaceholders["appLabel"] = "小票夹"
            resValue("string", "app_version_name", ticketboxVersionName)
            buildConfigField("Boolean", "SHOW_ADVANCED_TOOLS", "false")
        }
        create("internal") {
            dimension = "audience"
            applicationIdSuffix = ".internal"
            versionNameSuffix = "-internal"
            manifestPlaceholders["appLabel"] = "小票夹内部版"
            resValue("string", "app_version_name", "$ticketboxVersionName-internal")
            buildConfigField("Boolean", "SHOW_ADVANCED_TOOLS", "true")
        }
    }

    signingConfigs {
        create("stableDebug") {
            storeFile = ticketboxDebugKeystoreFile
            storePassword = ticketboxDebugSigning.storePassword
            keyAlias = ticketboxDebugSigning.keyAlias
            keyPassword = ticketboxDebugSigning.keyPassword
        }

        val releaseKeystorePath = System.getenv("TICKETBOX_KEYSTORE_PATH")
        val releaseKeyAlias = System.getenv("TICKETBOX_KEY_ALIAS")
        val releaseKeystorePassword = System.getenv("TICKETBOX_KEYSTORE_PASSWORD")
        val releaseKeyPassword = System.getenv("TICKETBOX_KEY_PASSWORD")
        if (
            !releaseKeystorePath.isNullOrBlank() &&
            !releaseKeyAlias.isNullOrBlank() &&
            !releaseKeystorePassword.isNullOrBlank() &&
            !releaseKeyPassword.isNullOrBlank()
        ) {
            create("release") {
                storeFile = file(releaseKeystorePath)
                storePassword = releaseKeystorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        debug {
            buildConfigField(
                "Boolean",
                "REQUIRE_LOCAL_UNLOCK",
                ticketboxRequireLocalUnlockDebug.toString(),
            )
            signingConfigs.findByName("stableDebug")?.let { stableDebugSigning ->
                signingConfig = stableDebugSigning
            }
        }
        release {
            isDebuggable = false
            // v1.1 Batch 2: R8 minify + resource shrinking on release.
            // Keep rules are in proguard-rules.pro alongside this file.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            buildConfigField(
                "Boolean",
                "REQUIRE_LOCAL_UNLOCK",
                ticketboxRequireLocalUnlockRelease.toString(),
            )
            signingConfigs.findByName("release")?.let { releaseSigning ->
                signingConfig = releaseSigning
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
        compose = true
        resValues = true
    }

    // ADR-0041 follow-up: package the exported Room schemas as androidTest assets
    // so MigrationTestHelper can load 10.json / 11.json and validate v10→v11.
    sourceSets {
        getByName("androidTest") {
            assets.srcDir("$projectDir/schemas")
        }
    }
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(ticketboxJavaLanguageVersion)
    }
}

val ticketboxResolvedBuildToolsVersion = providers.provider { android.buildToolsVersion }
val writeTicketboxBuildToolsVersion by tasks.registering {
    val outputFile = layout.buildDirectory.file("ticketbox-ci/build-tools-version.txt")
    inputs.property("buildToolsVersion", ticketboxResolvedBuildToolsVersion)
    outputs.file(outputFile)
    doLast {
        outputFile.get().asFile.apply {
            parentFile.mkdirs()
            writeText("${ticketboxResolvedBuildToolsVersion.get()}\n")
        }
    }
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
    arg("room.incremental", "true")
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

// issue #64 A2: Compose model stability via the compiler's stability config.
//
// stabilityConfigurationFiles tells the Compose compiler to treat the listed
// types as stable, so composables that take them — directly, or as the element
// type of a List/Map parameter — become skippable and stop recomposing every
// list item when an unrelated part of the parent state changes. The hard rule
// (issue #64 A2) is that domain/model must NOT import Compose, so we never put
// @Stable/@Immutable on the data classes; this external file carries the same
// signal without the dependency. compose_stability_config.conf lists only the
// types the metrics report verified as unstable.
//
// Metrics/reports are opt-in via -Pticketbox.composeMetrics=true so normal and
// CI builds pay nothing (no extra task outputs, no behavior change). Regenerate
// the stability report with:
//   ./gradlew :app:compileGrayDebugKotlin -Pticketbox.composeMetrics=true
// then read app/build/compose_compiler/*-classes.txt (per-class stability) and
// *-composables.txt (skippable/restartable per @Composable).
composeCompiler {
    stabilityConfigurationFiles.add(
        layout.projectDirectory.file("compose_stability_config.conf"),
    )
    if (project.findProperty("ticketbox.composeMetrics") == "true") {
        val composeMetricsDir = layout.buildDirectory.dir("compose_compiler")
        metricsDestination.set(composeMetricsDir)
        reportsDestination.set(composeMetricsDir)
    }
}

// ADR-0041 follow-up: androidx.lifecycle 2.10.0 transitively pins
// kotlinx-serialization to 1.7.3 (Kotlin-2.0 era) `strictly`, which is binary-
// incompatible with room-testing 2.8.4's schema-bundle serializers — they need
// ≥1.8.0 (AbstractMethodError: GeneratedSerializer.typeParametersSerializers()
// in MigrationTestHelper.loadSchema otherwise). Align to 1.10.0 to match the
// project's Kotlin 2.3.21; lifecycle's 1.7.3-era generated serializers run
// forward-compatibly on the newer runtime (the instrumented screen + migration
// tests on the emulator lane confirm both still work).
configurations.configureEach {
    // issue #64 A1 startup follow-up: profileinstaller must stay in release
    // builds to install the generated Baseline Profile, but debug builds do not
    // carry that release profile. Several AndroidX dependencies pull
    // profileinstaller transitively, so keep debug runtime manifests free of
    // its Startup initializer explicitly.
    if (name.endsWith("DebugRuntimeClasspath")) {
        exclude(group = "androidx.profileinstaller", module = "profileinstaller")
    }
    resolutionStrategy {
        force("org.jetbrains.kotlinx:kotlinx-serialization-core:1.10.0")
        force("org.jetbrains.kotlinx:kotlinx-serialization-json:1.10.0")
    }
}

// Instrumentation code runs in a separate APK but against the debug target APK.
// ProfileInstaller belongs to the release app, and its transitive test copy
// contributes a Startup provider whose shared runtime classes AGP keeps in the
// target APK. Exclude it at the official androidTest boundary so the test
// process cannot publish a provider it cannot load.
configurations.named("androidTestImplementation") {
    exclude(group = "androidx.profileinstaller", module = "profileinstaller")
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.exifinterface)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.fragment.ktx)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material3.adaptive)
    implementation(libs.androidx.compose.material3.adaptive.layout)
    implementation(libs.androidx.compose.material.icons.extended)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)

    // ADR-0038 PR-2g.2: WorkManager drains the outbox on a
    // connectivity-up-aware periodic schedule and on explicit
    // enqueue triggers. CoroutineWorker comes from the main
    // work-runtime jar (the -ktx artifact has been empty since
    // 2.9.0).
    implementation(libs.androidx.work.runtime)

    implementation(libs.okhttp)
    implementation(libs.okhttp.logging.interceptor)
    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.moshi)
    implementation(libs.moshi.kotlin)
    ksp(libs.moshi.kotlin.codegen)

    implementation(libs.androidx.biometric)
    implementation(libs.coroutines.android)
    implementation(libs.coil.compose)
    implementation(libs.coil.network.okhttp)
    implementation(libs.compose.shimmer)
    implementation(libs.lottie.compose)

    // issue #64 A1: profileinstaller installs the bundled Baseline Profile on
    // first release run (AOT dexopt of the hot startup path); it self-initialises
    // via its androidx-startup ContentProvider, so no app code is needed. Keep it
    // out of debug builds: debug APKs do not carry the generated release profile,
    // and startup QA should not pay for a no-op ProfileInstaller initializer.
    releaseImplementation(libs.androidx.profileinstaller)
    "baselineProfile"(project(":macrobenchmark"))

    testImplementation(libs.kotlin.test)
    testImplementation(libs.coroutines.test)
    // WorkManager TestDriver / TestListenableWorkerBuilder for the
    // outbox drain worker unit tests (Robolectric-free).
    testImplementation(libs.androidx.work.testing)
    // ADR-0041 follow-up: in-memory SQLite for the fast, emulator-free JVM
    // Room-migration SQL test — a local floor complementing the instrumented
    // MigrationTestHelper test below.
    testImplementation(libs.sqlite.jdbc)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    // ADR-0041 follow-up: real Room v10→v11 MigrationTestHelper coverage,
    // unblocked by aligning kotlinx-serialization to 1.10.0 (configurations
    // force above). Test-only artifact of the adopted Room library (same 2.8.4).
    androidTestImplementation(libs.androidx.room.testing)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}

// Machine gate for the six Kotlin complexity thresholds in
// docs/rules/CODE_QUALITY_STANDARDS.md. CI runs the type-resolving variant
// tasks (:app:detektGrayDebug + :app:detektGrayDebugUnitTest): detekt 2.0's
// embedded Kotlin matches this project's, and LongParameterList only runs
// under full analysis (the plain :app:detekt task silently skips it).
// Pre-existing violations are frozen per variant in
// detekt-baseline-grayDebug.xml / detekt-baseline-grayDebugUnitTest.xml —
// new/edited code must comply. Known alpha wart: the analysis classpath
// misses AGP-generated BuildConfig (35 unresolved-reference warnings); the
// six gated rules are syntax-level counts, so reporting stays accurate.
detekt {
    buildUponDefaultConfig = false
    config.setFrom(rootProject.file("detekt.yml"))
    baseline = file("detekt-baseline.xml")
    parallel = true
}

tasks.withType<dev.detekt.gradle.Detekt>().configureEach {
    exclude { element ->
        element.file.absolutePath
            .replace('\\', '/')
            .contains("/build/generated/")
    }
}

val androidTestBaselineFile = rootProject.file("audit/test_count_baseline.txt")
val androidTestQualificationScript =
    rootProject.file("scripts/verify_android_test_qualification.py")

fun ticketboxPythonCommand(): List<String> {
    val configured = ticketboxEnvOrLocal(
        "TICKETBOX_PYTHON",
        "ticketbox.pythonExecutable",
    )
    val isWindows = System.getProperty("os.name").contains("Windows", ignoreCase = true)
    val candidates = buildList {
        configured?.let { add(listOf(it)) }
        if (isWindows) {
            add(listOf("py", "-3"))
            add(listOf("python"))
        } else {
            add(listOf("python3"))
            add(listOf("python"))
        }
    }.distinct()

    return candidates.firstOrNull { command ->
        try {
            val commandProcess = ProcessBuilder(command + "--version")
                .directory(rootProject.rootDir)
                .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                .redirectError(ProcessBuilder.Redirect.DISCARD)
                .start()
            val completed = commandProcess.waitFor(10, TimeUnit.SECONDS)
            if (!completed) {
                commandProcess.destroyForcibly()
            }
            completed && commandProcess.exitValue() == 0
        } catch (_: Exception) {
            false
        }
    } ?: throw GradleException(
        "Python 3 is required for Android test qualification. Set TICKETBOX_PYTHON " +
            "or ticketbox.pythonExecutable, or make python3/python available on PATH."
    )
}

fun runTicketboxAndroidQualification(
    description: String,
    arguments: List<String>,
) {
    if (!androidTestQualificationScript.isFile) {
        throw GradleException(
            "Android test qualification script is missing: " +
                androidTestQualificationScript.absolutePath
        )
    }
    val command = ticketboxPythonCommand() +
        androidTestQualificationScript.absolutePath +
        arguments
    val qualificationProcess = ProcessBuilder(command)
        .directory(rootProject.rootDir.parentFile)
        .inheritIO()
        .start()
    if (!qualificationProcess.waitFor(2, TimeUnit.MINUTES)) {
        qualificationProcess.destroyForcibly()
        throw GradleException("Timed out while $description.")
    }
    if (qualificationProcess.exitValue() != 0) {
        throw GradleException(
            "$description failed with exit code " +
                qualificationProcess.exitValue() + "."
        )
    }
}

val grayDebugUnitTestTaskName = "testGrayDebugUnitTest"
val grayDebugUnitTestResultsDirectory =
    layout.buildDirectory.dir("test-results/$grayDebugUnitTestTaskName")

tasks.register("assertAndroidTestCountEqualsBaseline") {
    group = "verification"
    description = "Verify executed GrayDebug JVM results meet the Android test-count minimum ratchet."
    dependsOn(grayDebugUnitTestTaskName)
    inputs.file(androidTestBaselineFile)

    doLast {
        runTicketboxAndroidQualification(
            "GrayDebug JVM test-result qualification",
            listOf(
                "results",
                "--lane",
                "jvm",
                "--baseline",
                androidTestBaselineFile.absolutePath,
                "--results-dir",
                grayDebugUnitTestResultsDirectory.get().asFile.absolutePath,
            ),
        )
        runTicketboxAndroidQualification(
            "Android test baseline ratchet",
            listOf(
                "baseline",
                "--baseline",
                androidTestBaselineFile.absolutePath,
                "--repository-root",
                rootProject.rootDir.parentFile.absolutePath,
            ),
        )
    }
}


fun ticketboxAndroidSdkDirectory(): File? {
    val sdkDir = ticketboxLocalProperty("sdk.dir")
        ?: System.getenv("ANDROID_HOME")?.trim()?.takeIf { it.isNotBlank() }
        ?: System.getenv("ANDROID_SDK_ROOT")?.trim()?.takeIf { it.isNotBlank() }
    return sdkDir?.let(::File)?.takeIf(File::isDirectory)
}

fun ticketboxAdbExecutable(): File? {
    val adbName = if (System.getProperty("os.name").contains("Windows", ignoreCase = true)) {
        "adb.exe"
    } else {
        "adb"
    }
    return ticketboxAndroidSdkDirectory()
        ?.resolve("platform-tools/$adbName")
        ?.takeIf { it.exists() }
}

fun ticketboxApkAnalyzerExecutable(): File? {
    ticketboxEnvOrLocal(
        "TICKETBOX_APKANALYZER",
        "ticketbox.apkanalyzerExecutable",
    )?.let(::File)?.takeIf(File::isFile)?.let { return it }

    val sdkDirectory = ticketboxAndroidSdkDirectory() ?: return null
    val executableName = if (
        System.getProperty("os.name").contains("Windows", ignoreCase = true)
    ) {
        "apkanalyzer.bat"
    } else {
        "apkanalyzer"
    }
    val commandLineTools = sdkDirectory.resolve("cmdline-tools")
        .listFiles()
        ?.filter(File::isDirectory)
        .orEmpty()
        .sortedWith(
            compareByDescending<File> { it.name.equals("latest", ignoreCase = true) }
                .thenByDescending(File::getName)
        )
    return commandLineTools.asSequence()
        .map { it.resolve("bin/$executableName") }
        .firstOrNull(File::isFile)
}

fun ticketboxReadyDeviceSerials(): List<String> {
    val adb = ticketboxAdbExecutable() ?: return emptyList()
    val process = ProcessBuilder(adb.absolutePath, "devices", "-l")
        .directory(rootProject.rootDir)
        .redirectErrorStream(true)
        .start()
    if (!process.waitFor(30, TimeUnit.SECONDS) || process.exitValue() != 0) {
        return emptyList()
    }
    return process.inputStream.bufferedReader().readLines()
        .drop(1)
        .map { it.trim() }
        .filter { it.isNotEmpty() }
        .mapNotNull { line ->
            val parts = line.split(Regex("\\s+"))
            parts.firstOrNull()?.takeIf { parts.getOrNull(1) == "device" }
        }
}

fun ticketboxSelectedConnectedTestEmulatorSerial(readySerials: List<String>): String? {
    val selectedSerial = System.getenv("ANDROID_SERIAL")?.trim()?.takeIf { it.isNotBlank() }
        ?: return null
    return selectedSerial.takeIf { serial ->
        serial.startsWith("emulator-", ignoreCase = true) &&
            readySerials.any { it.equals(serial, ignoreCase = true) }
    }
}

val guardConnectedAndroidTestEmulatorOnly by tasks.registering {
    group = "verification"
    description = "Refuse connected Android tests on physical devices unless explicitly opted in."

    doLast {
        if (ticketboxAllowRealDeviceConnectedTest) {
            return@doLast
        }
        val readySerials = ticketboxReadyDeviceSerials()
        if (ticketboxSelectedConnectedTestEmulatorSerial(readySerials) != null) {
            return@doLast
        }
        val physicalDevices = readySerials
            .filterNot { it.startsWith("emulator-", ignoreCase = true) }
        if (physicalDevices.isNotEmpty()) {
            throw GradleException(
                "Refusing to run connected Android tests on physical device(s): " +
                    physicalDevices.joinToString(", ") + ". These tasks can install test APKs " +
                    "and disturb a bound daily-use app. Use an emulator, or explicitly set " +
                    "TICKETBOX_ALLOW_REAL_DEVICE_CONNECTED_TEST=true / " +
                    "ticketbox.allowRealDeviceConnectedTest=true after confirming app data loss is acceptable.",
            )
        }
    }
}

fun ticketboxConnectedEvidenceFile(fileName: String): File =
    System.getenv("RUNNER_TEMP")
        ?.trim()
        ?.takeIf { it.isNotBlank() }
        ?.let { File(it, fileName) }
        ?: layout.buildDirectory
            .file("reports/androidTests/$fileName")
            .get()
            .asFile

fun prepareTicketboxConnectedEvidenceFile(evidenceFile: File) {
    val evidenceDirectory = evidenceFile.parentFile
        ?: throw GradleException("Connected-test evidence file has no parent directory.")
    if (!evidenceDirectory.isDirectory && !evidenceDirectory.mkdirs()) {
        throw GradleException("Cannot create connected-test evidence directory.")
    }
}

fun ticketboxConnectedCaptureSerials(): List<String> {
    val readySerials = ticketboxReadyDeviceSerials()
    val selectedSerial = System.getenv("ANDROID_SERIAL")
        ?.trim()
        ?.takeIf { it.isNotBlank() }
    val captureSerials = when {
        selectedSerial != null -> readySerials.filter {
            it.equals(selectedSerial, ignoreCase = true)
        }
        ticketboxAllowRealDeviceConnectedTest -> readySerials
        else -> readySerials.filter { it.startsWith("emulator-", ignoreCase = true) }
    }
    if (captureSerials.isEmpty()) {
        throw GradleException(
            "No ready connected-test target is available for evidence capture."
        )
    }
    return captureSerials
}

fun captureTicketboxConnectedAdbEvidence(
    adb: File,
    serials: List<String>,
    evidenceFile: File,
    description: String,
    arguments: List<String>,
) {
    serials.forEach { serial ->
        evidenceFile.appendText("===== Android target $serial =====\n")
        val process = ProcessBuilder(
            listOf(adb.absolutePath, "-s", serial) + arguments
        )
            .directory(rootProject.rootDir)
            .redirectErrorStream(true)
            .redirectOutput(ProcessBuilder.Redirect.appendTo(evidenceFile))
            .start()
        if (!process.waitFor(30, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            throw GradleException("Timed out while capturing $description from $serial.")
        }
        if (process.exitValue() != 0) {
            throw GradleException(
                "Could not capture $description from $serial: " + evidenceFile.readText()
            )
        }
        evidenceFile.appendText("\n")
    }
}

val grayConnectedTestResultsDirectory =
    layout.buildDirectory.dir("outputs/androidTest-results/connected")
val grayDebugApkOutputDirectory =
    layout.buildDirectory.dir("outputs/apk/gray/debug")
val grayDebugAndroidTestApkOutputDirectory =
    layout.buildDirectory.dir("outputs/apk/androidTest/gray/debug")

val prepareGrayConnectedTestEvidence by tasks.registering {
    group = "verification"
    description = "Reset connected results and capture the pre-test process-exit baseline."
    dependsOn(guardConnectedAndroidTestEmulatorOnly)

    doLast {
        val adb = ticketboxAdbExecutable()
            ?: throw GradleException("Android adb is unavailable; cannot capture exit evidence.")
        val crashLog = ticketboxConnectedEvidenceFile("ticketbox-connected-crash.log")
        val beforeExitInfo = ticketboxConnectedEvidenceFile(
            "ticketbox-connected-exit-info-before.txt"
        )
        val afterExitInfo = ticketboxConnectedEvidenceFile(
            "ticketbox-connected-exit-info-after.txt"
        )
        prepareTicketboxConnectedEvidenceFile(crashLog)
        crashLog.writeText("")
        beforeExitInfo.writeText("")
        afterExitInfo.writeText("")
        project.delete(grayConnectedTestResultsDirectory)
        captureTicketboxConnectedAdbEvidence(
            adb,
            ticketboxConnectedCaptureSerials(),
            beforeExitInfo,
            "the pre-test process-exit baseline",
            listOf("shell", "dumpsys", "activity", "exit-info"),
        )
    }
}

tasks.matching { it.name.matches(Regex("connected.*AndroidTest")) }.configureEach {
    dependsOn(guardConnectedAndroidTestEmulatorOnly)
    if (name == "connectedGrayDebugAndroidTest") {
        dependsOn(prepareGrayConnectedTestEvidence)
        timeout.set(Duration.ofMinutes(10))
        doLast {
            val adb = ticketboxAdbExecutable()
                ?: throw GradleException(
                    "Android adb is unavailable; cannot qualify connected tests."
                )
            val apkanalyzer = ticketboxApkAnalyzerExecutable()
                ?: throw GradleException(
                    "Android apkanalyzer is unavailable; cannot qualify connected tests."
                )
            val captureSerials = ticketboxConnectedCaptureSerials()
            val beforeExitInfo = ticketboxConnectedEvidenceFile(
                "ticketbox-connected-exit-info-before.txt"
            )
            val afterExitInfo = ticketboxConnectedEvidenceFile(
                "ticketbox-connected-exit-info-after.txt"
            )
            val crashLog = ticketboxConnectedEvidenceFile(
                "ticketbox-connected-crash.log"
            )
            captureTicketboxConnectedAdbEvidence(
                adb,
                captureSerials,
                afterExitInfo,
                "the post-test process-exit snapshot",
                listOf("shell", "dumpsys", "activity", "exit-info"),
            )
            captureTicketboxConnectedAdbEvidence(
                adb,
                captureSerials,
                crashLog,
                "the connected-test crash buffer",
                listOf("logcat", "-b", "crash", "-d"),
            )
            runTicketboxAndroidQualification(
                "GrayDebug connected-test qualification",
                listOf(
                    "connected",
                    "--baseline",
                    androidTestBaselineFile.absolutePath,
                    "--results-dir",
                    grayConnectedTestResultsDirectory.get().asFile.absolutePath,
                    "--before",
                    beforeExitInfo.absolutePath,
                    "--after",
                    afterExitInfo.absolutePath,
                    "--apkanalyzer",
                    apkanalyzer.absolutePath,
                    "--target-apk-output-dir",
                    grayDebugApkOutputDirectory.get().asFile.absolutePath,
                    "--instrumentation-apk-output-dir",
                    grayDebugAndroidTestApkOutputDirectory.get().asFile.absolutePath,
                ),
            )
        }
    }
}
