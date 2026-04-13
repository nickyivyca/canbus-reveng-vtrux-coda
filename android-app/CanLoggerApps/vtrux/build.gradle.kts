plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.reverseit.vtrux"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.reverseit.vtrux"
        minSdk = 21
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
}

dependencies {
    implementation(project(":cancore"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.lifecycle.runtime.ktx)
    // activity-compose is listed here because it transitively supplies androidx.activity:activity-ktx,
    // which provides ComponentActivity.registerForActivityResult. No Compose UI is used.
    implementation(libs.activity.compose)
}
