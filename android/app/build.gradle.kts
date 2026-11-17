plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 버전은 데스크톱 프로그램과 같은 값을 쓴다.
val appVersion: String = Regex("__version__ = \"(.+?)\"")
    .find(rootProject.file("../molcom/__init__.py").readText())!!.groupValues[1]
val versionParts = appVersion.split(".").map { it.toInt() }

android {
    namespace = "io.github.ehgnsk.molcom"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.ehgnsk.molcom"
        minSdk = 26
        targetSdk = 34
        versionCode = versionParts[0] * 10000 + versionParts[1] * 100 + versionParts[2]
        versionName = appVersion
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    signingConfigs {
        // 저장소에 들어 있는 공개 키. 빌드마다 서명이 같아야 덮어쓰기 설치가 된다.
        create("shared") {
            storeFile = rootProject.file("molcom.keystore")
            storePassword = "android"
            keyAlias = "molcom"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("shared")
        }
        debug {
            signingConfig = signingConfigs.getByName("shared")
        }
    }

    // 얼굴 모델은 데스크톱 프로그램과 같은 파일을 쓴다.
    sourceSets.getByName("main").assets.srcDir(rootProject.file("../models"))
    androidResources {
        noCompress += "onnx"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")
    implementation("androidx.lifecycle:lifecycle-livedata-ktx:2.8.4")
    implementation("androidx.camera:camera-core:1.3.4")
    implementation("androidx.camera:camera-camera2:1.3.4")
    implementation("androidx.camera:camera-lifecycle:1.3.4")
    implementation("androidx.exifinterface:exifinterface:1.3.7")
    implementation("org.opencv:opencv:4.10.0")
}
