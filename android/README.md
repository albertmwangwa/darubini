# Darubini for Android

The native phone app for Darubini, in Kotlin and Jetpack Compose. It does what the web page at `darubini serve` does: photograph fields or record a pan through the eyepiece, see the running count and when to stop, then watch the Muse Spark agent check the slide and write the report in English or Kiswahili.

All counting happens on the server. The app talks to the same `/v1/sessions` API as the web page.

## Design

The screens were sketched in [M3E Canvas](https://github.com/albertmwangwa/m3e-canvas) first:

- [design/darubini.m3e.json](design/darubini.m3e.json) is the design document. Open it in M3E Canvas with **Open project**.
- [design/canvas-link.txt](design/canvas-link.txt) is a share link that opens the same design in the browser.

The design has five screens:

| Screen | What it does |
| --- | --- |
| Start | Picks English or Kiswahili and starts a slide |
| Capture | Photo or pan, running counts, WBC progress, overlay, next step |
| Agent | The agent's tool calls, live |
| Report | Density, audit warning, agent summary, excluded fields, share |
| Settings | Server address, connection test, report language |

**Visual design.** Since 2 Nov the app uses the design language of the *Credit Design* Figma system, adopted as Darubini's own:

- Plus Jakarta Sans;
- deep green `#215732` with lime accents;
- white cards with hairline borders;
- pill buttons;
- status shown as colour plus a word;
- metric tiles, notices, a timeline and a bottom action bar holding the screen's one decision.

Tokens, type scale and the component map are in [design/DESIGN.md](design/DESIGN.md).

## Build

You need Android Studio, or the Android SDK with JDK 17 or newer. Open this `android/` folder in Android Studio, or run:

```bash
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:testDebugUnitTest    # JSON parsing and API client tests
```

Versions:

- `compileSdk` and `targetSdk` are 37, and `minSdk` is 26 (Android 8).
- Material 3 is pinned to `1.5.0-beta02`, because the Expressive components are public only from that line.

## Run

1. Start the server on a laptop on the same Wi-Fi: `darubini serve --host 0.0.0.0`.
2. In the app, open **Settings** and enter the laptop's address, for example `http://192.168.1.20:8000`. Tap **Test connection**.
   - The emulator's default, `http://10.0.2.2:8000`, reaches a server on the host machine.
3. Tap **Start a new slide** and capture fields:
   - **Photograph field** uses the phone's camera app.
   - **Record a pan** records up to 8 s of video.
   - The gallery button in the top bar sends an existing photo or clip.
4. Tap **Finish slide** when the banner says the count is complete.

Notes:

- Photos are shrunk to 2,048 px and sent as JPEG at quality 85, the same as the web page.
- The server refuses clips over 60 MB.
- Plain HTTP is allowed because the server runs on the local network.
