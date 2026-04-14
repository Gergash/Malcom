// Package filesystem helpers for user data directories (shared with Python worker).
package filesystem

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Extensions we treat as “usuario subió datos/documentos” for strict-mode gating.
// Alineado con tipos que el AnalystAgent puede usar (CSV/Excel + documentos indexables).
var uploadedDataExtensions = map[string]struct{}{
	".csv": {}, ".xlsx": {}, ".xls": {}, ".pdf": {}, ".docx": {}, ".txt": {},
}

// HasUploadedDataFiles reports whether data/{chatID}/ contains at least one
// relevant file (no subcarpetas; ignora ocultos y .upload-tmp no aplica aquí).
func HasUploadedDataFiles(dataDir string, chatID int64) bool {
	dir := filepath.Join(dataDir, strconv.FormatInt(chatID, 10))
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if strings.HasPrefix(name, ".") {
			continue
		}
		ext := strings.ToLower(filepath.Ext(name))
		if _, ok := uploadedDataExtensions[ext]; ok {
			return true
		}
	}
	return false
}
