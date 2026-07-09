// main.go: punto de entrada del servidor InsightFlow Malcom API (Go).
package main

import (
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/handlers"
	"github.com/powerups/insightflow-malcom/internal/api/middleware"
	"github.com/powerups/insightflow-malcom/internal/config"
	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"github.com/powerups/insightflow-malcom/internal/db/repos"
	"github.com/powerups/insightflow-malcom/internal/worker"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	if err := os.MkdirAll(cfg.DataDir, 0o755); err != nil {
		log.Fatalf("No se pudo crear el directorio data: %v", err)
	}
	uploadTmp := filepath.Join(cfg.DataDir, ".upload-tmp")
	if err := os.MkdirAll(uploadTmp, 0o755); err != nil {
		log.Fatalf("No se pudo crear .upload-tmp: %v", err)
	}

	gdb, err := gorm.Open(postgres.Open(cfg.DatabaseURL), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Warn),
	})
	if err != nil {
		log.Fatalf("No se pudo conectar a PostgreSQL: %v", err)
	}

	if err := gdb.AutoMigrate(
		&malcomdb.User{},
		&malcomdb.Conversation{},
		&malcomdb.UserFile{},
		&malcomdb.Payment{},
		&malcomdb.DownloadToken{},
	); err != nil {
		log.Fatalf("AutoMigrate: %v", err)
	}
	log.Println("Base de datos lista (GORM AutoMigrate).")

	userRepo := repos.NewUserRepository(gdb, cfg.FreeMessageLimit, cfg.QuotaTimezone)
	convRepo := repos.NewConversationRepository(gdb)
	paymentRepo := repos.NewPaymentRepository(gdb, cfg.FreeMessageLimit, cfg.QuotaTimezone)

	workerClient := worker.NewHTTPClient(cfg.WorkerURL)

	tokenStore := handlers.NewPersistentTokenStore(gdb)

	healthHandler := handlers.NewHealthHandler()

	uploadMaxBytes := int64(cfg.UploadMaxMB) * 1024 * 1024
	if cfg.UploadMaxMB <= 0 {
		uploadMaxBytes = 32 * 1024 * 1024
	}
	chatHandler := handlers.NewChatHandler(userRepo, convRepo, workerClient, cfg.DataDir, tokenStore, cfg.EnablePublicData, uploadMaxBytes, cfg.DevForcePremium)
	if cfg.DevForcePremium {
		log.Println("⚠️  DEV_FORCE_PREMIUM ACTIVO: todos los chats actuarán como premium. Desactivar en producción.")
	}
	billingHandler := handlers.NewBillingHandler(
		userRepo,
		paymentRepo,
		cfg.WompiEventSecret,
		cfg.BoldWebhookSecret,
		cfg.BoldAPIKey,
		cfg.BoldIntegritySecret,
		cfg.PremiumAmountCOP,
		"https://www.powerupsagencia.com/portal-premium",
	)
	downloadHandler := handlers.NewDownloadHandler(tokenStore, userRepo, cfg.DataDir)
	dashboardHandler := handlers.NewDashboardHandler(tokenStore, userRepo, cfg.DataDir, cfg.DevForcePremium)

	router := gin.Default()
	router.MaxMultipartMemory = uploadMaxBytes

	router.Use(middleware.DefaultSecurityHeaders())
	router.Use(middleware.BuildCORS(cfg.CORSAllowedOrigins))
	if len(cfg.CORSAllowedOrigins) > 0 {
		log.Printf("CORS restringido a: %v", cfg.CORSAllowedOrigins)
	}

	if cfg.EnablePublicData {
		router.Static("/data", cfg.DataDir)
		log.Println("ENABLE_PUBLIC_DATA=true: /data expuesto sin token (solo desarrollo).")
	}

	router.GET("/download/:token", downloadHandler.Download)
	router.GET("/dashboard", middleware.DashboardPageSecurity(cfg.CSPFrameAncestors), dashboardHandler.Page)

	router.GET("/health", healthHandler.HealthCheck)

	chatRL := middleware.ChatRateLimit(cfg.ChatRateLimitRPS, cfg.ChatRateLimitBurst)
	if cfg.ChatRateLimitRPS > 0 {
		log.Printf("Rate limit chat: %.1f r/s burst=%d por IP", cfg.ChatRateLimitRPS, cfg.ChatRateLimitBurst)
	}

	v1 := router.Group("/api/v1")
	v1.Use(middleware.APIFrameDeny())
	{
		v1.POST("/chat", chatRL, chatHandler.Chat)
		v1.POST("/chat/upload", chatRL, chatHandler.UploadFile)
		v1.POST("/chat/token/refresh", chatRL, chatHandler.DashboardTokenRefresh)
		v1.GET("/chat/:chat_id/credits", chatHandler.GetCredits)
		v1.GET("/dashboard/session/:token", dashboardHandler.SessionJSON)

		v1.GET("/billing/status", billingHandler.BillingStatus)
		v1.GET("/billing/bold-checkout", billingHandler.BoldCheckout)
		v1.POST("/billing/webhook", middleware.BillingWebhookAuth(cfg.BillingWebhookSecret), billingHandler.PaymentWebhook)
		v1.POST("/billing/bold-webhook", billingHandler.BoldWebhook)
		v1.POST("/billing/link-email", billingHandler.LinkEmail)
	}
	if cfg.BillingWebhookSecret != "" {
		log.Println("BILLING_WEBHOOK_SECRET activo: el webhook exige cabecera compartida.")
	}
	if cfg.WompiEventSecret != "" {
		log.Println("WOMPI_EVENT_SECRET activo: se valida el checksum de eventos Wompi.")
	}
	if cfg.BoldWebhookSecret != "" {
		log.Println("BOLD_WEBHOOK_SECRET activo: se valida X-Bold-Signature en eventos Bold.")
	}
	log.Printf("Premium Bold: monto esperado $%d COP (PREMIUM_AMOUNT_COP)", cfg.PremiumAmountCOP)
	if strings.TrimSpace(cfg.CSPFrameAncestors) == "" {
		log.Println("Aviso: CSP_FRAME_ANCESTORS vacío — frame-ancestors solo incluye 'self'. " +
			"Para embeber /dashboard desde WordPress u otro sitio, define orígenes en CSP_FRAME_ANCESTORS.")
	}

	log.Printf("InsightFlow Malcom API en :%s | worker=%s | data=%s", cfg.Port, cfg.WorkerURL, cfg.DataDir)
	if err := router.Run(":" + cfg.Port); err != nil {
		log.Fatalf("Error arrancando el servidor: %v", err)
	}
}
