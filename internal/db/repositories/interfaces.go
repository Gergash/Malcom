// interfaces.go: contratos de repositorio que los handlers consumen.
// Implementaciones: internal/db/repos (GORM).
package repositories

import "context"

// ── Tipos de retorno compartidos ──────────────────────────────────────────────

// UserState representa el estado completo de un usuario (créditos, plan, etc.).
// Espeja el dict que devuelve user_repo.get_state() / bump_and_check() en Python.
type UserState struct {
	ChatID            *int64
	Email             *string
	Username          *string
	MessageCount      int
	IsPremium         bool
	FreeMessageLimit  int
	CreditsRemaining  int
	Paywall           bool
	PremiumSince      *string
	BrandingColor     *string
	BrandingColorSec  *string
	BrandingFontBody  *int
	BrandingFontTitle *int
	BrandingCharts    *string // JSON string: ["bars","heatmap"]
}

// PaymentUser — información mínima del usuario retornada tras confirmar un pago.
type PaymentUser struct {
	ChatID    *int64
	Email     *string
	IsPremium bool
}

// PaymentResult — resultado de ConfirmPayment.
type PaymentResult struct {
	User             *PaymentUser
	AlreadyProcessed bool
}

// ── Interfaces de repositorio ─────────────────────────────────────────────────

// UserRepository — operaciones sobre la tabla de usuarios.
type UserRepository interface {
	// BumpAndCheck incrementa el contador de mensajes y devuelve el estado
	// actualizado del usuario (incluyendo si alcanzó el paywall).
	// Crea el usuario si no existe. Equivale a user_repo.bump_and_check().
	BumpAndCheck(ctx context.Context, chatID int64, username *string) (*UserState, error)

	// GetState devuelve el estado del usuario sin modificar ningún contador.
	// Acepta chat_id o email (al menos uno es obligatorio).
	// Equivale a user_repo.get_state().
	GetState(ctx context.Context, chatID *int64, email *string) (*UserState, error)

	// LinkEmail asocia un email permanente al chat_id de Telegram del usuario.
	// Equivale a user_repo.link_email().
	LinkEmail(ctx context.Context, chatID int64, email string) error

	// ActivatePremium activa is_premium (y premium_since) si aún no lo está.
	// Usado por el webhook de pago. Equivale a user_repo.activate_premium().
	ActivatePremium(ctx context.Context, chatID *int64, email *string) (*PaymentUser, error)
}

// ConversationRepository — operaciones sobre el historial de conversación.
type ConversationRepository interface {
	// AddMessage persiste un mensaje (role: "user" | "assistant") en el historial.
	// Equivale a conv_repo.add_message().
	AddMessage(ctx context.Context, chatID int64, role, content string) error
}

// PaymentRepository — operaciones sobre pagos (Wompi/PSE).
type PaymentRepository interface {
	// MarkFailed registra un pago fallido sin activar el plan premium.
	// Equivale a payment_repo.mark_failed().
	MarkFailed(ctx context.Context, reference, provider string, amountCOP int) error

	// ConfirmPayment procesa un pago aprobado: activa is_premium en el usuario.
	// Es idempotente: si ya fue procesado, AlreadyProcessed = true.
	// Equivale a payment_repo.confirm_payment().
	ConfirmPayment(
		ctx context.Context,
		reference string,
		amountCOP int,
		provider string,
		payerEmail *string,
		payerChatID *int64,
	) (*PaymentResult, error)
}
