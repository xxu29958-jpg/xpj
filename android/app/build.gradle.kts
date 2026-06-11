import java.util.Properties
import java.util.concurrent.TimeUnit

val ticketboxVersionCode = 10200000
val ticketboxVersionName = "1.2.0"

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

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
    arg("room.incremental", "true")
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
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
    resolutionStrategy {
        force("org.jetbrains.kotlinx:kotlinx-serialization-core:1.10.0")
        force("org.jetbrains.kotlinx:kotlinx-serialization-json:1.10.0")
    }
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

    implementation(libs.androidx.biometric)
    implementation(libs.coroutines.android)
    implementation(libs.vico.compose.m3)
    implementation(libs.coil.compose)
    implementation(libs.coil.network.okhttp)
    implementation(libs.compose.shimmer)
    implementation(libs.lottie.compose)

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

// ---------------------------------------------------------------------------
// ADR-0038 prep: PR-Δ verification — Android side
// ---------------------------------------------------------------------------
//
// Counterpart to backend's ``_audit_pr_delta_metrics.py`` strict-equality
// gate. The Android count is enforced here (not by reaching across the
// backend/android boundary) — each side owns its own baseline file and
// own assertion. Cut-over PRs (ADR-0038 PR-A/B/C/D etc) that change the
// Android test count MUST bump ``audit/test_count_baseline.txt`` in the
// same diff. Strict equality (NOT >=); drift in either direction fails.
//
// Annotation set covers JUnit4 (``@Test`` only at present) and is
// forward-compatible with a JUnit5 migration (``@ParameterizedTest`` /
// ``@RepeatedTest`` / ``@TestFactory`` / ``@TestTemplate`` — currently
// 0 matches each). Adding them now costs nothing today and avoids a
// silent under-count if JUnit5 lands later without this task being
// updated in the same PR.
//
// Per-line predicate (kept simple — line-level state machine instead
// of full Kotlin parser):
//
//   - trim().startsWith(<test annotation>)  — annotation is the first
//     token on the line (the common style: each annotation on its
//     own line above the method)
//   - && NOT startsWith("//")  — line comment
//   - && NOT startsWith("*")   — KDoc continuation line ("* @Test")
//
// Known limitation: multi-annotation lines like ``@JvmField @Test``
// where ``@Test`` is not the first token aren't counted. The project
// doesn't use that style today; if it ever does, this task will
// under-count and the baseline mismatch will surface the missed style
// for explicit decision.
val androidTestAnnotations = listOf(
    "@Test",
    "@ParameterizedTest",
    "@RepeatedTest",
    "@TestFactory",
    "@TestTemplate",
)

// Conceptual counter name: ``android_junit_test_method_count`` — explicitly
// names "annotation-based method count", not "runtime-collected test count".
// Parametrized JUnit5 expansions (when/if migrated) would still register as
// 1 method per ``@ParameterizedTest`` site, not N runtime instances. The
// counter measures source-level test method declarations; runtime test
// count is a different metric (would need ``gradle test --dry-run`` and
// parsing). Keep them mentally separate.

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

tasks.register("assertAndroidTestCountEqualsBaseline") {
    group = "verification"
    description = "ADR-0038 PR-Δ: assert Android JUnit @Test method-annotation " +
        "count exactly matches audit/test_count_baseline.txt (strict-equality + " +
        "UP-ratchet vs PR base baseline + bootstrap exception by data shape)."

    val baselineFile = rootProject.file("audit/test_count_baseline.txt")
    val testDir = file("src/test")
    inputs.file(baselineFile)
    inputs.dir(testDir)

    doLast {
        if (!baselineFile.exists()) {
            throw GradleException(
                "ADR-0038 PR-Δ: baseline file missing at ${baselineFile.absolutePath}. " +
                "Create it with a single integer (current Android JUnit @Test method count)."
            )
        }
        val currentBaseline = baselineFile.readText().trim().toInt()

        val actual = if (testDir.exists()) {
            fileTree(testDir).matching { include("**/*.kt") }.sumOf { file ->
                file.useLines { lines ->
                    lines.count { line ->
                        val trimmed = line.trim()
                        androidTestAnnotations.any { trimmed.startsWith(it) } &&
                            !trimmed.startsWith("//") &&
                            !trimmed.startsWith("*")
                    }
                }
            }
        } else {
            0
        }

        // Layer 1: strict equality (actual == current baseline). Both directions FAIL.
        if (actual != currentBaseline) {
            val diff = actual - currentBaseline
            val sign = if (diff > 0) "+" else ""
            throw GradleException(
                "ADR-0038 PR-Δ strict equality FAIL: actual=$actual " +
                "current_baseline=$currentBaseline ($sign$diff). Update " +
                "audit/test_count_baseline.txt in the SAME PR if intentional " +
                "(both directions FAIL — silent drift in either is a bug)."
            )
        }

        // Layer 2: UP ratchet — current baseline must be >= base baseline.
        // Bootstrap exception: if base baseline file doesn't exist (prep PR
        // is the first to introduce it), only strict equality applies.
        //
        // Base ref priority mirrors backend gate:
        //   GITHUB_BASE_REF env (PR CI sets to PR target branch)
        //   → XPJ_AUDIT_BASE_REF env (manual override)
        //   → "main" fallback (local dev).
        // Prefixed with origin/ if not already namespaced.
        // The CI runner sets GITHUB_BASE_REF to the empty string on push
        // events (not unset — non-null but empty). System.getenv() returns
        // "" not null in that case, so a naïve null-coalesce treats push
        // CI as PR CI and builds baseRef="origin/" → unreachable → FAIL.
        // Treat empty same as null for both ref selection and PR-context
        // detection. Matches backend gate's ``bool(os.environ.get(...))``
        // which naturally treats empty as falsy via Python truthiness.
        val explicitRef = System.getenv("GITHUB_BASE_REF")?.takeIf { it.isNotEmpty() }
            ?: System.getenv("XPJ_AUDIT_BASE_REF")?.takeIf { it.isNotEmpty() }
        val baseRef = when {
            explicitRef != null -> if (explicitRef.contains("/")) explicitRef else "origin/$explicitRef"
            // CI push event (GITHUB_SHA set, no PR base): the offline checkout fetches
            // heads into origin/*, so the live main is origin/main.
            !System.getenv("GITHUB_SHA").isNullOrEmpty() -> "origin/main"
            // Local dev: the `origin` remote is the dead GitHub mirror (stale), so read
            // the LIVE local main instead — avoids false ratchet failures.
            else -> "refs/heads/main"
        }
        val isPrCiContext = !System.getenv("GITHUB_BASE_REF").isNullOrEmpty()

        // Distinguish three states (parallels backend gate's tuple return):
        //   - refReachable=false: git itself can't see the base ref (shallow
        //     checkout, ref not fetched) → infra failure
        //     · PR CI: FAIL loudly
        //     · local: INFO-skip ratchet
        //   - refReachable=true, fileMissing=true: ref reachable but baseline
        //     file didn't exist at base → integral-bootstrap for this counter
        //     · skip ratchet (no value to compare); strict equality already
        //       enforced above
        //   - refReachable=true, fileMissing=false, baseBaseline=N: normal
        //     ratchet path
        val refReachable = try {
            val proc = ProcessBuilder("git", "rev-parse", "--verify", baseRef)
                .directory(rootProject.rootDir)
                .redirectErrorStream(true)
                .start()
            proc.waitFor(30, TimeUnit.SECONDS)
            proc.exitValue() == 0
        } catch (e: Exception) {
            false
        }

        if (!refReachable) {
            if (isPrCiContext) {
                throw GradleException(
                    "ADR-0038 PR-Δ: in PR CI but base ref '$baseRef' is unreachable. " +
                    "Possible: shallow checkout (need fetch-depth: 0 in CI workflow), " +
                    "or remote not fetched. Fix CI config; do NOT downgrade to " +
                    "strict-equality-only as a workaround."
                )
            }
            println(
                "ADR-0038 PR-Δ: Android count $actual matches current baseline " +
                "(base ref '$baseRef' unreachable — local dev, ratchet skipped)."
            )
            return@doLast
        }

        val baseBaseline: Int? = try {
            val proc = ProcessBuilder(
                "git", "show", "$baseRef:android/audit/test_count_baseline.txt"
            )
                .directory(rootProject.rootDir)
                .redirectErrorStream(false)
                .start()
            val output = proc.inputStream.bufferedReader().readText().trim()
            val finished = proc.waitFor(30, TimeUnit.SECONDS)
            if (finished && proc.exitValue() == 0 && output.isNotEmpty()) {
                output.toIntOrNull()
            } else {
                // File didn't exist at base (ref was reachable, so this is
                // legit "this counter is new in this PR"). Bootstrap.
                null
            }
        } catch (e: Exception) {
            null
        }

        if (baseBaseline == null) {
            // refReachable=true + baseBaseline=null → integral-bootstrap.
            // Strict equality already enforced above (actual == currentBaseline);
            // ratchet skipped because there's no base value to ratchet against.
            // Auto-extinguishes once the baseline file lands in main.
            println(
                "ADR-0038 PR-Δ: Android count $actual matches current baseline " +
                "(bootstrap — baseline file new in this PR; ratchet auto-engages " +
                "next PR after merge)."
            )
            return@doLast
        }

        if (currentBaseline < baseBaseline) {
            throw GradleException(
                "ADR-0038 PR-Δ ratchet FAIL: Android test count baseline at base=$baseBaseline, " +
                "at current PR=$currentBaseline (dropped by ${baseBaseline - currentBaseline}). " +
                "Tests should accumulate, not vanish. If this drop is intentional " +
                "(test consolidation, dead code removal with paired test removal), " +
                "document the rationale and get explicit sign-off — don't silently " +
                "lower the floor. Strict equality alone misses this when actuals dropped " +
                "in lockstep — UP-ratchet catches it."
            )
        }

        println(
            "ADR-0038 PR-Δ: Android test count $actual matches current baseline " +
            "(base=$baseBaseline; ratchet UP OK)."
        )
    }
}
