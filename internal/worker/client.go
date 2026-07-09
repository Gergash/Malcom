// client.go: cliente HTTP para comunicarse con el Worker Python (Orchestrator).
// Go delega toda la lógica de IA/análisis a este servicio ligero.
// Usa Resty como cliente HTTP.
package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/go-resty/resty/v2"
	"github.com/powerups/insightflow-malcom/internal/api/types"
)

// ── Tipos de retorno ──────────────────────────────────────────────────────────

// ProcessResult — resultado que el Worker Python retorna tras procesar un mensaje.
type ProcessResult struct {
	Response   string   `json:"response"`
	HasPDF     bool     `json:"has_pdf"`
	HasExcel   bool     `json:"has_excel"`
	HasChart   bool     `json:"has_chart"`
	ChartPath  string   `json:"chart_path"`  // ruta en disco, gráfica primaria
	ChartPaths []string `json:"chart_paths"` // P5: rutas adicionales (premium multi-chart)
	PDFPath    string   `json:"pdf_path"`    // ruta al PDF generado
	ExcelPath  string   `json:"excel_path"`  // ruta al Excel generado
	// EChartsOption — opción Apache ECharts (JSON) cuando el Brain generó dashboard.
	EChartsOption json.RawMessage `json:"echarts_option,omitempty"`
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
	ChatID            int64               `json:"chat_id"`
	Message           string              `json:"message"`
	ReportConfig      *types.ReportConfig `json:"report_config,omitempty"`
	RequireStrictData bool                `json:"require_strict_data"`
	GenerateECharts   bool                `json:"generate_echarts"`
}

type ingestRequest struct {
	ChatID           int64  `json:"chat_id"`
	TmpPath          string `json:"tmp_path"`
	Filename         string `json:"filename"` // nombre almacenado en disco (p. ej. UUID + ext)
	OriginalFilename string `json:"original_filename,omitempty"`
}

// ── Interfaz ──────────────────────────────────────────────────────────────────

// Client define las operaciones que Go delega al Worker Python.
type Client interface {
	// ProcessMessage envía el mensaje al worker. requireStrictData indica si el chat
	// tiene archivos subidos (Go lo infiere desde data/); el analista no debe inventar datos.
	ProcessMessage(ctx context.Context, chatID int64, message string, reportConfig *types.ReportConfig, requireStrictData bool) (*ProcessResult, error)

	// IngestFile envía la ruta de un archivo temporal al Worker para que lo
	// indexe/almacene. storedFilename es el nombre en data/{chat_id}/; originalFilename es el nombre del usuario (RAG).
	IngestFile(ctx context.Context, chatID int64, tmpPath, storedFilename, originalFilename string) (*IngestResult, error)
}

// ── Implementación HTTP (Resty) ───────────────────────────────────────────────

const defaultWorkerRequestTimeoutSec = 330

var chartKeywords = []string{
	"gráfic", "grafic", "chart", "tablero", "echart", "visualiz",
	"dashboard", "barras", "heatmap", "mapa de calor", "plot",
}

// shouldGenerateECharts — v2: ECharts disponible con datos o cuando el usuario pide gráfica.
func shouldGenerateECharts(message string, requireStrictData bool) bool {
	if requireStrictData {
		return true
	}
	lower := strings.ToLower(message)
	for _, kw := range chartKeywords {
		if strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}

// calculateProcessTimeout ajusta el tiempo de espera al Brain según carga esperada.
func calculateProcessTimeout(message string, reportConfig *types.ReportConfig, requireStrictData, generateECharts bool, maxSec int) time.Duration {
	if maxSec <= 0 {
		maxSec = defaultWorkerRequestTimeoutSec
	}
	maxDur := time.Duration(maxSec) * time.Second

	timeout := 90 * time.Second
	if len(message) > 500 {
		timeout += 30 * time.Second
	}
	if reportConfig != nil {
		timeout += 90 * time.Second
	}
	if requireStrictData {
		timeout += 2 * time.Minute
	}
	if generateECharts {
		timeout += 90 * time.Second
	}
	if timeout > maxDur {
		return maxDur
	}
	return timeout
}

// HTTPClient implementa Client llamando al Worker Python vía HTTP.
type HTTPClient struct {
	resty              *resty.Client
	baseURL            string
	requestTimeoutSec  int
}

// NewHTTPClient crea un cliente apuntando al Worker Python.
// requestTimeoutSec — techo alineado con WORKER_REQUEST_TIMEOUT_SEC del Brain (default 330).
func NewHTTPClient(baseURL string, requestTimeoutSec int) Client {
	if requestTimeoutSec <= 0 {
		requestTimeoutSec = defaultWorkerRequestTimeoutSec
	}
	restyTimeout := time.Duration(requestTimeoutSec+30) * time.Second
	r := resty.New().
		SetBaseURL(baseURL).
		SetTimeout(restyTimeout).
		SetRetryCount(1).
		SetRetryWaitTime(3 * time.Second).
		SetRetryMaxWaitTime(10 * time.Second).
		AddRetryCondition(func(resp *resty.Response, err error) bool {
			if resp == nil {
				return false
			}
			sc := resp.StatusCode()
			return sc >= 502 && sc <= 504
		})

	return &HTTPClient{
		resty:             r,
		baseURL:           baseURL,
		requestTimeoutSec: requestTimeoutSec,
	}
}

func (c *HTTPClient) ProcessMessage(
	ctx context.Context,
	chatID int64,
	message string,
	reportConfig *types.ReportConfig,
	requireStrictData bool,
) (*ProcessResult, error) {
	genECharts := shouldGenerateECharts(message, requireStrictData)
	patience := calculateProcessTimeout(message, reportConfig, requireStrictData, genECharts, c.requestTimeoutSec)
	dynamicCtx, cancel := context.WithTimeout(ctx, patience)
	defer cancel()

	var result ProcessResult
	var apiErr map[string]any

	resp, err := c.resty.R().
		SetContext(dynamicCtx).
		SetBody(processRequest{
			ChatID:            chatID,
			Message:           message,
			ReportConfig:      reportConfig,
			RequireStrictData: requireStrictData,
			GenerateECharts:   genECharts,
		}).
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
	tmpPath, storedFilename, originalFilename string,
) (*IngestResult, error) {
	maxDur := time.Duration(c.requestTimeoutSec) * time.Second
	ingestCtx, cancel := context.WithTimeout(ctx, maxDur)
	defer cancel()

	var result IngestResult
	var apiErr map[string]any

	if strings.TrimSpace(originalFilename) == "" {
		originalFilename = storedFilename
	}
	resp, err := c.resty.R().
		SetContext(ingestCtx).
		SetBody(ingestRequest{
			ChatID:           chatID,
			TmpPath:          tmpPath,
			Filename:         storedFilename,
			OriginalFilename: originalFilename,
		}).
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
