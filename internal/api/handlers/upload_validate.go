package handlers

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/gabriel-vasile/mimetype"
)

// MIME permitidos por extensión (no confiar solo en el nombre del archivo).
var uploadMimeByExt = map[string][]string{
	".pdf":  {"application/pdf"},
	".csv":  {"text/csv", "text/plain", "application/csv"},
	".txt":  {"text/plain"},
	".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
	".xls":  {"application/vnd.ms-excel"},
	".doc":  {"application/msword"},
	".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}

func validateUploadMIME(tmpPath, originalFilename string) error {
	ext := strings.ToLower(filepath.Ext(originalFilename))
	allowed, ok := uploadMimeByExt[ext]
	if !ok {
		return fmt.Errorf("extensión no permitida: usa PDF, CSV, TXT, XLS/XLSX o DOC/DOCX")
	}
	det, err := mimetype.DetectFile(tmpPath)
	if err != nil {
		return fmt.Errorf("no se pudo inspeccionar el contenido del archivo")
	}
	mt := det.String()
	for _, prefix := range allowed {
		if strings.HasPrefix(mt, prefix) {
			return nil
		}
	}
	// OOXML a veces se detecta como ZIP internamente
	if ext == ".xlsx" && strings.HasPrefix(mt, "application/zip") {
		return nil
	}
	return fmt.Errorf("el tipo detectado (%s) no coincide con %s", mt, ext)
}
