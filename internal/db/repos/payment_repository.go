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

type paymentRepo struct {
	db        *gorm.DB
	freeLimit int
}

// NewPaymentRepository registra pagos y activa premium en la misma transacción que user_repo.
func NewPaymentRepository(gdb *gorm.DB, freeMessageLimit int) repositories.PaymentRepository {
	return &paymentRepo{db: gdb, freeLimit: freeMessageLimit}
}

func normalizeEmailPtr(p *string) *string {
	if p == nil || strings.TrimSpace(*p) == "" {
		return nil
	}
	s := strings.ToLower(strings.TrimSpace(*p))
	return &s
}

func (r *paymentRepo) getByReference(ctx context.Context, tx *gorm.DB, reference string) (*db.Payment, error) {
	var p db.Payment
	err := tx.WithContext(ctx).Where("reference = ?", reference).First(&p).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (r *paymentRepo) loadUserByID(ctx context.Context, tx *gorm.DB, id uint) (*db.User, error) {
	var u db.User
	err := tx.WithContext(ctx).First(&u, id).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &u, nil
}

func (r *paymentRepo) MarkFailed(ctx context.Context, reference, provider string, amountCOP int) error {
	return r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		p, err := r.getByReference(ctx, tx, reference)
		if err != nil {
			return err
		}
		if p == nil {
			pe := &db.Payment{
				Reference: reference,
				AmountCOP: amountCOP,
				Provider:  provider,
				Status:    "failed",
			}
			return tx.WithContext(ctx).Create(pe).Error
		}
		p.Status = "failed"
		return tx.WithContext(ctx).Save(p).Error
	})
}

func (r *paymentRepo) ConfirmPayment(
	ctx context.Context,
	reference string,
	amountCOP int,
	provider string,
	payerEmail *string,
	payerChatID *int64,
) (*repositories.PaymentResult, error) {
	var result *repositories.PaymentResult

	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		p, err := r.getByReference(ctx, tx, reference)
		if err != nil {
			return err
		}

		if p != nil && p.Status == "paid" {
			var pu *repositories.PaymentUser
			if p.UserID != nil {
				u, err := r.loadUserByID(ctx, tx, *p.UserID)
				if err != nil {
					return err
				}
				if u != nil {
					pu = userToPaymentUser(u)
				}
			}
			result = &repositories.PaymentResult{User: pu, AlreadyProcessed: true}
			return nil
		}

		if p == nil {
			pe := &db.Payment{
				Reference:   reference,
				AmountCOP:   amountCOP,
				Provider:    provider,
				Status:      "pending",
				PayerEmail:  normalizeEmailPtr(payerEmail),
				PayerChatID: payerChatID,
			}
			if err := tx.WithContext(ctx).Create(pe).Error; err != nil {
				return err
			}
			p = pe
		}

		u, err := getOrCreateUserTx(tx, ctx, r.freeLimit, payerChatID, nil, payerEmail)
		if err != nil {
			return err
		}
		paidAt := time.Now().UTC()
		if !u.IsPremium {
			u.IsPremium = true
			u.PremiumSince = &paidAt
			u.UpdatedAt = paidAt
			if err := tx.WithContext(ctx).Save(u).Error; err != nil {
				return err
			}
		}

		uid := u.ID
		p.Status = "paid"
		p.UserID = &uid
		p.PaidAt = &paidAt
		if pe := normalizeEmailPtr(payerEmail); pe != nil && (p.PayerEmail == nil || *p.PayerEmail == "") {
			p.PayerEmail = pe
		}
		if payerChatID != nil && p.PayerChatID == nil {
			p.PayerChatID = payerChatID
		}
		if err := tx.WithContext(ctx).Save(p).Error; err != nil {
			return err
		}

		result = &repositories.PaymentResult{
			User:             userToPaymentUser(u),
			AlreadyProcessed: false,
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return result, nil
}
