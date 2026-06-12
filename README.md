# ScreenDrop

Send screenshots from your Windows laptop to your tablet instantly — no cloud, no app install, works over local WiFi.

## How it works

```
Win+Shift+S (screenshot)
      ↓
clipboard_watcher.py detects new image
      ↓
POSTs to Go server running on your laptop
      ↓
Server broadcasts via WebSocket
      ↓
Browser tab on tablet receives image instantly
```

## Setup

### 1. Start the Go server

```bash
go mod tidy
go run main.go
```

You'll see:
```
ScreenDrop running on http://0.0.0.0:8080
Open http://<your-laptop-ip>:8080 on your tablet
```

### 2. Find your laptop's local IP

Open PowerShell:
```
ipconfig
```
Look for `IPv4 Address` under your WiFi adapter — something like `192.168.1.42`

### 3. Open on your tablet

Open a browser on your tablet and go to:
```
http://192.168.1.42:8080
```
Keep this tab open.

### 4. Start the clipboard watcher

In a separate terminal on your laptop:
```bash
pip install pillow requests pywin32
python clipboard_watcher.py
```

### 5. Use it

Press `Win+Shift+S`, select any area — it appears on your tablet in under a second.

Tap **Save image** on the tablet to download it into your notes app.

## Project structure

```
screendrop/
  main.go                  ← server entry point, routes
  handlers/
    handlers.go            ← WebSocket hub, upload handler, image store
  static/
    index.html             ← tablet UI (served by Go)
  clipboard_watcher.py     ← Windows clipboard watcher
  go.mod
```

## Why this stack

- **No DB** — latest image held in memory, that's all we need
- **WebSocket** — push to tablet the moment image arrives, no polling
- **Base64 encoding** — image sent inline in the WebSocket message, no second request needed
- **In-memory store** — if tablet connects after upload, it still gets the latest image immediately
- **gorilla/websocket** — handles WebSocket protocol, Go's stdlib doesn't include it
