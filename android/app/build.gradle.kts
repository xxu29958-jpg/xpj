val ticketboxVersionCode = 1
val ticketboxVersionName = "0.1.0"

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

        resValue("string", "app_version_name", ticketboxVersionName)
        resValue("integer", "app_version_code", ticketboxVersionCode.toString())
        buildConfigField("Boolean", "SHOW_ADVANCED_TOOLS", "false")
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"https://api.zen70.cn\"")
        manifestPlaceholders["appLabel"] = "小票夹"
    }

    flavorDimensions += "audience"
    productFlavors {
        create("gray") {
            dimension = "audience"
            manifestPlaceholders["appLabel"] = "小票夹"
            buildConfigField("Boolean", "SHOW_ADVANCED_TOOLS", "false")
        }
        create("internal") {
            dimension = "audience"
            applicationIdSuffix = ".internal"
            versionNameSuffix = "-internal"
            manifestPlaceholders["appLabel"] = "小票夹内部版"
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
        release {
            isDebuggable = false
            isMinifyEnabled = false
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

    testImplementation(libs.kotlin.test)
    testImplementation(libs.coroutines.test)
}
