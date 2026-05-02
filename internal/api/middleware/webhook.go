package middleware

import (
	"crypto/subtle"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// BillingWebhookAuth exige cabecera compartida si secret no está vacío.
func BillingWebhookAuth(secret string) gin.HandlerFunc {
	if strings.TrimSpace(secret) == "" {
		return func(c *gin.Context) { c.Next() }
	}
	want := []byte(strings.TrimSpace(secret))
	return func(c *gin.Context) {
		h := strings.TrimSpace(c.GetHeader("X-Webhook-Secret"))
		bearer := strings.TrimSpace(strings.TrimPrefix(c.GetHeader("Authorization"), "Bearer"))
		ok := subtle.ConstantTimeCompare([]byte(h), want) == 1 ||
			(bearer != "" && subtle.ConstantTimeCompare([]byte(bearer), want) == 1)
		if !ok {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"detail": "Webhook no autorizado.",
			})
			return
		}
		c.Next()
	}
}
