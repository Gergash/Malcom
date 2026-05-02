// Package middleware — cabeceras HTTP, CORS restringible y límites de uso.
package middleware

import (
	"strings"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

// DefaultSecurityHeaders aplica cabeceras recomendadas (OWASP) a todas las respuestas.
func DefaultSecurityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("Referrer-Policy", "strict-origin-when-cross-origin")
		c.Header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
		c.Next()
	}
}

// APIFrameDeny impide embeber respuestas JSON del API en iframes de terceros.
func APIFrameDeny() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Frame-Options", "DENY")
		c.Next()
	}
}

// BuildCORS configura CORS: si allowedOrigins está vacío se permite cualquier origen (desarrollo).
func BuildCORS(allowedOrigins []string) gin.HandlerFunc {
	cfg := cors.DefaultConfig()
	if len(allowedOrigins) == 0 {
		cfg.AllowAllOrigins = true
	} else {
		cfg.AllowOrigins = allowedOrigins
	}
	cfg.AllowCredentials = false
	cfg.AllowMethods = []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
	cfg.AllowHeaders = []string{
		"Origin", "Content-Type", "Accept", "Authorization",
		"ngrok-skip-browser-warning", "X-Webhook-Secret",
	}
	return cors.New(cfg)
}

// DashboardPageSecurity añade CSP para la página /dashboard (scripts ECharts + iframe desde WordPress).
// frameAncestors: lista separada por espacios de orígenes permitidos; vacío = solo 'self'.
func DashboardPageSecurity(frameAncestors string) gin.HandlerFunc {
	fa := strings.TrimSpace(frameAncestors)
	if fa == "" {
		fa = "'self'"
	}
	csp := strings.Join([]string{
		"default-src 'none'",
		"frame-ancestors 'self' " + fa,
		"script-src 'unsafe-inline' https://cdn.jsdelivr.net",
		"style-src 'unsafe-inline'",
		"connect-src 'self'",
		"img-src data: blob: https:",
		"font-src 'self' data:",
	}, "; ")
	return func(c *gin.Context) {
		c.Header("Content-Security-Policy", csp)
		// framing lo controla CSP; no enviar X-Frame-Options en conflicto con el widget cross-origin
		c.Next()
	}
}
