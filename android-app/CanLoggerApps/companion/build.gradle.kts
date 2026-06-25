plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.reverseit.companion"
    compileSdk = 34

    defaultConfig {
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    flavorDimensions += "vehicle"
    productFlavors {
        create("coda") {
            dimension = "vehicle"
            applicationId = "com.reverseit.codacompanion"
            resValue("string", "app_name", "Coda Companion")
            buildConfigField("String", "VEHICLE", "\"coda\"")
            buildConfigField("String", "DEFAULT_SSID", "\"Coda\"")
        }
        create("vtrux") {
            dimension = "vehicle"
            applicationId = "com.reverseit.vtruxcompanion"
            resValue("string", "app_name", "Vtrux Companion")
            buildConfigField("String", "VEHICLE", "\"vtrux\"")
            buildConfigField("String", "DEFAULT_SSID", "\"Vtrux\"")
        }
    }

    signingConfigs {
        getByName("debug") {
            storeFile = rootProject.file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
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
    buildFeatures {
        compose = true
        buildConfig = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = libs.versions.composeCompiler.get()
    }
}

dependencies {
    implementation(project(":cancore"))
    "vtruxImplementation"(project(":display"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.lifecycle.viewmodel.ktx)
    implementation(libs.lifecycle.runtime.ktx)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.material3)
    implementation(libs.compose.runtime)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.documentfile)
}
