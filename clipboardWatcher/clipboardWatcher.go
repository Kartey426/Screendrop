package clipboardwatcher

import(
	"golang.design/x/clipboard"
	"context"
	"net/http"
	"mime/multipart"
	"bytes"
	"time"
)

func WatchClipboard(serverURL string) error {
    err := clipboard.Init()
	if err != nil {
		return err
	}
	ch := clipboard.Watch(context.TODO())
	var lastUpload time.Time
	for data := range ch {
		switch data.Format {
		case clipboard.FmtText:
				println("text:", string(data.Bytes))
		case clipboard.FmtImage:
				if time.Since(lastUpload) < 500*time.Millisecond {
					println("debounced duplicate")
					continue
				}
				println("image bytes:", len(data.Bytes))
				err := uploadImage(data.Bytes, serverURL)
				if err != nil {
					println("upload error:", err.Error())
				}else {
					println("image uploaded successfully")
					lastUpload = time.Now()
				}
		}
	}
	return nil
}

func uploadImage(imgBytes []byte, serverURL string) error {
    var buf bytes.Buffer
    w := multipart.NewWriter(&buf)

    part, err := w.CreateFormFile("image", "screenshot.png")
    if err != nil {
        return err
    }
    part.Write(imgBytes)
    w.Close()

    resp, err := http.Post(serverURL+"/upload", w.FormDataContentType(), &buf)
    if err != nil {
        return err
    }
    defer resp.Body.Close()
    return nil
}