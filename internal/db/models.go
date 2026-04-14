// Package db defines GORM models mirroring app/database/models.py (PostgreSQL).
package db

import "time"

// User — identidad (email + chat_id), plan premium y contador (paywall).
type User struct {
	ID               uint `gorm:"primaryKey"`
	ChatID           *int64 `gorm:"uniqueIndex"`
	Email            *string `gorm:"uniqueIndex;size:320"`
	Username         *string `gorm:"size:255"`
	IsPremium        bool `gorm:"not null;default:false"`
	MessageCount     int  `gorm:"not null;default:0"`
	FreeMessageLimit int  `gorm:"not null;default:7"`
	CreatedAt        time.Time
	UpdatedAt        time.Time
	PremiumSince     *time.Time
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
