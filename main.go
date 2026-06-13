package main

import (
	"log"
	"net/http"
	"screendrop/handlers"
	"screendrop/clipboardWatcher"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"crypto/rand"
	"encoding/hex"
	"screendrop/qr"
	"fmt"
	"net"
)

func generateToken() string {
    b := make([]byte, 16)
    rand.Read(b)
    return hex.EncodeToString(b) // 32 char hex string
}

func getLocalIP() string {
    iface, err := net.InterfaceByName("Wi-Fi")
    if err != nil {
        // fallback to the subnet scan
        return getLocalIPFallback()
    }

    addrs, err := iface.Addrs()
    if err != nil {
        return "localhost"
    }

    for _, addr := range addrs {
        if ipnet, ok := addr.(*net.IPNet); ok {
            if ip4 := ipnet.IP.To4(); ip4 != nil {
                return ip4.String()
            }
        }
    }
    return "localhost"
}

func getLocalIPFallback() string {
    addrs, err := net.InterfaceAddrs()
    if err != nil {
        return "localhost"
    }
    for _, addr := range addrs {
        if ipnet, ok := addr.(*net.IPNet); ok && !ipnet.IP.IsLoopback() {
            if ip4 := ipnet.IP.To4(); ip4 != nil {
                if ip4[0] == 192 && ip4[1] == 168 {
                    return ipnet.IP.String()
                }
            }
        }
    }
    return "localhost"
}

func main() {
	hub := handlers.NewHub()
	go hub.Run()

	// start clipboard watcher in background
    go func() {
        if err := clipboardwatcher.WatchClipboard("http://localhost:8080"); err != nil {
            log.Fatal("clipboard watcher error:", err)
        }
    }()

	r := chi.NewRouter()
		
    // middleware
    r.Use(middleware.Logger)
    r.Use(middleware.Recoverer)
    r.Use(middleware.RequestID)

    // routes
	r.Post("/test", func(w http.ResponseWriter, r *http.Request) {
		log.Println("test hit")
		w.Write([]byte("ok"))
	})
    r.Get("/", handlers.ServeHome)
    r.Post("/upload", handlers.UploadHandler(hub))
	token := generateToken()
	log.Println("Token:", token)
	url := fmt.Sprintf("http://%s:8080?token=%s", getLocalIP(), token)
	qr.Generate(url)
    r.Get("/ws", handlers.WebSocketHandler(hub, token))
    r.Get("/latest", handlers.LatestImageHandler)

    log.Println("ScreenDrop running on http://0.0.0.0:8080")
    log.Fatal(http.ListenAndServe("0.0.0.0:8080", r))
}
