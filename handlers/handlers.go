package handlers

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"sync"
	"time"
	"github.com/gorilla/websocket"
	"screendrop/ringBuffer"
)

// ---- WebSocket Hub ----
// Maintains all active tablet connections.
// When a new image arrives, it broadcasts to every connected client.

type Hub struct {
	clients    map[*websocket.Conn]bool
	broadcast  chan []byte
	register   chan *websocket.Conn
	unregister chan *websocket.Conn
	mu         sync.Mutex
}

func NewHub() *Hub {
	return &Hub{
		clients:    make(map[*websocket.Conn]bool),
		broadcast:  make(chan []byte, 10),
		register:   make(chan *websocket.Conn),
		unregister: make(chan *websocket.Conn),
	}
}

func (h *Hub) Run() {
	for {
		select {
		case conn := <-h.register:
			h.mu.Lock()
			h.clients[conn] = true
			h.mu.Unlock()
			log.Println("Tablet connected. Total clients:", len(h.clients))

		case conn := <-h.unregister:
			h.mu.Lock()
			delete(h.clients, conn)
			conn.Close()
			h.mu.Unlock()
			log.Println("Tablet disconnected. Total clients:", len(h.clients))

		case message := <-h.broadcast:
			h.mu.Lock()
			for conn := range h.clients {
				err := conn.WriteMessage(websocket.TextMessage, message)
				if err != nil {
					log.Println("Write error, removing client:", err)
					delete(h.clients, conn)
					conn.Close()
				}
			}
			h.mu.Unlock()
		}
	}
}

// ---- Latest image store ----
// Holds the most recent screenshot in memory.
// No DB needed — we only care about the N latest ones.

// add this
type Image struct {
    Data      string
    Timestamp string
    Size      int
    Seq       int
}

func (img *Image) GetSeq() int {
    return img.Seq
}

const BufferSize = 20
var Store = ringBuffer.NewRingBuffer[*Image](BufferSize)

// ---- Upgrader ----

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true // allow all origins on local network
	},
}

// ---- Handlers ----

func ServeHome(w http.ResponseWriter, r *http.Request) {
	http.ServeFile(w, r, "static/index.html")
}

func WebSocketHandler(hub *Hub) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Println("WebSocket upgrade error:", err)
			return
		}

		
		// read hello from client first
		_, msg, err := conn.ReadMessage()
		lastSeq := -1
		if err == nil {
			var hello map[string]any
			if json.Unmarshal(msg, &hello) == nil {
				if t, ok := hello["type"].(string); ok && t == "hello" {
					if seq, ok := hello["lastSeq"].(float64); ok {
						lastSeq = int(seq)
					}
				}
			}
		}
		// decide what to send based on lastSeq
		var toSend []*Image
		if lastSeq == -1 {
			toSend = Store.Get()      // fresh connect, send everything
		} else {
			toSend = Store.GetSince(lastSeq)  // reconnect, send only new ones
		}

		for _, img := range toSend {
			msg := map[string]any{
				"type":      "image",
				"data":      img.Data,
				"timestamp": img.Timestamp,
				"seq":       img.Seq,
			}
			b, _ := json.Marshal(msg)
			conn.WriteMessage(websocket.TextMessage, b)
		}
		hub.register <- conn
		// Keep connection alive, detect disconnects
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
	}
}

func UploadHandler(hub *Hub) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// if r.Method != http.MethodPost {
		// 	http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		// 	return
		// }

		// 10MB max
		r.Body = http.MaxBytesReader(w, r.Body, 10<<20)

		file, header, err := r.FormFile("image")
		if err != nil {
			http.Error(w, "Could not read image: "+err.Error(), http.StatusBadRequest)
			return
		}
		defer file.Close()

		data, err := io.ReadAll(file)
		if err != nil {
			http.Error(w, "Could not read file", http.StatusInternalServerError)
			return
		}

		// Detect content type (png, jpeg etc)
		contentType := header.Header.Get("Content-Type")
		if contentType == "" {
			contentType = http.DetectContentType(data)
		}

		encoded := base64.StdEncoding.EncodeToString(data)
		dataURL := fmt.Sprintf("data:%s;base64,%s", contentType, encoded)
		timestamp := time.Now().Format("3:04:05 PM")

		// Update in-memory store
		Store.Add(&Image{
			Data:      dataURL,
			Timestamp: timestamp,
			Size:      len(data),
		})

		img,_ :=Store.Latest()
		// Broadcast to all connected tablets
		msg := map[string]any{
			"type":      "image",
			"data":      img.Data,
			"timestamp": img.Timestamp,
			"seq": img.Seq,
		}
		b, _ := json.Marshal(msg)
		hub.broadcast <- b

		log.Printf("Image received: %s, %d KB, sent to %d client(s)", header.Filename, len(data)/1024, len(hub.clients))

		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	}
}

func LatestImageHandler(w http.ResponseWriter, r *http.Request) {
    images := Store.Get()
    if len(images) == 0 {
        http.Error(w, "No images yet", http.StatusNotFound)
        return
    }

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(images)
}
