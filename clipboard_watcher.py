"""
ScreenDrop - Clipboard Watcher
Runs in the background on Windows.
When you copy a screenshot, it automatically sends it to your Go server.

Install dependencies:
  pip install pillow requests pywin32

Run:
  python clipboard_watcher.py
"""

import time
import io
import sys
import requests
from PIL import ImageGrab, Image

SERVER_URL = "http://localhost:8080/upload"
POLL_INTERVAL = 0.5  # seconds between clipboard checks

def get_clipboard_image():
    """Returns PIL Image if clipboard has an image, else None."""
    try:
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            return img
    except Exception:
        pass
    return None

def image_to_bytes(img):
    """Convert PIL Image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def upload(img_bytes):
    """POST image to Go server."""
    try:
        response = requests.post(
            SERVER_URL,
            files={"image": ("screenshot.png", img_bytes, "image/png")},
            timeout=5
        )
        if response.status_code == 200:
            print(f"  ✓ Sent ({len(img_bytes) // 1024} KB)")
        else:
            print(f"  ✗ Server error: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("  ✗ Could not connect to server — is it running?")
    except Exception as e:
        print(f"  ✗ Error: {e}")

def main():
    print("ScreenDrop clipboard watcher running")
    print(f"Sending to: {SERVER_URL}")
    print("Copy any screenshot with Win+Shift+S — it will appear on your tablet")
    print("Press Ctrl+C to stop\n")

    last_image_bytes = None

    while True:
        try:
            img = get_clipboard_image()
            if img is not None:
                img_bytes = image_to_bytes(img)
                # Only send if it's a new image (different from last sent)
                if img_bytes != last_image_bytes:
                    last_image_bytes = img_bytes
                    print(f"Screenshot detected — sending...")
                    upload(img_bytes)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)

if __name__ == "__main__":
    main()
