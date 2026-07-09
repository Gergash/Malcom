// Package db defines GORM models mirroring app/database/models.py (PostgreSQL).
package db

import "time"

// User — identidad (email + chat_id), plan premium, contador (paywall) y branding premium.
type User struct {
	ID               uint `gorm:"primaryKey"`
	ChatID           *int64 `gorm:"uniqueIndex"`
	Email            *string `gorm:"uniqueIndex;size:320"`
	Username         *string `gorm:"size:255"`
	IsPremium        bool `gorm:"not null;default:false"`
	MessageCount     int  `gorm:"not null;default:0"` // lifetime total (analytics)
	MessagesToday    int  `gorm:"not null;default:0"` // cupo diario v2
	QuotaDate        *time.Time `gorm:"type:date"`      // día calendario del contador (TZ quota)
	FreeMessageLimit int  `gorm:"not null;default:15"`
	CreatedAt        time.Time
	UpdatedAt        time.Time
	PremiumSince     *time.Time
	// Último JSON envuelto {"echarts_option":...} para reemitir token tras consumo one-shot.
	LastDashboardJSON *string `gorm:"column:last_dashboard_json;type:text"`
	// Branding premium — null = usar defaults del tier; solo aplica cuando is_premium = true.
	BrandingColor    *string `gorm:"column:branding_color;size:7"`
	BrandingColorSec *string `gorm:"column:branding_color_sec;size:7"`
	BrandingFontBody *int    `gorm:"column:branding_font_body"`
	BrandingFontTitle *int   `gorm:"column:branding_font_title"`
	BrandingCharts   *string `gorm:"column:branding_charts;size:256"` // JSON: ["bars","heatmap"]
}

// Conversation — historial de mensajes por chat_id.
type Conversation struct {
	ID        uint `gorm:"primaryKey"`
	ChatID    int64 `gorm:"index;not null"`
	Role      string `gorm:"size:10;not null"`
	Content   string `gorm:"type:text;not null"`
	CreatedAt time.Time
}

// UserFile — metadatos de archivos en data/{chat_id}/ (paridad con SQLAlchemy).
type UserFile struct {
	ID            uint `gorm:"primaryKey"`
	UserID        uint `gorm:"index;not null"`
	ChatID        int64 `gorm:"index;not null"`
	Filename      string `gorm:"size:512;not null"`
	FileType      string `gorm:"size:20;not null;default:other"`
	FilePath      string `gorm:"size:1024;not null"`
	SizeBytes     *int
	Indexed       bool `gorm:"not null;default:false"`
	IndexedChunks int  `gorm:"not null;default:0"`
	CreatedAt     time.Time
}

// DownloadToken — token de descarga persistido en PostgreSQL (P2: reemplaza memoria).
// Válido hasta expires_at; used_at registra primera descarga (auditoría).
// PayloadJSON: sesión dashboard (ECharts) u otros JSON efímeros; FilePath vacío si solo hay payload.
type DownloadToken struct {
	ID           uint      `gorm:"primaryKey"`
	Token        string    `gorm:"uniqueIndex;size:64;not null"`
	FilePath     string    `gorm:"size:1024"` // vacío si el recurso es solo payload_json
	PayloadJSON  *string   `gorm:"column:payload_json;type:text"`
	ChatID       int64     `gorm:"index;not null"`
	ResourceType string    `gorm:"size:20;not null;default:report"` // pdf | excel | chart | dashboard
	ExpiresAt    time.Time `gorm:"not null;index"`
	UsedAt       *time.Time
	CreatedAt    time.Time
}

// Payment — registro de webhooks de pago.
type Payment struct {
	ID          uint `gorm:"primaryKey"`
	UserID      *uint `gorm:"index"`
	Reference   string `gorm:"uniqueIndex;size:256;not null"`
	AmountCOP   int    `gorm:"column:amount_cop;not null"`
	Status      string `gorm:"size:20;not null;default:pending"`
	Provider    string `gorm:"size:50;not null;default:wompi"`
	PayerEmail  *string `gorm:"size:320;index"`
	PayerChatID *int64
	PaidAt      *time.Time
	CreatedAt   time.Time
}
