pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "CanLoggerApps"
include(":cancore")
include(":display")
include(":coda")
include(":tpms")
include(":vtrux")
include(":companion")
include(":p914")
