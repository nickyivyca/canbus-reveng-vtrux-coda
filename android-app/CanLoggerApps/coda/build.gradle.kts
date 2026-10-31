plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.reverseit.coda"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.reverseit.coda"
        // 26 is required by the :display module (shared ColorBandSlider/StatusWord
        // widgets). Harmless for the A007 head unit, which runs Android 12.
        minSdk = 26
        targetSdk = 34
        versionCode = 3
        versionName = "1.2"
    }

    signingConfigs {
        getByName("debug") {
            storeFile = rootProject.extra["projectKeystore"] as File  // root build.gradle.kts
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // The project keystore, as debug builds use: car and phone loads are release builds
            // (Change 15) and must install over the debug builds already there, keeping their data.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = libs.versions.composeCompiler.get()
    }
}

dependencies {
    implementation(project(":cancore"))
    implementation(project(":tpms"))
    implementation(project(":display"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.lifecycle.viewmodel.ktx)
    implementation(libs.lifecycle.runtime.ktx)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    // Explicit (was transitive): HorizontalPager for the page-2 swipe.
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.runtime)
    testImplementation("junit:junit:4.13.2")
}
