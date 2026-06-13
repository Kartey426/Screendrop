# ScreenDrop

A local network screenshot sharing tool. Take a screenshot on your laptop, see it instantly on your tablet. No cloud, no accounts, no nonsense — just your WiFi.

## What it does

You copy a screenshot with `Win+Shift+S`, it shows up on your tablet in real time. That's it. Useful when you want a second screen for reference material, want to share something with someone next to you, or just don't want to AirDrop / email yourself things.

- **Real time** — screenshots appear on the tablet the moment you copy them
- **Gallery view** — keeps the last 20 screenshots in a scrollable grid, click any to expand
- **Reconnect-aware** — if the tablet loses connection it picks up where it left off, no duplicate images
- **Token secured** — access is gated behind a QR code you scan on first connect, no one else on the network can just open it

## How it works

Three pieces running together:

- **Go server** — runs on your laptop, handles WebSocket connections and image storage
- **Clipboard watcher** — watches your clipboard for new screenshots and posts them to the server
- **Tablet UI** — a browser page that connects via WebSocket and displays images as they arrive

Everything stays on your local network. Nothing leaves your machine.

## Setup

### Requirements

- Go 1.21+
- Both devices on the same WiFi network

### Run it

```bash
git clone https://github.com/Kartey426/Screendrop
cd Screendrop
go run .
```

On startup you'll see a QR code printed in the terminal and a token URL like:

```
http://192.168.x.x:8080?token=abc123...
```

Open your tablet's camera, scan the QR code. It'll open the ScreenDrop page in the browser. You're connected.

### Take a screenshot

On Windows, press `Win+Shift+S` to copy a screenshot to clipboard. It'll appear on the tablet within a second.

## Project structure

```
screendrop/
├── main.go               # server entry point, token generation, routing
├── handlers/
│   └── handlers.go       # WebSocket hub, upload handler, image store
├── clipboardWatcher/
│   └── clipboardWatcher.go  # watches clipboard, posts images to server
├── ringBuffer/
│   └── ringBuffer.go     # generic ring buffer for image history
├── qr/
│   └── qr.go             # QR code generation for terminal
└── static/
    └── index.html        # tablet UI
```

## Security

Access is controlled by a random token generated each time the server starts. The token is embedded in the QR code — anyone who scans it can connect, anyone who doesn't can't. The token changes every restart so old QR codes stop working.

It's not end-to-end encrypted and it's not meant to be — this is a local network tool. Don't run it on public WiFi.

## Built with

- [chi](https://github.com/go-chi/chi) — HTTP router and middleware
- [gorilla/websocket](https://github.com/gorilla/websocket) — WebSocket connections
- [golang.design/x/clipboard](https://pkg.go.dev/golang.design/x/clipboard) — clipboard watching
- [go-qrcode](https://github.com/skip2/go-qrcode) — QR code generation