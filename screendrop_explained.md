# ScreenDrop — Code Explained

A walkthrough of every part of the codebase, mapped to concepts you already know from C#.

---

## `main.go` — Entry Point

```go
package main
```

Every Go file belongs to a package. `main` is special — it's the entry point of the program. Same role as `Program.cs` in C#.

```go
hub := handlers.NewHub()
go hub.Run()
```

Creates the WebSocket hub (which holds all connected tablet connections) and runs it concurrently in a goroutine. The `go` keyword is all you need to spin up a goroutine — like `Task.Run()` in C# but much cheaper in memory. The hub runs in the background forever, listening for events.

```go
http.HandleFunc("/", handlers.ServeHome)
http.HandleFunc("/upload", handlers.UploadHandler(hub))
http.HandleFunc("/ws", handlers.WebSocketHandler(hub))
http.HandleFunc("/latest", handlers.LatestImageHandler)
```

Registers routes — same concept as controllers in C#. Each path maps to a handler function. Notice `UploadHandler(hub)` and `WebSocketHandler(hub)` pass the hub in — those handlers need access to it so they can broadcast to connected clients.

```go
http.ListenAndServe("0.0.0.0:8080", nil)
```

Starts the server on all network interfaces. `0.0.0.0` means accept connections from anywhere on the network, not just localhost. `nil` means use the default router we registered routes on above.

---

## `handlers/handlers.go` — Everything Else

### The Hub

```go
type Hub struct {
    clients    map[*websocket.Conn]bool
    broadcast  chan []byte
    register   chan *websocket.Conn
    unregister chan *websocket.Conn
    mu         sync.Mutex
}
```

A struct with four fields:

- `clients` — a map of all connected tablet WebSocket connections. The `bool` value doesn't matter, we're using the map as a set — just tracking which connections exist.
- `broadcast` — a channel. Channels are how goroutines communicate in Go. When you send a message to this channel, the hub picks it up and sends to all clients.
- `register` / `unregister` — channels for adding and removing clients when tablets connect or disconnect.
- `mu` — a mutex lock. Because multiple goroutines can touch `clients` at the same time, we lock it before reading or writing to prevent race conditions. Same concept as `lock` in C#.

---

### NewHub() — Constructor

```go
func NewHub() *Hub {
    return &Hub{
        clients:   make(map[*websocket.Conn]bool),
        broadcast: make(chan []byte, 10),
        ...
    }
}
```

Constructor pattern in Go — by convention named `NewXxx`. Returns a pointer to a Hub (`*Hub`). `make` initialises maps and channels — you can't use them without this, similar to `new` in C#.

---

### Hub.Run() — The Event Loop

```go
func (h *Hub) Run() {
    for {
        select {
        case conn := <-h.register:
            ...
        case conn := <-h.unregister:
            ...
        case message := <-h.broadcast:
            ...
        }
    }
}
```

Runs forever (`for` with no condition = infinite loop). `select` is like a `switch` but for channels — it blocks until one of the channels has data, then handles it:

- Tablet connects → connection arrives on `register` channel → added to `clients` map
- Tablet disconnects → arrives on `unregister` → removed from map
- Image uploaded → arrives on `broadcast` → loops through all clients and sends the message

This is the core of the real time system. One goroutine managing all connections safely.

The `(h *Hub)` part before the function name is called a **receiver** — it's Go's way of attaching a function to a struct. Equivalent to a method on a class in C#.

---

### ImageStore — In-Memory Database

```go
type ImageStore struct {
    mu        sync.RWMutex
    Data      string
    Timestamp string
    Size      int
}

var Store = &ImageStore{}
```

Holds the latest screenshot in memory. `RWMutex` is a read-write mutex — multiple goroutines can read simultaneously, but writes get exclusive access. More efficient than a regular mutex when reads are frequent.

`var Store = &ImageStore{}` is a package-level variable, shared across all requests. This is the "database" for this project — simple, no Postgres needed for a single value.

---

### WebSocketHandler

```go
conn, err := upgrader.Upgrade(w, r, nil)
```

HTTP connections start as regular HTTP then "upgrade" to WebSocket — this is the WebSocket handshake. After this line, `conn` is a persistent two-way connection, not a regular HTTP request/response cycle.

```go
hub.register <- conn
```

Sends the new connection into the hub's register channel. The `<-` operator sends to a channel. The hub's `Run()` goroutine picks it up and adds it to the clients map.

```go
// If there's already an image in the store, send it immediately
Store.mu.RLock()
if Store.Data != "" {
    ...
    conn.WriteMessage(websocket.TextMessage, b)
}
Store.mu.RUnlock()
```

Late join handling — if you open the tablet tab after a screenshot was already sent, the server immediately sends the last image so you don't see a blank screen. This is why we keep the image in the `ImageStore`.

```go
go func() {
    defer func() {
        hub.unregister <- conn
    }()
    for {
        _, _, err := conn.ReadMessage()
        if err != nil {
            break
        }
    }
}()
```

Spins up a goroutine that does nothing except detect when the tablet disconnects. When `ReadMessage()` errors, the connection is dead — send it to the unregister channel so the hub cleans it up. `defer` runs when the function exits, same as `finally` in C#.

---

### UploadHandler

```go
r.Body = http.MaxBytesReader(w, r.Body, 10<<20)
```

Limits request body to 10MB (`10 << 20` is a bitwise left shift, a compact way to write 10 × 1024 × 1024). Prevents someone sending a massive file and crashing the server.

```go
file, header, err := r.FormFile("image")
```

Reads the uploaded file from the multipart form. The `"image"` key matches what the Python clipboard watcher sends — `files={"image": ...}`.

```go
encoded := base64.StdEncoding.EncodeToString(data)
dataURL := fmt.Sprintf("data:%s;base64,%s", contentType, encoded)
```

Converts the raw image bytes to a base64 data URL — a format browsers understand directly as an image source. This means the tablet can display the image without making a second HTTP request to fetch it. The whole image travels inside the WebSocket message as text.

```go
msg := map[string]string{
    "type":      "image",
    "data":      dataURL,
    "timestamp": timestamp,
}
b, _ := json.Marshal(msg)
hub.broadcast <- b
```

Serialises the message to JSON and drops it on the broadcast channel. The hub picks it up and sends it to all connected tablets.

---

## `static/index.html` — Tablet UI

### WebSocket Connection

```javascript
const ws = new WebSocket(`ws://${location.host}/ws`)
```

Opens a WebSocket connection back to the Go server. `location.host` automatically uses whatever IP/port the page was loaded from — so it works on any network without hardcoding the IP.

```javascript
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.type === 'image') {
        showImage(msg.data, msg.timestamp)
    }
}
```

Receives messages from the server. Parses the JSON, checks the type, and calls `showImage` which sets the `<img>` src to the base64 data URL. Browser renders it instantly.

```javascript
ws.onclose = () => {
    dot.className = 'dot connecting'
    reconnectTimer = setTimeout(connect, 2000)
}
```

Auto-reconnect — if WiFi drops, the tablet retries every 2 seconds. This is why you see the status dot go orange and back to green when the connection blips.

### Save Button

```javascript
function saveImage() {
    const a = document.createElement('a')
    a.href = screenshot.src
    a.download = `screenshot-${Date.now()}.png`
    a.click()
}
```

Creates a temporary anchor tag with a `download` attribute and programmatically clicks it. This triggers the browser's native file save — no server involved. The image is already in memory as a base64 URL.

---

## `clipboard_watcher.py` — Windows Clipboard Watcher

```python
img = ImageGrab.grabclipboard()
if isinstance(img, Image.Image):
    ...
```

`ImageGrab.grabclipboard()` reads whatever is currently on the Windows clipboard. It returns a PIL Image object if the clipboard contains an image (like after `Win+Shift+S`), or `None` otherwise.

```python
if img_bytes != last_image_bytes:
    last_image_bytes = img_bytes
    upload(img_bytes)
```

Compares the current clipboard image to the last one sent. Prevents sending the same screenshot multiple times if the clipboard hasn't changed between polls.

```python
requests.post(
    SERVER_URL,
    files={"image": ("screenshot.png", img_bytes, "image/png")},
    timeout=5
)
```

Sends the image as a multipart form POST to the Go server — the same format as a browser file upload. The `"image"` key matches what `r.FormFile("image")` expects in the Go handler.

---

## Data Flow — End to End

```
Win+Shift+S pressed on laptop
        ↓
clipboard_watcher.py detects new image in clipboard (polls every 0.5s)
        ↓
Python converts image to PNG bytes
        ↓
HTTP POST to /upload (multipart form)
        ↓
Go UploadHandler receives file
        ↓
Converts to base64 data URL
        ↓
Updates ImageStore (in memory)
        ↓
Sends JSON message to hub.broadcast channel
        ↓
Hub.Run() receives from broadcast channel
        ↓
Loops through all connected clients
        ↓
Writes JSON message down each WebSocket connection
        ↓
Tablet browser receives WebSocket message
        ↓
JavaScript sets <img src> to base64 data URL
        ↓
Image renders on tablet
```

Total time: under 1 second on local WiFi.

---

## Why No Database?

A common question — why not store images in Postgres?

For this use case, a DB would add complexity with no benefit:

- We only need the **latest** screenshot, not history
- Images are **temporary** — you glance at it, drag it into your notes, done
- The server restarts infrequently — memory loss isn't a problem
- Local network only — no need for persistence across deployments

If you wanted to add history (last 10 screenshots, searchable by time), that's when Postgres would make sense. For now, a single in-memory struct is the right tool.

---

## Go Concepts Used

| Concept | Where | C# Equivalent |
|---|---|---|
| Struct | `Hub`, `ImageStore` | Class |
| Receiver method | `(h *Hub) Run()` | Class method |
| Constructor pattern | `NewHub()` | `new Hub()` |
| Goroutine | `go hub.Run()` | `Task.Run()` |
| Channel | `hub.broadcast <- b` | `BlockingCollection<T>` |
| Select | `select { case ... }` | `switch` on tasks |
| Mutex | `sync.Mutex`, `sync.RWMutex` | `lock` keyword |
| Defer | `defer conn.Close()` | `finally` |
| Error as value | `result, err := fn()` | `try/catch` |
| Package | `package handlers` | Namespace |
