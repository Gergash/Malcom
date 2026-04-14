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

	return &Config{
		DatabaseURL:      NormalizeDatabaseURL(rawURL),
		Port:             port,
		WorkerURL:        strings.TrimRight(workerURL, "/"),
		DataDir:          dataDir,
		PublicBaseURL:    strings.TrimSpace(os.Getenv("PUBLIC_BASE_URL")),
		FreeMessageLimit: freeLimit,
	}, nil
}

// NormalizeDatabaseURL converts SQLAlchemy/asyncpg URLs to a form GORM accepts.
func NormalizeDatabaseURL(u string) string {
	u = strings.TrimSpace(u)
	u = strings.Replace(u, "postgresql+asyncpg://", "postgres://", 1)
	u = strings.Replace(u, "postgresql://", "postgres://", 1)
	return u
}
