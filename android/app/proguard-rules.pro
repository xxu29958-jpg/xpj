# v1.1 Batch 2: R8 keep rules for the ticketbox release build.
#
# The release build now runs R8 with minifyEnabled + shrinkResources, so
# anything that's reflected against (Moshi DTOs, Retrofit interfaces,
# Room entities, Compose tooling) needs an explicit keep rule.
#
# Conservative — we keep more than strictly needed so a release crash
# never traces back to a missing rule. APK size impact stays modest.

# Keep line numbers for crash reports.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# --- Kotlin -----------------------------------------------------------
-keepattributes Signature,InnerClasses,EnclosingMethod
-keep class kotlin.Metadata { *; }
-dontwarn kotlin.**
-keep class kotlin.coroutines.Continuation { *; }

# --- Moshi (Kotlin codegen) -------------------------------------------
# Moshi codegen generates *_JsonAdapter classes alongside each
# @JsonClass(generateAdapter = true) DTO. R8 finds them via the
# generated lookup, but be defensive: keep both DTOs and adapters.
-keep,allowobfuscation @com.squareup.moshi.JsonClass class **
-keep class **_JsonAdapter { *; }
-keepclassmembers class * {
    @com.squareup.moshi.* <fields>;
    @com.squareup.moshi.* <methods>;
}

# --- Retrofit ---------------------------------------------------------
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class retrofit2.Response
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}
# Service interfaces are referenced only by Retrofit's dynamic proxy.
-keep interface com.ticketbox.**.api.** { *; }

# --- OkHttp -----------------------------------------------------------
-dontwarn okhttp3.**
-dontwarn okio.**

# --- Room -------------------------------------------------------------
-keep class * extends androidx.room.RoomDatabase { *; }
-keep @androidx.room.Entity class *
-keep @androidx.room.Dao class *
-keep @androidx.room.Database class *
-keepclassmembers class * {
    @androidx.room.* <methods>;
}

# --- Compose ----------------------------------------------------------
# Compose uses reflection for tooling previews. The default
# proguard-android-optimize file already covers most of it; reinforce
# the public API surface so previews still render in IDE.
-keep,allowobfuscation class androidx.compose.ui.tooling.** { *; }

# --- App-specific -----------------------------------------------------
# Keep classes referenced by name from the manifest. R8's default rules
# already include this for android:name attributes, but listing them
# explicitly makes intent clear in code review.
-keep class com.ticketbox.TicketboxApplication { *; }
-keep class com.ticketbox.MainActivity { *; }
-keep class com.ticketbox.notification.TicketboxNotificationListenerService { *; }

# BuildConfig is read by reflection in some debug surfaces.
-keep class com.ticketbox.BuildConfig { *; }

# Moshi DTOs live under .net.dto / .data — keep them all to avoid a
# whole class of "field name was renamed" runtime crashes.
-keep class com.ticketbox.**.dto.** { *; }
-keep class com.ticketbox.**.model.** { *; }
