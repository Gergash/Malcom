// main.go: punto de entrada del servidor InsightFlow Malcom API (Go).
package main

import (
	"log"
	"os"
	"path/filepath"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/handlers"
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

	userRepo := repos.NewUserRepository(gdb, cfg.FreeMessageLimit)
	convRepo := repos.NewConversationRepository(gdb)
	paymentRepo := repos.NewPaymentRepository(gdb, cfg.FreeMessageLimit)

	workerClient := worker.NewHTTPClient(cfg.WorkerURL)

	tokenStore := handlers.NewPersistentTokenStore(gdb)

	healthHandler := handlers.NewHealthHandler()
	chatHandler := handlers.NewChatHandler(userRepo, convRepo, workerClient, cfg.DataDir, tokenStore, cfg.EnablePublicData)
	billingHandler := handlers.NewBillingHandler(userRepo, paymentRepo)
	downloadHandler := handlers.NewDownloadHandler(tokenStore)
	dashboardHandler := handlers.NewDashboardHandler(tokenStore)

	router := gin.Default()

	// CORS: el widget en WordPress y ngrok usan otro origen; credenciales omitidas en fetch del widget.
	corsCfg := cors.DefaultConfig()
	corsCfg.AllowAllOrigins = true
	corsCfg.AllowCredentials = false
	corsCfg.AllowMethods = []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
	corsCfg.AllowHeaders = []string{
		"Origin", "Content-Type", "Accept", "Authorization", "ngrok-skip-browser-warning",
	}
	router.Use(cors.New(corsCfg))

	if cfg.EnablePublicData {
		router.Static("/data", cfg.DataDir)
		log.Println("ENABLE_PUBLIC_DATA=true: /data expuesto sin token (solo desarrollo).")
	}

	// Descarga (reportes) y vista de gráficas cuando /data está cerrado: token efímero (TTL 30 min).
	router.GET("/download/:token", downloadHandler.Download)
	// Dashboard premium (ECharts): misma base pública que el API (proxy o dominio único).
	router.GET("/dashboard", dashboardHandler.Page)

	router.GET("/health", healthHandler.HealthCheck)

	v1 := router.Group("/api/v1")
	{
		v1.POST("/chat", chatHandler.Chat)
		v1.POST("/chat/upload", chatHandler.UploadFile)
		v1.GET("/chat/:chat_id/credits", chatHandler.GetCredits)
		v1.GET("/dashboard/session/:token", dashboardHandler.SessionJSON)

		v1.GET("/billing/status", billingHandler.BillingStatus)
		v1.POST("/billing/webhook", billingHandler.PaymentWebhook)
		v1.POST("/billing/link-email", billingHandler.LinkEmail)
	}

	log.Printf("InsightFlow Malcom API en :%s | worker=%s | data=%s", cfg.Port, cfg.WorkerURL, cfg.DataDir)
	if err := router.Run(":" + cfg.Port); err != nil {
		log.Fatalf("Error arrancando el servidor: %v", err)
	}
}
