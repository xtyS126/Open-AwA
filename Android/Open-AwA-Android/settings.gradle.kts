pluginManagement {
    repositories {
        maven{url=uri("https://maven.aliyun.com/repository/google")}
        maven{url=uri("https://maven.aliyun.com/repository/central")}
        // Chaquopy 内嵌 Python 运行时插件仓库
        maven{url=uri("https://chaquo.com/chaquopy/maven/")}
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven{url=uri("https://maven.aliyun.com/repository/google")}
        maven{url=uri("https://maven.aliyun.com/repository/central")}
        // Chaquopy 内嵌 Python 运行时插件仓库
        maven{url=uri("https://chaquo.com/chaquopy/maven/")}
        google()
        mavenCentral()
    }
}

rootProject.name = "Open-AwA"
include(":app")
 