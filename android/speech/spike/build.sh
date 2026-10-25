#!/bin/sh
# Builds the throwaway spike APK into ./out (gitignored by caller). Needs ~/Library/Android/sdk.
set -e
cd "$(dirname "$0")"
SDK=~/Library/Android/sdk; BT=$SDK/build-tools/36.0.0; JAR=$SDK/platforms/android-36/android.jar
[ -f assets/hello.wav ] || { mkdir -p assets; say -o out.aiff "hello world. this is a test of the speech recognizer" && afconvert -f WAVE -d LEI16@16000 -c 1 out.aiff assets/hello.wav && rm out.aiff; }
rm -rf out; mkdir -p out/classes out/dex
javac -source 17 -target 17 -cp "$JAR" -d out/classes src/com/gettarka/speechspike/*.java
"$BT/d8" --min-api 34 --lib "$JAR" --output out/dex $(find out/classes -name '*.class')
"$BT/aapt2" link -o out/base.apk -I "$JAR" --manifest AndroidManifest.xml -A assets
(cd out/dex && zip -q ../base.apk classes.dex)
"$BT/zipalign" -f 4 out/base.apk out/aligned.apk
[ -f out/../debug.keystore ] || keytool -genkeypair -keystore debug.keystore -storepass android -keypass android -alias d -keyalg RSA -dname CN=spike -validity 365 >/dev/null 2>&1
"$BT/apksigner" sign --ks debug.keystore --ks-pass pass:android --out out/spike.apk out/aligned.apk
echo built out/spike.apk
