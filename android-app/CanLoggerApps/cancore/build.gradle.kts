plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

// From the secrets folder, else local.properties, else DEV_TOKEN_UNSET: root build.gradle.kts.
val syncToken = rootProject.extra["syncToken"] as String

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
    // LogFileServerTest runs the real server on the JVM: android.util.Log becomes a no-op there.
    testOptions {
        unitTests.isReturnDefaultValues = true
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
    // android.jar's org.json is a stub that throws under JVM tests; the real one for the tests.
    testImplementation("org.json:json:20231013")
}
