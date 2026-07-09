package bold

import (
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/tidwall/gjson"
)

var chatIDPattern = regexp.MustCompile(`(?i)(?:^|[?&\s])chat_id[=:]([0-9]+)`)

// Event is the normalized subset of a Bold webhook needed by billing.
type Event struct {
	Type        string
	Status      string
	Reference   string
	Description string
	AmountCents int
	ChatID      *int64
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
	return ev
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
