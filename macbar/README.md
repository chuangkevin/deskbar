# Deskbar Menu Bar

macOS menu bar app for showing the same usage data served by deskbar `GET /api/usage`.

## Requirements

- macOS 14 or newer
- Swift command line tools
- No Xcode project is required

## Build

```sh
swift build --configuration release
```

To create the `.app` bundle:

```sh
bash build-app.sh
```

The script writes `.build/DeskbarMenuBar.app` and signs it with ad-hoc signing.

## Configure URL

The app reads `UserDefaults` key `deskbarBaseURL`.

Default:

```text
http://100.98.35.59:8080
```

You can change it from the menu using `設定 URL…`. The app fetches again after applying the new URL.

## Launch At Login

Use the `登入時啟動` toggle in the menu. It uses `SMAppService.mainApp`.

## Test

```sh
swift test
```
