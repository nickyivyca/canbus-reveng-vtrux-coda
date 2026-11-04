# Local paths for this clone

This is the template for `local-paths.md`, which is gitignored and filled in
separately in each clone with the local paths this clone's builds and tools
use. If `local-paths.md` doesn't exist, copy this file to it. If you see this
text in `local-paths.md`, ask the user what information belongs here, write
it in, and delete this paragraph. Never commit `local-paths.md`; it stays
gitignored.

## Machine

<!-- The hostname, and the Python command to use on it. Source:
../python-executables-reference.md -->

## Builds

<!-- The JDK for Gradle (JAVA_HOME), the Android SDK (ANDROID_HOME), adb and
apksigner, and the gradlew invocation that works on this machine. Source:
../android-app/android-tools-reference.md -->

## Secrets and environment variables

<!-- This machine's REVERSE_IT_DIR, and where reverseit.secretsDir is set
(normally ~/.gradle/gradle.properties, pointing at
../android-app/secrets). Never write the token or the keystore
password here. -->

## Other clones

<!-- Any other clone this session works with, such as the public repo
(canbus-reveng-vtrux-coda) for exports. -->
