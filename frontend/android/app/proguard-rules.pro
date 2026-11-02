# -----------------------------------------------------------------------------
# flutter_local_notifications uses Gson to (de)serialize scheduled
# notifications. R8's release minification strips Gson's generic type
# information, which makes ScheduledNotificationReceiver crash with
# "java.lang.RuntimeException: Missing type parameter." when a scheduled
# notification fires. Keep the required Gson reflection info.
# -----------------------------------------------------------------------------
-keepattributes Signature
-keepattributes *Annotation*

-keep class com.google.gson.reflect.TypeToken { *; }
-keep class * extends com.google.gson.reflect.TypeToken
-keep class com.google.gson.stream.** { *; }
-dontwarn com.google.gson.**
