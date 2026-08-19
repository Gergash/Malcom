// Package config loads application settings (env + .env).
package config

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

// Config holds runtime configuration for the Go API.
type Config struct {
	DatabaseURL      string
	Port             string
	WorkerURL        string
	DataDir          string
	PublicBaseURL    string
	FreeMessageLimit int
	QuotaTimezone    string // ej. America/Bogota — día calendario del cupo diario
	EnablePublicData bool   // cuando true, sirve /data/* sin restricción (solo DEV)

	// CORSAllowedOrigins — lista separada por comas; vacío = permitir cualquier origen (solo desarrollo).
	CORSAllowedOrigins []string
	// CSPFrameAncestors — orígenes que pueden embeber /dashboard en iframe (p. ej. sitio WordPress).
	// Formato: "https://powerups.com.co https://www.powerups.com.co". Vacío = solo 'self'.
	CSPFrameAncestors string

	// TrustedProxies — de qué peers acepta Gin la cabecera X-Forwarded-For para
	// resolver la IP del cliente. Debe listar al proxy, no a la API: cuando la API
	// corre en Docker detrás de Caddy, el peer es la gateway del bridge
	// (172.x), no 127.0.0.1. Si la lista no incluye al peer real, ClientIP()
	// devuelve la IP de la gateway para todos y el rate limit pasa a ser global.
	TrustedProxies []string

	// Límite aproximado de peticiones /chat y /chat/upload por IP (token bucket). Cero = desactivado.
	ChatRateLimitRPS   float64
	ChatRateLimitBurst int

	// Tamaño máximo de subida multipart (MB). Por defecto 32.
	UploadMaxMB int

	// Si no está vacío, POST /billing/webhook exige el mismo valor en X-Webhook-Secret o Authorization: Bearer …
	BillingWebhookSecret string
	// Secreto de eventos Wompi (Dashboard comercio): valida X-Event-Checksum / signature.checksum del body.
	WompiEventSecret string
	// Secreto de webhook Bold: valida X-Bold-Signature con HMAC-SHA256 sobre el body crudo.
	BoldWebhookSecret string
	// Llave de identidad Bold (Botón de pagos) — pública en el frontend.
	BoldAPIKey string
	// Llave secreta Bold para el hash de integridad del botón (solo servidor).
	BoldIntegritySecret string
	// Monto fijo en COP para activar premium vía Bold (p. ej. 40000).
	PremiumAmountCOP int
	// URL a la que Bold devuelve al usuario tras el pago (data-redirection-url).
	// Configurable con PREMIUM_PORTAL_URL; la API le añade ?chat_id=.
	PremiumPortalURL string

	// DevForcePremium: SOLO DESARROLLO. Si true, todos los chats se tratan como premium
	// (sin paywall, con dashboard ECharts, gráficas múltiples y descargas). Útil para
	// validar el flujo premium en local antes de exponerlo en producción.
	// Activar con DEV_FORCE_PREMIUM=true en .env y reiniciar la API.
	DevForcePremium bool
	// WorkerRequestTimeoutSec — techo de espera API→Brain (alinear con WORKER_REQUEST_TIMEOUT_SEC).
	WorkerRequestTimeoutSec int

	// ── Email login (magic link) / Bold auth gate ──────────────────────────────
	// ResendAPIKey — API key de Resend (https://resend.com) para el envío de magic links.
	ResendAPIKey string
	// MailFrom / MailFromName — remitente de los correos transaccionales (magic link).
	MailFrom     string
	MailFromName string
	// AuthRateLimitRPS/Burst — límite por IP en POST /auth/request-magic-link (token bucket).
	AuthRateLimitRPS   float64
	AuthRateLimitBurst int
	// LoginGateEnabled — feature flag: activa las rutas de auth, el gate de BoldCheckout y el
	// ticker de expiración premium. false = comportamiento actual sin gate (rollback rápido).
	LoginGateEnabled bool
}

// Load reads .env (if present) and environment variables.
func Load() (*Config, error) {
	if err := godotenv.Load(); err != nil {
		log.Println("Advertencia: no se encontró .env, usando variables de entorno del sistema.")
	}

	rawURL := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if rawURL == "" {
		return nil, fmt.Errorf("variable de entorno obligatoria no definida: DATABASE_URL")
	}

	port := strings.TrimSpace(os.Getenv("API_PORT"))
	if port == "" {
		port = strings.TrimSpace(os.Getenv("PORT"))
	}
	if port == "" {
		port = "8080"
	}

	workerURL := strings.TrimSpace(os.Getenv("WORKER_URL"))
	if workerURL == "" {
		workerURL = "http://localhost:8001"
	}

	dataDir := strings.TrimSpace(os.Getenv("DATA_DIR"))
	if dataDir == "" {
		dataDir = "data"
	}
	if !filepath.IsAbs(dataDir) {
		wd, err := os.Getwd()
		if err == nil {
			dataDir = filepath.Clean(filepath.Join(wd, dataDir))
		}
	}

	freeLimit := 15
	if v := strings.TrimSpace(os.Getenv("FREE_MESSAGE_LIMIT")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			freeLimit = n
		}
	}

	enablePublicData := strings.ToLower(strings.TrimSpace(os.Getenv("ENABLE_PUBLIC_DATA"))) == "true"

	corsOrigins := parseCommaList(os.Getenv("CORS_ALLOWED_ORIGINS"))
	trustedProxies := parseCommaList(os.Getenv("TRUSTED_PROXIES"))
	if len(trustedProxies) == 0 {
		// Loopback (API en el host) + rango privado de los bridges de Docker
		// (172.16.0.0/12 cubre 172.17–172.31), que es el peer cuando Caddy
		// alcanza al contenedor por el puerto publicado.
		trustedProxies = []string{"127.0.0.1", "::1", "172.16.0.0/12"}
	}
	cspFrames := strings.TrimSpace(os.Getenv("CSP_FRAME_ANCESTORS"))

	chatRPS := 8.0
	if v := strings.TrimSpace(os.Getenv("CHAT_RATE_LIMIT_RPS")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f >= 0 {
			chatRPS = f
		}
	}
	chatBurst := 24
	if v := strings.TrimSpace(os.Getenv("CHAT_RATE_LIMIT_BURST")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			chatBurst = n
		}
	}

	uploadMB := 32
	if v := strings.TrimSpace(os.Getenv("UPLOAD_MAX_MB")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			uploadMB = n
		}
	}

	webhookSecret := strings.TrimSpace(os.Getenv("BILLING_WEBHOOK_SECRET"))
	wompiEvent := strings.TrimSpace(os.Getenv("WOMPI_EVENT_SECRET"))
	boldWebhook := strings.TrimSpace(os.Getenv("BOLD_WEBHOOK_SECRET"))
	boldAPIKey := strings.TrimSpace(os.Getenv("BOLD_API_KEY"))
	boldIntegrity := strings.TrimSpace(os.Getenv("BOLD_INTEGRITY_SECRET"))

	devForcePremium := false
	switch strings.ToLower(strings.TrimSpace(os.Getenv("DEV_FORCE_PREMIUM"))) {
	case "1", "true", "yes", "on":
		devForcePremium = true
	}

	premiumAmountCOP := 40000
	if v := strings.TrimSpace(os.Getenv("PREMIUM_AMOUNT_COP")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			premiumAmountCOP = n
		}
	}

	premiumPortalURL := strings.TrimSpace(os.Getenv("PREMIUM_PORTAL_URL"))
	if premiumPortalURL == "" {
		premiumPortalURL = "https://clarity-connector-18.lovable.app/insightflow/portal"
	}

	quotaTZ := strings.TrimSpace(os.Getenv("QUOTA_TIMEZONE"))
	if quotaTZ == "" {
		quotaTZ = "America/Bogota"
	}

	workerTimeoutSec := 330
	if v := strings.TrimSpace(os.Getenv("WORKER_REQUEST_TIMEOUT_SEC")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			workerTimeoutSec = n
		}
	}

	resendAPIKey := strings.TrimSpace(os.Getenv("RESEND_API_KEY"))
	mailFrom := strings.TrimSpace(os.Getenv("MAIL_FROM"))
	mailFromName := strings.TrimSpace(os.Getenv("MAIL_FROM_NAME"))

	authRPS := 0.1
	if v := strings.TrimSpace(os.Getenv("AUTH_RATE_LIMIT_RPS")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f >= 0 {
			authRPS = f
		}
	}
	authBurst := 3
	if v := strings.TrimSpace(os.Getenv("AUTH_RATE_LIMIT_BURST")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			authBurst = n
		}
	}

	loginGateEnabled := false
	switch strings.ToLower(strings.TrimSpace(os.Getenv("LOGIN_GATE_ENABLED"))) {
	case "1", "true", "yes", "on":
		loginGateEnabled = true
	}

	return &Config{
		DatabaseURL:             NormalizeDatabaseURL(rawURL),
		Port:                    port,
		WorkerURL:               strings.TrimRight(workerURL, "/"),
		DataDir:                 dataDir,
		PublicBaseURL:           strings.TrimSpace(os.Getenv("PUBLIC_BASE_URL")),
		FreeMessageLimit:        freeLimit,
		QuotaTimezone:           quotaTZ,
		EnablePublicData:        enablePublicData,
		CORSAllowedOrigins:      corsOrigins,
		TrustedProxies:          trustedProxies,
		CSPFrameAncestors:       cspFrames,
		ChatRateLimitRPS:        chatRPS,
		ChatRateLimitBurst:      chatBurst,
		UploadMaxMB:             uploadMB,
		BillingWebhookSecret:    webhookSecret,
		WompiEventSecret:        wompiEvent,
		BoldWebhookSecret:       boldWebhook,
		BoldAPIKey:              boldAPIKey,
		BoldIntegritySecret:     boldIntegrity,
		PremiumAmountCOP:        premiumAmountCOP,
		PremiumPortalURL:        premiumPortalURL,
		DevForcePremium:         devForcePremium,
		WorkerRequestTimeoutSec: workerTimeoutSec,
		ResendAPIKey:            resendAPIKey,
		MailFrom:                mailFrom,
		MailFromName:            mailFromName,
		AuthRateLimitRPS:        authRPS,
		AuthRateLimitBurst:      authBurst,
		LoginGateEnabled:        loginGateEnabled,
	}, nil
}

func parseCommaList(s string) []string {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// NormalizeDatabaseURL converts SQLAlchemy/asyncpg URLs to a form GORM accepts.
func NormalizeDatabaseURL(u string) string {
	u = strings.TrimSpace(u)
	u = strings.Replace(u, "postgresql+asyncpg://", "postgres://", 1)
	u = strings.Replace(u, "postgresql://", "postgres://", 1)
	return u
}
