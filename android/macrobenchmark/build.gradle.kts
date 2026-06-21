import com.android.build.api.dsl.ManagedVirtualDevice

// issue #64 A1: Baseline Profile generation + cold-start measurement module.
//
// This is a `com.android.test` module — it builds a separate test APK that drives
// the :app build it targets. It produces the Baseline Profile (consumed by :app's
// `baselineProfile` configuration) and hosts the StartupBenchmark used to compare
// cold-start TTID before/after (A1 acceptance #1). Kotlin compilation comes from
// AGP's built-in Kotlin, same as :app (no kotlin-android plugin is applied anywhere
// in this project).
plugins {
    alias(libs.plugins.android.test)
    alias(libs.plugins.androidx.baselineprofile)
}

android {
    namespace = "com.ticketbox.macrobenchmark"
    compileSdk = 36

    defaultConfig {
        // Baseline Profile collection + Macrobenchmark need an API 28+ device.
        minSdk = 28
        targetSdk = 36
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // Mirror :app's `audience` flavor dimension. Without this the baselineprofile
    // plugin cannot resolve a matching :app variant and sync fails with
    // "unable to find matching variant of project :app".
    flavorDimensions += "audience"
    productFlavors {
        create("gray") { dimension = "audience" }
        create("internal") { dimension = "audience" }
    }

    targetProjectPath = ":app"

    // A Gradle-managed AVD so generation is a single command and needs no manual
    // device wiring. AOSP image — Baseline Profile collection needs the elevated
    // shell perms that the Google-APIs images lock down.
    testOptions {
        managedDevices {
            allDevices {
                create<ManagedVirtualDevice>("pixel6Api34") {
                    device = "Pixel 6"
                    apiLevel = 34
                    systemImageSource = "aosp"
                }
            }
        }
    }
}

// Producer side: where to run the generator. Default to the managed AVD so the
// `:app:generate<Variant>BaselineProfile` command is self-contained; flip
// useConnectedDevices=true to drive an attached phone instead.
baselineProfile {
    managedDevices += "pixel6Api34"
    useConnectedDevices = false
}

dependencies {
    implementation(libs.junit)
    implementation(libs.androidx.test.ext.junit)
    implementation(libs.androidx.test.uiautomator)
    implementation(libs.androidx.benchmark.macro.junit4)
}
