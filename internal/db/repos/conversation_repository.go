package repos

import (
	"context"

	"github.com/powerups/insightflow-malcom/internal/db"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"gorm.io/gorm"
)

type conversationRepo struct {
	db *gorm.DB
}

// NewConversationRepository builds a ConversationRepository.
func NewConversationRepository(gdb *gorm.DB) repositories.ConversationRepository {
	return &conversationRepo{db: gdb}
}

func (r *conversationRepo) AddMessage(ctx context.Context, chatID int64, role, content string) error {
	msg := db.Conversation{
		ChatID:  chatID,
		Role:    role,
		Content: content,
	}
	return r.db.WithContext(ctx).Create(&msg).Error
}
