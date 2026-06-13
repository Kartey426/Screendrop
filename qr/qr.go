package qr

import(
	"fmt"
	"github.com/skip2/go-qrcode"
)

func Generate(url string) error {
	q, err := qrcode.New(url, qrcode.Medium)
	if err!=nil{
		return err
	}
	fmt.Println(q.ToSmallString(false))
	return nil
}
