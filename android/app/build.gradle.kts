import java.util.Properties

val ticketboxVersionCode = 90000
val ticketboxVersionName = "0.9.0a1"
val ticketboxRequireLocalUnlock = false

// Server URL precedence:
//   1. ENV: TICKETBOX_SERVER_URL
//   2. local.properties: ticketbox.serverUrl=...
//   3. fallback: https://api.example.com (placeholder; replace before publishing)
val ticketboxServerUrl: String = run {
    val envUrl: String? = System.getenv("TICKETBOX_SERVER_URL")
    if (!envUrl.isNullOrBlank()) return@run envUrl.trim()
    val propsFile = rootProject.file("local.properties")
    if (propsFile.exists()) {
        val props = Properties()
        propsFile.inputStream().use { stream -> props.load(stream) }
        val v: String? = props.getProperty("ticketbox.serverUrl")
        if (!v.isNullOrBlank()) return@run v.trim()
    }
    "https://api.example.com"
}

plugins {
    alias(libs.plugins.android.application)
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
            buildConfigField("Boolean", "REQUIRE_LOCAL_UNLOCK", ticketboxRequireLocalUnlock.toString())
        }
        release {
            isDebuggable = false
            isMinifyEnabled = false
            buildConfigField("Boolean", "REQUIRE_LOCAL_UNLOCK", ticketboxRequireLocalUnlock.toString())
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

    implementation(libs.okhttp)
    implementation(libs.okhttp.logging.interceptor)
    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.moshi)
    implementation(libs.moshi.kotlin)

    implementation(libs.androidx.biometric)
    implementation(libs.coroutines.android)
    implementation(libs.vico.compose.m3)

    testImplementation(libs.kotlin.test)
    testImplementation(libs.coroutines.test)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
