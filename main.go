package main

import (
	"log"
	"net/http"
	"screendrop/handlers"
)

func main() {
	hub := handlers.NewHub()
	go hub.Run()

	http.HandleFunc("/", handlers.ServeHome)
	http.HandleFunc("/upload", handlers.UploadHandler(hub))
	http.HandleFunc("/ws", handlers.WebSocketHandler(hub))
	http.HandleFunc("/latest", handlers.LatestImageHandler)

	log.Println("ScreenDrop running on http://0.0.0.0:8080")
	log.Println("Open http://<your-laptop-ip>:8080 on your tablet")
	log.Fatal(http.ListenAndServe("0.0.0.0:8080", nil))
}
