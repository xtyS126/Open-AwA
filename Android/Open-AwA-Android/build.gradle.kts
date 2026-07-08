// Top-level build file where you can add configuration options common to all sub-projects/modules.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    // Chaquopy 内嵌 Python 运行时插件（声明在项目级，由 app 模块应用）
    id("com.chaquo.python") version libs.versions.chaquopy apply false
}
