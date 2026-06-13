package main

import (
	"log"
	"net/http"
	"screendrop/handlers"
	"screendrop/clipboardWatcher"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

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
    r.Get("/ws", handlers.WebSocketHandler(hub))
    r.Get("/latest", handlers.LatestImageHandler)

    log.Println("ScreenDrop running on http://0.0.0.0:8080")
    log.Fatal(http.ListenAndServe("0.0.0.0:8080", r))
}
