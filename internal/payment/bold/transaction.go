package bold

import (
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/tidwall/gjson"
)

var chatIDPattern = regexp.MustCompile(`(?i)(?:^|[?&\s])chat_id[=:]([0-9]+)`)
var insightFlowOrderPattern = regexp.MustCompile(`(?i)^IF-([0-9]+)-[0-9]+$`)

// Event is the normalized subset of a Bold webhook needed by billing.
type Event struct {
	Type        string
	Status      string
	Reference   string
	Description string
	AmountCents int
	ChatID      *int64
	PayerEmail  string // correo del pagador si Bold lo incluye; "" si ausente/ inválido
}

// ParseEvent normalizes common Bold transaction webhook payload shapes.
func ParseEvent(raw []byte) Event {
	ev := Event{
		Type: firstString(raw,
			"type",
			"event",
			"event_type",
			"data.type",
			"data.event",
		),
		Status: firstString(raw,
			"status",
			"transaction.status",
			"data.status",
			"data.transaction.status",
			"data.payment.status",
		),
		Reference: firstString(raw,
			"reference",
			"transaction.reference",
			"transaction.id",
			"data.reference",
			"data.transaction.reference",
			"data.transaction.id",
			"data.payment.reference",
			"data.payment.id",
		),
		Description: firstString(raw,
			"description",
			"transaction.description",
			"data.description",
			"data.transaction.description",
			"data.payment.description",
		),
		AmountCents: int(firstInt(raw,
			"amount_in_cents",
			"amount",
			"transaction.amount_in_cents",
			"transaction.amount",
			"data.amount_in_cents",
			"data.amount",
			"data.transaction.amount_in_cents",
			"data.transaction.amount",
		)),
	}
	ev.ChatID = ExtractChatID(raw)
	ev.PayerEmail = ExtractPayerEmail(raw)
	return ev
}

// ExtractPayerEmail extracts the payer's email from common Bold payload shapes.
// Returns "" when absent or not email-shaped. Used to auto-link email↔chat_id
// on payment confirmation so premium can be recovered if localStorage is lost.
func ExtractPayerEmail(raw []byte) string {
	email := firstString(raw,
		"payer_email",
		"customer_email",
		"payer.email",
		"customer.email",
		"transaction.payer_email",
		"transaction.customer_email",
		"transaction.payer.email",
		"transaction.customer.email",
		"data.payer_email",
		"data.customer_email",
		"data.payer.email",
		"data.customer.email",
		"data.transaction.payer_email",
		"data.transaction.customer_email",
		"data.payment.payer_email",
		"data.payment.customer_email",
	)
	email = strings.ToLower(strings.TrimSpace(email))
	// Validación mínima: evita guardar strings arbitrarios como email.
	// users.email es varchar(320) — descartar valores más largos.
	at := strings.Index(email, "@")
	if at < 1 || len(email) > 320 ||
		!strings.Contains(email[at:], ".") || strings.ContainsAny(email, " \t\n") {
		return ""
	}
	return email
}

// IsSuccessful reports whether the Bold event/status indicates a successful transaction.
func (e Event) IsSuccessful() bool {
	t := strings.ToLower(strings.TrimSpace(e.Type))
	s := strings.ToLower(strings.TrimSpace(e.Status))
	return t == "transaction.succeeded" ||
		t == "transaction.approved" ||
		s == "succeeded" ||
		s == "success" ||
		s == "approved" ||
		s == "paid" ||
		s == "captured"
}

// ExtractChatID extracts chat_id from metadata or URL-style description fields.
func ExtractChatID(raw []byte) *int64 {
	for _, path := range []string{
		"metadata.chat_id",
		"transaction.metadata.chat_id",
		"data.metadata.chat_id",
		"data.transaction.metadata.chat_id",
		"data.payment.metadata.chat_id",
	} {
		if id := parseInt64(gjson.GetBytes(raw, path).String()); id != nil {
			return id
		}
	}

	for _, path := range []string{
		"description",
		"transaction.description",
		"data.description",
		"data.transaction.description",
		"data.payment.description",
		"checkout_url",
		"data.checkout_url",
		"data.transaction.checkout_url",
	} {
		if id := extractChatIDFromText(gjson.GetBytes(raw, path).String()); id != nil {
			return id
		}
	}

	for _, path := range []string{
		"reference",
		"transaction.reference",
		"data.reference",
		"data.transaction.reference",
		"data.payment.reference",
		"order_id",
		"data.order_id",
	} {
		text := strings.TrimSpace(gjson.GetBytes(raw, path).String())
		if text == "" {
			continue
		}
		if m := insightFlowOrderPattern.FindStringSubmatch(text); len(m) == 2 {
			if id := parseInt64(m[1]); id != nil {
				return id
			}
		}
		if id := parseInt64(text); id != nil {
			return id
		}
		if id := extractChatIDFromText(text); id != nil {
			return id
		}
	}
	return nil
}

func firstString(raw []byte, paths ...string) string {
	for _, path := range paths {
		v := strings.TrimSpace(gjson.GetBytes(raw, path).String())
		if v != "" {
			return v
		}
	}
	return ""
}

func firstInt(raw []byte, paths ...string) int64 {
	for _, path := range paths {
		v := gjson.GetBytes(raw, path)
		if v.Exists() {
			return v.Int()
		}
	}
	return 0
}

func parseInt64(s string) *int64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil || n <= 0 {
		return nil
	}
	return &n
}

func extractChatIDFromText(s string) *int64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	if u, err := url.Parse(s); err == nil {
		if id := parseInt64(u.Query().Get("chat_id")); id != nil {
			return id
		}
	}
	m := chatIDPattern.FindStringSubmatch(s)
	if len(m) == 2 {
		return parseInt64(m[1])
	}
	return nil
}
