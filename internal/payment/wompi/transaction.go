package wompi

import "github.com/tidwall/gjson"

// MapTransactionWebhook extrae campos del evento transaction.updated (cuerpo oficial Wompi).
func MapTransactionWebhook(raw []byte) (reference, status string, amountCents int, customerEmail string, ok bool) {
	if gjson.GetBytes(raw, "event").String() != "transaction.updated" {
		return "", "", 0, "", false
	}
	base := "data.transaction."
	reference = gjson.GetBytes(raw, base+"reference").String()
	status = gjson.GetBytes(raw, base+"status").String()
	amountCents = int(gjson.GetBytes(raw, base+"amount_in_cents").Int())
	customerEmail = gjson.GetBytes(raw, base+"customer_email").String()
	ok = reference != "" && status != ""
	return
}
