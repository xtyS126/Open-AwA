plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    // TODO: Chaquopy 17.0.0 与 Gradle 9 + AGP 9 兼容性待验证，暂未集成
    // 集成时取消下一行注释，并恢复下方 chaquopy {} 配置块
    // alias(libs.plugins.chaquopy)
}

android {
    namespace = "com.xtys126.open_awa"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.xtys126.open_awa"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // 支持 ndk 过滤，减少 APK 体积（仅保留 arm64-v8a 与 x86_64，覆盖真机与模拟器）
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
}

// AGP 9 + Kotlin 2.0+ 使用 kotlin { compilerOptions } 替代 kotlinOptions
kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
    }
}

// Chaquopy 内嵌 Python 运行时配置（暂未集成）
// 文档：https://chaquo.com/chaquopy/doc/current/android.html
// TODO: Chaquopy 17.0.0 + Gradle 9 + AGP 9 兼容性待验证
// 集成时取消上方 plugins 块中的 chaquopy 插件注释，并恢复以下配置块：
/*
chaquopy {
    defaultConfig {
        // Python 版本：3.12 与 backend/ 的 3.11+ 兼容（pure Python）
        version = "3.12"

        // 构建用 Python 命令（Windows 下用 py -3.12）
        buildPython("py", "-3.12")

        // 内嵌后端 pip 依赖（Chaquopy 兼容的 pure-Python wheel）
        // 注意：Chaquopy 仅支持 pure-Python wheel 或预编译的 Android ABI wheel
        // 不兼容依赖（C 扩展/平台相关）已剔除：
        //   - torch/torchaudio/torchvision: 体积过大且无 Android ABI
        //   - pywinpty: Windows 专属
        //   - qdrant-client 嵌入式模式: 依赖 Rust 编译
        //   - tree-sitter/tree-sitter-languages: C 扩展
        //   - bcrypt: C 扩展，passlib 改用 pbkdf2_sha256 纯 Python 实现
        //   - pydantic-core: Rust C 扩展，Chaquopy 无法编译，降级到 pydantic 1.x
        pip {
            // Web 框架：fastapi 0.99.1 是最后兼容 pydantic v1 的版本
            install("fastapi==0.99.1")
            // 不带 [standard]，避免 uvloop/httptools C 扩展
            install("uvicorn==0.23.2")
            install("python-multipart==0.0.6")
            // ORM 与配置
            install("sqlalchemy==1.4.54")
            // pydantic 1.10.x 纯 Python，无 pydantic-core 依赖
            // 1.10.22+ 修复了 Python 3.12 兼容性，1.10.24 是最后一个 1.10.x 版本
            install("pydantic==1.10.24")
            // 认证（passlib 不带 [bcrypt]，使用 pbkdf2_sha256 纯 Python 后端）
            install("passlib==1.7.4")
            install("PyJWT==2.8.0")
            // 邮箱校验（pydantic v1 EmailStr 依赖）
            install("email-validator==2.1.0")
            // 日期时间工具
            install("python-dateutil==2.8.2")
            // python-jose（虽然当前未直接使用，预留兼容）
            install("python-jose==3.3.0")
            // 日志
            install("loguru")
        }

        // 内嵌 Python 源码目录（Chaquopy 17.0 Kotlin DSL：用 maybeCreate 兼容创建 source set）
        sourceSets {
            maybeCreate("main").srcDir("src/main/python")
        }
    }
}
*/

dependencies {
    // AndroidX 基础
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)

    // Compose BOM 统一管理 Compose 库版本
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.extended)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)
    debugImplementation(libs.androidx.compose.ui.tooling)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.coroutines.core)

    // Ktor HTTP 客户端
    implementation(libs.ktor.client.core)
    implementation(libs.ktor.client.cio)
    implementation(libs.ktor.client.content.negotiation)
    implementation(libs.ktor.serialization.kotlinx.json)
    implementation(libs.ktor.client.logging)

    // Kotlinx Serialization
    implementation(libs.kotlinx.serialization.json)

    // DataStore Preferences
    implementation(libs.androidx.datastore.preferences)

    // Chaquopy Java SDK（17.0.0 在 AGP 9 下未自动添加，需显式声明）
    // 包含 com.chaquo.python.Python 与 com.chaquo.python.android.AndroidPlatform
    // 排除 annotations-java5：与项目已有的 org.jetbrains:annotations:23.0.0 类冲突
    implementation("com.chaquo.python.runtime:chaquopy_java:17.0.0") {
        exclude(group = "org.jetbrains", module = "annotations-java5")
    }

    // 测试
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
}
