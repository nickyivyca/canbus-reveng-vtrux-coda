import java.util.Properties

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
}

// Secrets stay out of the source tree (notes/plans/private-git-migration.md step 1): a folder named
// by the Gradle property `reverseit.secretsDir`, set once per machine in ~/.gradle/gradle.properties.
// The modules read the results as rootProject.extra["projectKeystore"] and ["syncToken"].
val secretsDir: File? = (findProperty("reverseit.secretsDir") as String?)
    ?.takeIf { it.isNotBlank() }?.let { file(it) }

// The keystore that signs every app, release car builds included (Change 15). The only fallback is
// the in-tree copy (there until the cutover), never ~/.android/debug.keystore: an APK signed with
// another key will not install over the car's apps without an uninstall, which wipes their data.
// With neither present this names the expected path anyway, so signing fails ("Keystore file ...
// not found") instead of quietly using another key.
extra["projectKeystore"] =
    listOfNotNull(secretsDir?.resolve("debug.keystore"), file("debug.keystore")).firstOrNull { it.isFile }
        ?: (secretsDir ?: file("secrets-not-configured")).resolve("debug.keystore")

fun readProps(f: File?) = Properties().apply { if (f != null && f.isFile) f.inputStream().use { load(it) } }

extra["syncToken"] = readProps(secretsDir?.resolve("android.properties")).getProperty("sync.token")
    ?: readProps(file("local.properties")).getProperty("sync.token")
    ?: "DEV_TOKEN_UNSET"
