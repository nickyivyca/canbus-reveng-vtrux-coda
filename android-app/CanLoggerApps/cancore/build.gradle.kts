import java.util.Properties

plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
val syncToken: String = localProps.getProperty("sync.token") ?: "DEV_TOKEN_UNSET"

android {
    namespace = "com.reverseit.cancore"
    compileSdk = 34

    defaultConfig {
        minSdk = 21
        buildConfigField("String", "SYNC_TOKEN", "\"$syncToken\"")
    }

    buildFeatures {
        buildConfig = true
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
    implementation(libs.androidx.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.lifecycle.viewmodel.ktx)
    implementation(libs.lifecycle.runtime.ktx)
    implementation(libs.nanohttpd)
    implementation(libs.okhttp)
    implementation(libs.java.websocket)
    testImplementation("junit:junit:4.13.2")
}
