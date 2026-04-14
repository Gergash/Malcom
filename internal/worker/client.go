// client.go: cliente HTTP para comunicarse con el Worker Python (Orchestrator).
// Go delega toda la lógica de IA/análisis a este servicio ligero.
// Usa Resty como cliente HTTP.
package worker

import (
	"context"
	"fmt"

	"github.com/go-resty/resty/v2"
	"github.com/powerups/insightflow-malcom/internal/api/types"
)

// ── Tipos de retorno ──────────────────────────────────────────────────────────

// ProcessResult — resultado que el Worker Python retorna tras procesar un mensaje.
type ProcessResult struct {
	Response  string  `json:"response"`
	HasPDF    bool    `json:"has_pdf"`
	HasExcel  bool    `json:"has_excel"`
	HasChart  bool    `json:"has_chart"`
	ChartPath string  `json:"chart_path"` // ruta en disco, si existe
}

// IngestResult — resultado que el Worker Python retorna tras ingestar un archivo.
type IngestResult struct {
	SavedPath string  `json:"saved_path"`
	Indexed   bool    `json:"indexed"`
	Chunks    int     `json:"chunks"`
	Message   string  `json:"message"`
	Error     *string `json:"error,omitempty"`
}

// ── Payloads de petición al Worker ────────────────────────────────────────────

type processRequest struct {
	ChatID       int64                `json:"chat_id"`
	Message      string               `json:"message"`
	ReportConfig *types.ReportConfig  `json:"report_config,omitempty"`
}

type ingestRequest struct {
	ChatID   int64  `json:"chat_id"`
	TmpPath  string `json:"tmp_path"`
	Filename string `json:"filename"`
}

// ── Interfaz ──────────────────────────────────────────────────────────────────

// Client define las operaciones que Go delega al Worker Python.
type Client interface {
	// ProcessMessage envía el mensaje del usuario al Orchestrator Python
	// y devuelve la respuesta estructurada del agente.
	ProcessMessage(ctx context.Context, chatID int64, message string, reportConfig *types.ReportConfig) (*ProcessResult, error)

	// IngestFile envía la ruta de un archivo temporal al Worker para que lo
	// indexe/almacene y devuelve el resultado de la ingestión.
	IngestFile(ctx context.Context, chatID int64, tmpPath, filename string) (*IngestResult, error)
}

// ── Implementación HTTP (Resty) ───────────────────────────────────────────────

// HTTPClient implementa Client llamando al Worker Python vía HTTP.
type HTTPClient struct {
	resty   *resty.Client
	baseURL string
}

// NewHTTPClient crea un cliente apuntando al Worker Python.
// baseURL ejemplo: "http://localhost:8001"
func NewHTTPClient(baseURL string) *HTTPClient {
	r := resty.New().SetBaseURL(baseURL)
	return &HTTPClient{resty: r, baseURL: baseURL}
}

func (c *HTTPClient) ProcessMessage(
	ctx context.Context,
	chatID int64,
	message string,
	reportConfig *types.ReportConfig,
) (*ProcessResult, error) {
	var result ProcessResult
	var apiErr map[string]any

	resp, err := c.resty.R().
		SetContext(ctx).
		SetBody(processRequest{ChatID: chatID, Message: message, ReportConfig: reportConfig}).
		SetResult(&result).
		SetError(&apiErr).
		Post("/internal/process-message")

	if err != nil {
		return nil, fmt.Errorf("worker no disponible: %w", err)
	}
	if resp.IsError() {
		return nil, fmt.Errorf("worker error %d: %v", resp.StatusCode(), apiErr)
	}
	return &result, nil
}

func (c *HTTPClient) IngestFile(
	ctx context.Context,
	chatID int64,
	tmpPath, filename string,
) (*IngestResult, error) {
	var result IngestResult
	var apiErr map[string]any

	resp, err := c.resty.R().
		SetContext(ctx).
		SetBody(ingestRequest{ChatID: chatID, TmpPath: tmpPath, Filename: filename}).
		SetResult(&result).
		SetError(&apiErr).
		Post("/internal/ingest-file")

	if err != nil {
		return nil, fmt.Errorf("worker no disponible: %w", err)
	}
	if resp.IsError() {
		return nil, fmt.Errorf("worker error %d: %v", resp.StatusCode(), apiErr)
	}
	return &result, nil
}
