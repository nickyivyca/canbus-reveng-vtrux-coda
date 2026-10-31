plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
}

// Coda indirect TPMS, including the GPS common-mode channel. Only :coda depends on this module, so
// none of it -- the code, the location permission, the GPS service -- reaches any other app.
android {
    namespace = "com.reverseit.tpms"
    compileSdk = 34

    defaultConfig {
        minSdk = 26
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
    implementation(libs.kotlinx.coroutines.android)
    testImplementation("junit:junit:4.13.2")
    // android.jar's org.json is a stub that throws under JVM tests; the real one for the tests.
    // Not shipped -- the device has its own.
    testImplementation("org.json:json:20231013")
}
