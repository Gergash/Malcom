// billing_handler.go: endpoints de facturación e integración con WordPress.
// Reemplaza app/api/routes/billing.py
//
// GET  /api/v1/billing/status      → estado para botones del frontend
// POST /api/v1/billing/webhook     → confirmación de pago (Wompi/PSE)
// POST /api/v1/billing/link-email  → vincula email a chat_id de Telegram
package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"github.com/powerups/insightflow-malcom/internal/payment/bold"
	"github.com/powerups/insightflow-malcom/internal/payment/wompi"
)

// BillingHandler agrupa las dependencias de los endpoints de facturación.
type BillingHandler struct {
	userRepo          repositories.UserRepository
	paymentRepo       repositories.PaymentRepository
	wompiEventSecret  string
	boldWebhookSecret string
	premiumAmountCOP  int
}

// NewBillingHandler construye el handler con sus dependencias.
func NewBillingHandler(
	userRepo repositories.UserRepository,
	paymentRepo repositories.PaymentRepository,
	wompiEventSecret string,
	boldWebhookSecret string,
	premiumAmountCOP int,
) *BillingHandler {
	return &BillingHandler{
		userRepo:          userRepo,
		paymentRepo:       paymentRepo,
		wompiEventSecret:  wompiEventSecret,
		boldWebhookSecret: boldWebhookSecret,
		premiumAmountCOP:  premiumAmountCOP,
	}
}

// ── GET /api/v1/billing/status ────────────────────────────────────────────────

// BillingStatus devuelve el estado del plan del usuario para que WordPress
// decida qué botones mostrar (Upgrade / Generar PDF / Paywall).
//
// Requiere al menos uno: ?chat_id= o ?email=
func (h *BillingHandler) BillingStatus(c *gin.Context) {
	chatIDParam := c.Query("chat_id")
	emailParam := c.Query("email")

	if chatIDParam == "" && emailParam == "" {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
			Detail: "Se requiere al menos uno de: chat_id, email",
		})
		return
	}

	var chatID *int64
	if chatIDParam != "" {
		var id int64
		if _, err := fmt.Sscanf(chatIDParam, "%d", &id); err != nil {
			c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
				Detail: "chat_id debe ser un entero válido",
			})
			return
		}
		chatID = &id
	}

	var email *string
	if emailParam != "" {
		email = &emailParam
	}

	ctx := c.Request.Context()
	state, err := h.userRepo.GetState(ctx, chatID, email)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error consultando estado: %v", err),
		})
		return
	}

	plan := "free"
	if state.IsPremium {
		plan = "premium"
	}

	c.JSON(http.StatusOK, types.BillingStatusResponse{
		ChatID:            state.ChatID,
		Email:             state.Email,
		IsPremium:         state.IsPremium,
		Plan:              plan,
		MessageCount:      state.MessageCount,
		CreditsRemaining:  state.CreditsRemaining,
		ShowUpgradeButton: !state.IsPremium,
		ShowPDFButton:     state.IsPremium,
		PaywallActive:     state.Paywall,
		PremiumSince:      state.PremiumSince,
	})
}

// ── POST /api/v1/billing/webhook ──────────────────────────────────────────────

// PaymentWebhook recibe la notificación de pago del PSP (Wompi, PSE u otro).
//
// Flujo (espeja billing.py):
//
//	APPROVED → registra el pago como pagado + activa is_premium en el usuario.
//	DECLINED / ERROR / VOIDED → registra el pago como fallido.
//
// Es idempotente: si la referencia ya fue procesada responde AlreadyProcessed=true.
func (h *BillingHandler) PaymentWebhook(c *gin.Context) {
	raw, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "No se pudo leer el cuerpo."})
		return
	}
	c.Request.Body = io.NopCloser(bytes.NewReader(raw))

	if strings.TrimSpace(h.wompiEventSecret) != "" {
		chk := c.GetHeader("X-Event-Checksum")
		if !wompi.VerifyEventChecksum(raw, chk, h.wompiEventSecret) {
			slog.Warn("billing webhook: checksum Wompi inválido o evento sin firma")
			c.JSON(http.StatusForbidden, types.ErrorResponse{Detail: "Firma de evento inválida."})
			return
		}
	}

	ref, wStatus, amountCents, emailStr, mapped := wompi.MapTransactionWebhook(raw)
	var req types.PaymentWebhookRequest
	if mapped {
		req.Reference = ref
		req.Status = wStatus
		req.AmountInCents = amountCents
		req.Provider = "wompi"
		if emailStr != "" {
			req.PayerEmail = &emailStr
		}
	} else {
		if err := json.Unmarshal(raw, &req); err != nil {
			c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: err.Error()})
			return
		}
		if req.Provider == "" {
			req.Provider = "wompi"
		}
	}

	ctx := c.Request.Context()

	approvedStatuses := map[string]bool{
		"APPROVED":  true,
		"COMPLETED": true,
	}

	if !approvedStatuses[strings.ToUpper(req.Status)] {
		// Pago fallido — registrar sin activar premium
		if err := h.paymentRepo.MarkFailed(ctx, req.Reference, req.Provider, req.AmountInCents); err != nil {
			c.JSON(http.StatusInternalServerError, types.ErrorResponse{
				Detail: fmt.Sprintf("Error registrando pago fallido: %v", err),
			})
			return
		}
		c.JSON(http.StatusOK, types.PaymentWebhookResponse{
			Success:   false,
			Message:   fmt.Sprintf("Pago con estado '%s' registrado.", req.Status),
			Reference: req.Reference,
		})
		return
	}

	// Pago aprobado
	result, err := h.paymentRepo.ConfirmPayment(
		ctx,
		req.Reference,
		req.AmountInCents,
		req.Provider,
		req.PayerEmail,
		req.PayerChatID,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error confirmando pago: %v", err),
		})
		return
	}

	msg := "Premium activado."
	if result.AlreadyProcessed {
		msg = "Pago ya procesado anteriormente."
	}

	resp := types.PaymentWebhookResponse{
		Success:          true,
		AlreadyProcessed: result.AlreadyProcessed,
		Message:          msg,
		Reference:        req.Reference,
	}
	if result.User != nil {
		resp.UserEmail = result.User.Email
		resp.UserChatID = result.User.ChatID
		resp.IsPremium = result.User.IsPremium
	}

	c.JSON(http.StatusOK, resp)
}

// ── POST /api/v1/billing/bold-webhook ─────────────────────────────────────────

// BoldWebhook recibe notificaciones de Bold cuando cambia el estado de una transacción.
// Si la firma es válida, el monto coincide con PREMIUM_AMOUNT_COP y la transacción
// fue exitosa, registra el pago (idempotente) y activa premium para el chat_id
// recibido en metadata, description, reference u order_id.
func (h *BillingHandler) BoldWebhook(c *gin.Context) {
	raw, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "No se pudo leer el cuerpo."})
		return
	}

	signature := c.GetHeader("X-Bold-Signature")
	if !bold.VerifySignature(raw, signature, h.boldWebhookSecret) {
		slog.Warn(
			"bold webhook: firma inválida",
			slog.String("remote_ip", c.ClientIP()),
			slog.Bool("signature_present", strings.TrimSpace(signature) != ""),
		)
		c.JSON(http.StatusUnauthorized, types.ErrorResponse{Detail: "Firma Bold inválida."})
		return
	}

	event := bold.ParseEvent(raw)
	if !event.IsSuccessful() {
		ref := strings.TrimSpace(event.Reference)
		if ref != "" {
			amountCOP := bold.NormalizeAmountCOP(event.AmountCents)
			if err := h.paymentRepo.MarkFailed(c.Request.Context(), ref, "bold", amountCOP); err != nil {
				slog.Warn("bold webhook: error registrando pago fallido", slog.String("error", err.Error()))
			}
		}
		slog.Info(
			"bold webhook: evento no exitoso registrado",
			slog.String("event_type", event.Type),
			slog.String("status", event.Status),
			slog.String("reference", event.Reference),
		)
		c.JSON(http.StatusOK, gin.H{
			"success":   false,
			"message":   "Evento Bold recibido sin activación premium.",
			"event":     event.Type,
			"status":    event.Status,
			"reference": event.Reference,
		})
		return
	}

	if !bold.AmountMatchesPremium(event.AmountCents, h.premiumAmountCOP) {
		got := bold.NormalizeAmountCOP(event.AmountCents)
		slog.Warn(
			"bold webhook: monto inválido",
			slog.Int("amount_cop", got),
			slog.Int("expected_cop", h.premiumAmountCOP),
			slog.String("reference", event.Reference),
		)
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
			Detail: fmt.Sprintf(
				"Monto inválido: se esperaban $%d COP, recibido $%d COP.",
				h.premiumAmountCOP,
				got,
			),
		})
		return
	}

	if event.ChatID == nil {
		slog.Warn(
			"bold webhook: pago exitoso sin chat_id",
			slog.String("event_type", event.Type),
			slog.String("status", event.Status),
			slog.String("reference", event.Reference),
		)
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
			Detail: "No se encontró chat_id en metadata, description o reference.",
		})
		return
	}

	ref := strings.TrimSpace(event.Reference)
	if ref == "" {
		ref = fmt.Sprintf("bold-chat-%d", *event.ChatID)
	}
	amountCOP := bold.NormalizeAmountCOP(event.AmountCents)

	result, err := h.paymentRepo.ConfirmPayment(
		c.Request.Context(),
		ref,
		amountCOP,
		"bold",
		nil,
		event.ChatID,
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error confirmando pago Bold: %v", err),
		})
		return
	}

	msg := "Premium activado por Bold."
	if result.AlreadyProcessed {
		msg = "Pago Bold ya procesado anteriormente."
	}

	slog.Info(
		"bold webhook: premium activado",
		slog.Int64("chat_id", *event.ChatID),
		slog.String("reference", ref),
		slog.String("event_type", event.Type),
		slog.String("status", event.Status),
		slog.Bool("already_processed", result.AlreadyProcessed),
	)

	resp := types.PaymentWebhookResponse{
		Success:          true,
		AlreadyProcessed: result.AlreadyProcessed,
		Message:          msg,
		Reference:        ref,
		IsPremium:        true,
	}
	if result.User != nil {
		resp.UserChatID = result.User.ChatID
		resp.UserEmail = result.User.Email
		resp.IsPremium = result.User.IsPremium
	}
	c.JSON(http.StatusOK, resp)
}

// ── POST /api/v1/billing/link-email ──────────────────────────────────────────

// LinkEmail asocia el email del usuario a su chat_id de Telegram.
// Necesario para que el webhook de pago pueda activar el premium
// aunque no llegue el chat_id en el payload de Wompi.
func (h *BillingHandler) LinkEmail(c *gin.Context) {
	var body struct {
		ChatID int64  `json:"chat_id" validate:"required"`
		Email  string `json:"email"   validate:"required,email"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: err.Error()})
		return
	}

	ctx := c.Request.Context()

	if err := h.userRepo.LinkEmail(ctx, body.ChatID, body.Email); err != nil {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{
			Detail: fmt.Sprintf("No se pudo vincular el email: %v", err),
		})
		return
	}

	state, err := h.userRepo.GetState(ctx, &body.ChatID, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error consultando estado tras vincular: %v", err),
		})
		return
	}

	c.JSON(http.StatusOK, types.CreditStateResponse{
		ChatID:           state.ChatID,
		Email:            state.Email,
		Username:         state.Username,
		MessageCount:     state.MessageCount,
		IsPremium:        state.IsPremium,
		FreeMessageLimit: state.FreeMessageLimit,
		CreditsRemaining: state.CreditsRemaining,
		Paywall:          state.Paywall,
		PremiumSince:     state.PremiumSince,
	})
}
