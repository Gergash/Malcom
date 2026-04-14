// Package repos implements PostgreSQL persistence with GORM.
package repos

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/powerups/insightflow-malcom/internal/db"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"gorm.io/gorm"
)

type userRepo struct {
	db        *gorm.DB
	freeLimit int
}

// NewUserRepository builds a UserRepository backed by GORM.
func NewUserRepository(gdb *gorm.DB, freeMessageLimit int) repositories.UserRepository {
	return &userRepo{db: gdb, freeLimit: freeMessageLimit}
}

func lookupUserByChatID(ctx context.Context, tx *gorm.DB, chatID int64) (*db.User, error) {
	var u db.User
	err := tx.WithContext(ctx).Where("chat_id = ?", chatID).First(&u).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &u, nil
}

func lookupUserByEmail(ctx context.Context, tx *gorm.DB, email string) (*db.User, error) {
	norm := strings.ToLower(strings.TrimSpace(email))
	var u db.User
	err := tx.WithContext(ctx).Where("email = ?", norm).First(&u).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &u, nil
}

// getOrCreateUserTx finds or creates a user (chat_id y/o email). Al menos uno debe estar presente.
func getOrCreateUserTx(tx *gorm.DB, ctx context.Context, freeLimit int, chatID *int64, username *string, email *string) (*db.User, error) {
	var user *db.User
	var err error

	if chatID != nil {
		user, err = lookupUserByChatID(ctx, tx, *chatID)
		if err != nil {
			return nil, err
		}
	}

	if user == nil && email != nil && strings.TrimSpace(*email) != "" {
		norm := strings.ToLower(strings.TrimSpace(*email))
		user, err = lookupUserByEmail(ctx, tx, norm)
		if err != nil {
			return nil, err
		}
		if user != nil && chatID != nil && user.ChatID == nil {
			user.ChatID = chatID
			user.UpdatedAt = time.Now().UTC()
			if err := tx.WithContext(ctx).Save(user).Error; err != nil {
				return nil, err
			}
		}
	}

	if user != nil {
		return user, nil
	}

	u := db.User{
		ChatID:           chatID,
		FreeMessageLimit: freeLimit,
		MessageCount:     0,
		IsPremium:        false,
	}
	if email != nil && strings.TrimSpace(*email) != "" {
		e := strings.ToLower(strings.TrimSpace(*email))
		u.Email = &e
	}
	if username != nil {
		u.Username = username
	}
	if err := tx.WithContext(ctx).Create(&u).Error; err != nil {
		return nil, err
	}
	return &u, nil
}

func userToState(u *db.User) *repositories.UserState {
	var chat *int64
	if u.ChatID != nil {
		chat = u.ChatID
	}
	st := &repositories.UserState{
		ChatID:           chat,
		Email:            u.Email,
		Username:         u.Username,
		MessageCount:     u.MessageCount,
		IsPremium:        u.IsPremium,
		FreeMessageLimit: u.FreeMessageLimit,
		PremiumSince:     formatPremiumSince(u.PremiumSince),
	}
	remaining := u.FreeMessageLimit - u.MessageCount
	if remaining < 0 {
		remaining = 0
	}
	st.CreditsRemaining = remaining
	st.Paywall = !u.IsPremium && u.MessageCount >= u.FreeMessageLimit
	return st
}

func formatPremiumSince(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := t.UTC().Format(time.RFC3339)
	return &s
}

func userToPaymentUser(u *db.User) *repositories.PaymentUser {
	return &repositories.PaymentUser{
		ChatID:    u.ChatID,
		Email:     u.Email,
		IsPremium: u.IsPremium,
	}
}

func (r *userRepo) BumpAndCheck(ctx context.Context, chatID int64, username *string) (*repositories.UserState, error) {
	var out *repositories.UserState
	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		u, err := getOrCreateUserTx(tx, ctx, r.freeLimit, &chatID, username, nil)
		if err != nil {
			return err
		}

		if u.IsPremium {
			out = userToState(u)
			out.Paywall = false
			out.CreditsRemaining = -1
			return nil
		}

		if u.MessageCount >= u.FreeMessageLimit {
			out = userToState(u)
			out.Paywall = true
			out.CreditsRemaining = 0
			return nil
		}

		u.MessageCount++
		u.UpdatedAt = time.Now().UTC()
		if err := tx.WithContext(ctx).Save(u).Error; err != nil {
			return err
		}

		out = userToState(u)
		out.Paywall = false
		rem := u.FreeMessageLimit - u.MessageCount
		if rem < 0 {
			rem = 0
		}
		out.CreditsRemaining = rem
		return nil
	})
	return out, err
}

func (r *userRepo) GetState(ctx context.Context, chatID *int64, email *string) (*repositories.UserState, error) {
	if chatID == nil && (email == nil || strings.TrimSpace(*email) == "") {
		return nil, errors.New("se requiere chat_id o email")
	}

	var u *db.User
	var err error
	err = r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		u, err = getOrCreateUserTx(tx, ctx, r.freeLimit, chatID, nil, email)
		return err
	})
	if err != nil {
		return nil, err
	}
	return userToState(u), nil
}

func (r *userRepo) LinkEmail(ctx context.Context, chatID int64, email string) error {
	norm := strings.ToLower(strings.TrimSpace(email))
	if norm == "" {
		return errors.New("email vacío")
	}

	return r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		existing, err := lookupUserByEmail(ctx, tx, norm)
		if err != nil {
			return err
		}

		if existing != nil {
			if existing.ChatID != nil && *existing.ChatID == chatID {
				return nil
			}
			if err := tx.WithContext(ctx).
				Where("chat_id = ? AND id != ?", chatID, existing.ID).
				Delete(&db.User{}).Error; err != nil {
				return err
			}
			now := time.Now().UTC()
			if err := tx.WithContext(ctx).Model(existing).Updates(map[string]interface{}{
				"chat_id":    chatID,
				"updated_at": now,
			}).Error; err != nil {
				return err
			}
			return nil
		}

		u, err := getOrCreateUserTx(tx, ctx, r.freeLimit, &chatID, nil, nil)
		if err != nil {
			return err
		}
		u.Email = &norm
		u.UpdatedAt = time.Now().UTC()
		return tx.WithContext(ctx).Save(u).Error
	})
}

func (r *userRepo) ActivatePremium(ctx context.Context, chatID *int64, email *string) (*repositories.PaymentUser, error) {
	if chatID == nil && (email == nil || strings.TrimSpace(*email) == "") {
		return nil, errors.New("se requiere chat_id o email para activar premium")
	}

	var u *db.User
	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var err error
		u, err = getOrCreateUserTx(tx, ctx, r.freeLimit, chatID, nil, email)
		if err != nil {
			return err
		}
		if !u.IsPremium {
			now := time.Now().UTC()
			u.IsPremium = true
			u.PremiumSince = &now
			u.UpdatedAt = now
			if err := tx.WithContext(ctx).Save(u).Error; err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return userToPaymentUser(u), nil
}
