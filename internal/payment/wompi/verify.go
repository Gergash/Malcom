// Package wompi — verificación de integridad de eventos (documentación oficial Wompi).
package wompi

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/tidwall/gjson"
)

// VerifyEventChecksum valida X-Event-Checksum o signature.checksum según el algoritmo de Wompi.
// eventSecret es el "Secreto para eventos" del dashboard del comercio (no la llave privada).
// Si eventSecret está vacío, no valida (compatibilidad con payloads de prueba).
func VerifyEventChecksum(raw []byte, headerChecksum, eventSecret string) bool {
	eventSecret = strings.TrimSpace(eventSecret)
	if eventSecret == "" {
		return true
	}
	provided := strings.TrimSpace(headerChecksum)
	if provided == "" {
		provided = strings.TrimSpace(gjson.GetBytes(raw, "signature.checksum").String())
	}
	if provided == "" {
		return false
	}
	computed, err := computeChecksum(raw, eventSecret)
	if err != nil {
		return false
	}
	return strings.EqualFold(computed, provided)
}

func computeChecksum(raw []byte, secret string) (string, error) {
	var envelope struct {
		Signature *struct {
			Properties []string `json:"properties"`
		} `json:"signature"`
		Timestamp int64 `json:"timestamp"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return "", err
	}
	if envelope.Signature == nil || len(envelope.Signature.Properties) == 0 {
		return "", fmt.Errorf("firma wompi: falta signature.properties")
	}
	var b strings.Builder
	for _, prop := range envelope.Signature.Properties {
		path := prop
		if !strings.HasPrefix(path, "data.") {
			path = "data." + path
		}
		val := gjson.GetBytes(raw, path)
		b.WriteString(val.String())
	}
	b.WriteString(strconv.FormatInt(envelope.Timestamp, 10))
	b.WriteString(secret)
	sum := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(sum[:]), nil
}
