// types.go: structs de Go para request/response del API.
// Reemplaza app/api/schemas.py (modelos Pydantic).
package types

// ── Chat ──────────────────────────────────────────────────────────────────────

// ReportConfig — estilo del informe definido por PowerUps antes de generarlo.
// Guía narrativa (Thick Data) y parámetros visuales para PDF/Excel.
type ReportConfig struct {
	PrimaryColor       string   `json:"primary_color"`
	SecondaryColor     string   `json:"secondary_color"`
	FontSizeBody       int      `json:"font_size_body"   validate:"min=6,max=24"`
	FontSizeTitles     int      `json:"font_size_titles" validate:"min=8,max=36"`
	StakeholderProfile string   `json:"stakeholder_profile"`
	LanguageStyle      string   `json:"language_style"`
	Dialect            string   `json:"dialect"`
	// Campos de tier — Go los inyecta desde la DB; el frontend NO debe enviarlos.
	Tier       string   `json:"tier"`        // "free" | "premium"
	ChartTypes []string `json:"chart_types"` // ej. ["bars"] | ["bars","heatmap","pie","treemap"]
}

// ChatRequest — payload de POST /api/v1/chat.
type ChatRequest struct {
	ChatID       int64         `json:"chat_id"   validate:"required"`
	Message      string        `json:"message"   validate:"required,min=1"`
	Username     *string       `json:"username,omitempty"`
	ReportConfig *ReportConfig `json:"report_config,omitempty"`
}

// ArtifactInfo — entregable premium (gráfica, PDF o Excel) con URL tokenizada y etiqueta.
type ArtifactInfo struct {
	Type  string `json:"type"`  // "chart" | "pdf" | "excel"
	URL   string `json:"url"`
	Label string `json:"label"`
}

// ChatResponse — respuesta de POST /api/v1/chat.
type ChatResponse struct {
	Response         string  `json:"response"`
	HasPDF           bool    `json:"has_pdf"`
	HasExcel         bool    `json:"has_excel"`
	HasChart         bool    `json:"has_chart"`
	Paywall          bool    `json:"paywall"`
	CreditsRemaining int     `json:"credits_remaining"`
	ImageURL         *string `json:"image_url"`
	// Descarga de reporte: URL temporal con token (válida 30 min) y etiqueta para el botón.
	DownloadURL   *string `json:"download_url,omitempty"`
	DownloadLabel string  `json:"download_label,omitempty"`
	// P5: colección multi-artefacto para premium (gráficas adicionales + descargas).
	ChartURLs []string       `json:"chart_urls,omitempty"` // todas las URLs de gráficas, incluye la primaria
	Artifacts []ArtifactInfo `json:"artifacts,omitempty"`  // colección completa para el widget
}

// ── Upload ────────────────────────────────────────────────────────────────────

// UploadResponse — respuesta de POST /api/v1/chat/upload.
type UploadResponse struct {
	ChatID    int64   `json:"chat_id"`
	Filename  string  `json:"filename"`
	SavedPath string  `json:"saved_path"`
	Indexed   bool    `json:"indexed"`
	Chunks    int     `json:"chunks"`
	Message   string  `json:"message"`
	Error     *string `json:"error,omitempty"`
}

// ── Credits ───────────────────────────────────────────────────────────────────

// CreditStateResponse — respuesta de GET /api/v1/chat/{chat_id}/credits.
type CreditStateResponse struct {
	ChatID           *int64  `json:"chat_id"`
	Email            *string `json:"email"`
	Username         *string `json:"username"`
	MessageCount     int     `json:"message_count"`
	IsPremium        bool    `json:"is_premium"`
	FreeMessageLimit int     `json:"free_message_limit"`
	CreditsRemaining int     `json:"credits_remaining"`
	Paywall          bool    `json:"paywall"`
	PremiumSince     *string `json:"premium_since,omitempty"`
}

// ── Billing ───────────────────────────────────────────────────────────────────

// BillingStatusResponse — respuesta de GET /api/v1/billing/status.
// El frontend WordPress la consulta para decidir qué botones mostrar.
type BillingStatusResponse struct {
	ChatID            *int64  `json:"chat_id"`
	Email             *string `json:"email"`
	IsPremium         bool    `json:"is_premium"`
	Plan              string  `json:"plan"` // "free" | "premium"
	MessageCount      int     `json:"message_count"`
	CreditsRemaining  int     `json:"credits_remaining"`
	ShowUpgradeButton bool    `json:"show_upgrade_button"` // true si no es premium
	ShowPDFButton     bool    `json:"show_pdf_button"`     // true si es premium
	PaywallActive     bool    `json:"paywall_active"`      // true si agotó mensajes gratis
	PremiumSince      *string `json:"premium_since,omitempty"`
}

// PaymentWebhookRequest — payload de POST /api/v1/billing/webhook (Wompi/PSE).
type PaymentWebhookRequest struct {
	Reference     string  `json:"reference"      validate:"required"`
	Status        string  `json:"status"         validate:"required"` // APPROVED | DECLINED | ERROR | VOIDED
	AmountInCents int     `json:"amount_in_cents" validate:"required"`
	Provider      string  `json:"provider"`
	PayerEmail    *string `json:"payer_email,omitempty"`
	PayerChatID   *int64  `json:"payer_chat_id,omitempty"`
}

// PaymentWebhookResponse — respuesta de POST /api/v1/billing/webhook.
type PaymentWebhookResponse struct {
	Success          bool    `json:"success"`
	AlreadyProcessed bool    `json:"already_processed"`
	Message          string  `json:"message"`
	Reference        string  `json:"reference"`
	UserEmail        *string `json:"user_email,omitempty"`
	UserChatID       *int64  `json:"user_chat_id,omitempty"`
	IsPremium        bool    `json:"is_premium"`
}

// ── Health ────────────────────────────────────────────────────────────────────

// HealthResponse — respuesta de GET /health.
type HealthResponse struct {
	Status  string `json:"status"`
	Service string `json:"service"`
	Version string `json:"version"`
}

// ── Error ─────────────────────────────────────────────────────────────────────

// ErrorResponse — respuesta de error estándar (espeja el formato de FastAPI).
type ErrorResponse struct {
	Detail string `json:"detail"`
}
