# 官方资料与依赖来源

本项目优先使用官方文档和一手元数据。社区帖子只用于启发，不覆盖官方文档、本项目工程规范和关键决策。

## 后端

- Python `venv`：https://docs.python.org/3/library/venv.html
- pip requirements files：https://pip.pypa.io/en/stable/reference/requirements-file-format/
- FastAPI request files / `UploadFile` / `File`：https://fastapi.tiangolo.com/tutorial/request-files/
- FastAPI error handling / exception handlers：https://fastapi.tiangolo.com/tutorial/handling-errors/
- FastAPI bigger applications / `APIRouter`：https://fastapi.tiangolo.com/tutorial/bigger-applications/
- FastAPI testing / `TestClient`：https://fastapi.tiangolo.com/tutorial/testing/
- FastAPI testing dependency overrides：https://fastapi.tiangolo.com/advanced/testing-dependencies/
- SQLAlchemy ORM 2.0：https://docs.sqlalchemy.org/en/20/orm/
- SQLAlchemy SQLite dialect：https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
- pytest 文档：https://docs.pytest.org/en/stable/
- pytest PyPI 元数据：https://pypi.org/project/pytest/
- httpx PyPI 元数据：https://pypi.org/project/httpx/
- Pillow PyPI 元数据：https://pypi.org/project/pillow/
- Pillow 12.2.0 release notes：https://pillow.readthedocs.io/en/stable/releasenotes/12.2.0.html
- Pillow image file formats：https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html

## Android

- Android app architecture：https://developer.android.com/topic/architecture
- Android UI layer / UDF and state holders：https://developer.android.com/topic/architecture/ui-layer
- Android data layer：https://developer.android.com/topic/architecture/data-layer
- Jetpack Compose state hoisting：https://developer.android.com/develop/ui/compose/state-hoisting
- Android `BitmapFactory`：https://developer.android.com/reference/android/graphics/BitmapFactory
- Room：https://developer.android.com/training/data-storage/room
- Room DAO：https://developer.android.com/training/data-storage/room/accessing-data
- Room `@Upsert` API：https://developer.android.com/reference/androidx/room/Upsert
- Room `@Index` API：https://developer.android.com/reference/androidx/room/Index
- Room `@Transaction` API：https://developer.android.com/reference/androidx/room/Transaction
- BiometricPrompt：https://developer.android.com/identity/sign-in/biometric-auth
- Android Keystore：https://developer.android.com/privacy-and-security/keystore
- Android backup and data extraction rules：https://developer.android.com/about/versions/12/backup-restore
- Android Storage Access Framework：https://developer.android.com/guide/topics/providers/document-provider
- Android Activity Result APIs：https://developer.android.com/training/basics/intents/result
- Android `ActivityResultContracts.CreateDocument`：https://developer.android.com/reference/androidx/activity/result/contract/ActivityResultContracts.CreateDocument
- Android 真机运行与调试：https://developer.android.com/studio/run/device
- Android Debug Bridge：https://developer.android.com/tools/adb
- Gradle Java testing / JUnit Platform：https://docs.gradle.org/current/userguide/java_testing.html
- Kotlin `kotlin.test`：https://kotlinlang.org/api/core/kotlin-test/

## Windows

- `schtasks create`：https://learn.microsoft.com/windows-server/administration/windows-commands/schtasks-create
- PowerShell character encoding：https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_character_encoding

## CI

- actions/checkout releases：https://github.com/actions/checkout/releases
- actions/setup-python releases：https://github.com/actions/setup-python/releases
- actions/setup-java releases：https://github.com/actions/setup-java/releases
- actions/upload-artifact releases：https://github.com/actions/upload-artifact/releases
- GitHub hosted runners：https://docs.github.com/actions/using-github-hosted-runners/about-github-hosted-runners

## 联调与部署

- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Cloudflare Tunnel 概览：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Apple 快捷指令“获取 URL 内容”：https://support.apple.com/guide/shortcuts/use-the-get-contents-of-url-action-apd58d46713f/ios

## Android 依赖元数据

依赖版本升级必须查询官方 Maven 元数据，避免使用过时库、alpha/beta 弱依赖或凭记忆升级。

- AndroidX Maven：https://dl.google.com/dl/android/maven2/
- Maven Central：https://repo1.maven.org/maven2/
- Maven repository metadata：https://maven.apache.org/repositories/metadata.html
- PyPI JSON API：https://docs.pypi.org/api/json/
- Android SDK packages / sdkmanager：https://developer.android.com/tools/sdkmanager
- Gradle 9.4.1 release notes：https://docs.gradle.org/9.4.1/release-notes.html
- Room runtime metadata：https://dl.google.com/dl/android/maven2/androidx/room/room-runtime/maven-metadata.xml
- Compose BOM metadata：https://dl.google.com/dl/android/maven2/androidx/compose/compose-bom/maven-metadata.xml
- Android Gradle Plugin metadata：https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/maven-metadata.xml
- Kotlin Compose plugin metadata：https://repo1.maven.org/maven2/org/jetbrains/kotlin/plugin/compose/org.jetbrains.kotlin.plugin.compose.gradle.plugin/maven-metadata.xml
- KSP Gradle plugin metadata：https://repo1.maven.org/maven2/com/google/devtools/ksp/com.google.devtools.ksp.gradle.plugin/maven-metadata.xml
- Retrofit metadata：https://repo1.maven.org/maven2/com/squareup/retrofit2/retrofit/maven-metadata.xml
- OkHttp metadata：https://repo1.maven.org/maven2/com/squareup/okhttp3/okhttp/maven-metadata.xml
