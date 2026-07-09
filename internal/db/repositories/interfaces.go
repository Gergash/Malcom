// interfaces.go: contratos de repositorio que los handlers consumen.
// Implementaciones: internal/db/repos (GORM).
package repositories

import (
	"context"

	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
)

// ── Tipos de retorno compartidos ──────────────────────────────────────────────

// UserState representa el estado completo de un usuario (créditos, plan, etc.).
// Espeja el dict que devuelve user_repo.get_state() / bump_and_check() en Python.
type UserState struct {
	ChatID            *int64
	Email             *string
	Username          *string
	MessagesToday      int
	MessageCount       int // messages_today expuesto como message_count (compat widget)
	LifetimeMessages   int // message_count acumulado de por vida
	IsPremium         bool
	FreeMessageLimit  int
	CreditsRemaining  int
	Paywall           bool
	PremiumSince      *string
	QuotaResetsAt     *string // RFC3339 UTC — próximo reset del cupo diario
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

	// IsPremiumForChat consulta si existe un usuario con chat_id y está en premium.
	// No crea filas (adecuado para validar tokens de dashboard/descarga).
	IsPremiumForChat(ctx context.Context, chatID int64) (bool, error)

	// SaveLastDashboardSnapshot guarda el JSON de sesión ECharts (mismo cuerpo que StorePayload).
	SaveLastDashboardSnapshot(ctx context.Context, chatID int64, payloadJSON string) error
	// GetLastDashboardSnapshot devuelve "" si no hay snapshot.
	GetLastDashboardSnapshot(ctx context.Context, chatID int64) (string, error)

	// GetUserIDForChat devuelve el ID de fila users o nil si no existe.
	GetUserIDForChat(ctx context.Context, chatID int64) (*uint, error)
	// RecordUploadedFile inserta auditoría en user_files (tras ingestión exitosa).
	RecordUploadedFile(ctx context.Context, file *malcomdb.UserFile) error
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
