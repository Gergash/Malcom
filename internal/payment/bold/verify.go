// Package bold contains helpers for Bold payment webhooks.
package bold

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"strings"
)

// VerifySignature validates Bold webhook integrity using HMAC-SHA256(rawBody, secret).
//
// Bold installations can expose the signature header with small formatting
// differences depending on dashboard/version. This accepts:
//   - raw hex digest
//   - "sha256=<hex>"
//   - base64 digest
//
// An empty secret never validates: production webhooks must be signed.
func VerifySignature(raw []byte, providedHeader, webhookSecret string) bool {
	secret := strings.TrimSpace(webhookSecret)
	provided := strings.TrimSpace(providedHeader)
	if secret == "" || provided == "" {
		return false
	}
	provided = strings.TrimPrefix(provided, "sha256=")

	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write(raw)
	expected := mac.Sum(nil)

	if decoded, err := hex.DecodeString(provided); err == nil {
		return subtle.ConstantTimeCompare(decoded, expected) == 1
	}
	if decoded, err := base64.StdEncoding.DecodeString(provided); err == nil {
		return subtle.ConstantTimeCompare(decoded, expected) == 1
	}
	return hmac.Equal([]byte(hex.EncodeToString(expected)), []byte(strings.ToLower(provided)))
}
