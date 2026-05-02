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
	EnablePublicData bool // cuando true, sirve /data/* sin restricción (solo DEV)

	// CORSAllowedOrigins — lista separada por comas; vacío = permitir cualquier origen (solo desarrollo).
	CORSAllowedOrigins []string
	// CSPFrameAncestors — orígenes que pueden embeber /dashboard en iframe (p. ej. sitio WordPress).
	// Formato: "https://powerups.com.co https://www.powerups.com.co". Vacío = solo 'self'.
	CSPFrameAncestors string

	// Límite aproximado de peticiones /chat y /chat/upload por IP (token bucket). Cero = desactivado.
	ChatRateLimitRPS   float64
	ChatRateLimitBurst int

	// Tamaño máximo de subida multipart (MB). Por defecto 32.
	UploadMaxMB int

	// Si no está vacío, POST /billing/webhook exige el mismo valor en X-Webhook-Secret o Authorization: Bearer …
	BillingWebhookSecret string
	// Secreto de eventos Wompi (Dashboard comercio): valida X-Event-Checksum / signature.checksum del body.
	WompiEventSecret string
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

	freeLimit := 7
	if v := strings.TrimSpace(os.Getenv("FREE_MESSAGE_LIMIT")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			freeLimit = n
		}
	}

	enablePublicData := strings.ToLower(strings.TrimSpace(os.Getenv("ENABLE_PUBLIC_DATA"))) == "true"

	corsOrigins := parseCommaList(os.Getenv("CORS_ALLOWED_ORIGINS"))
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

	return &Config{
		DatabaseURL:          NormalizeDatabaseURL(rawURL),
		Port:                 port,
		WorkerURL:            strings.TrimRight(workerURL, "/"),
		DataDir:              dataDir,
		PublicBaseURL:        strings.TrimSpace(os.Getenv("PUBLIC_BASE_URL")),
		FreeMessageLimit:     freeLimit,
		EnablePublicData:     enablePublicData,
		CORSAllowedOrigins:   corsOrigins,
		CSPFrameAncestors:    cspFrames,
		ChatRateLimitRPS:     chatRPS,
		ChatRateLimitBurst:   chatBurst,
		UploadMaxMB:          uploadMB,
		BillingWebhookSecret: webhookSecret,
		WompiEventSecret:     wompiEvent,
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
