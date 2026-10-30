# Market Visit Android app

A small Android shell around the phone app at `/app` on the Market Visit Tracker.
All screens and data come from the server, so changes to `app/static/app.html` reach
every phone without a new APK. A new APK is only needed when something in this
`android/` folder changes.

## Getting the APK

Every push to `main` that touches `android/` builds the app on GitHub and publishes it at:

https://github.com/samansingh62-ux/market-visit-tracker-api/releases/download/android-latest/MarketVisit.apk

You can also run the **Android APK** workflow by hand from the repo's Actions tab.

## Installing on a phone

1. Open the link above on the phone (or send the APK file on WhatsApp).
2. Tap the downloaded file. Android asks to allow installing from that app (Chrome or WhatsApp): allow it once.
3. Open **Market Visit**, log in with your PIN, and allow location and camera when asked.

## Signing (optional, recommended before wide roll-out)

Without a signing key, each build is signed with a temporary key. Phones can install
any single build, but moving to a newer APK then needs the old app uninstalled first.
To make updates install over the top, add these repository secrets once
(Settings → Secrets and variables → Actions):

| Secret | Value |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | the `.jks` keystore file, base64-encoded |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | key alias |
| `ANDROID_KEY_PASSWORD` | key password |

Create a keystore with:

```
keytool -genkeypair -v -keystore marketvisit.jks -alias marketvisit -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 marketvisit.jks
```

Keep the `.jks` file and passwords safe and out of this public repository.
