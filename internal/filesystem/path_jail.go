// Package filesystem — rutas bajo data/ por chat (anti path traversal).
package filesystem

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// FileUnderChatData reports whether absFile is a path inside dataRoot/chatID/ (tras Clean/Abs).
func FileUnderChatData(dataRoot, filePath string, chatID int64) bool {
	if dataRoot == "" || filePath == "" {
		return false
	}
	rootAbs, err := filepath.Abs(filepath.Clean(dataRoot))
	if err != nil {
		return false
	}
	fileAbs, err := filepath.Abs(filepath.Clean(filePath))
	if err != nil {
		return false
	}
	chatRoot, err := filepath.Abs(filepath.Join(rootAbs, strconv.FormatInt(chatID, 10)))
	if err != nil {
		return false
	}
	sep := string(os.PathSeparator)
	prefix := chatRoot + sep
	if fileAbs == chatRoot {
		return false
	}
	return strings.HasPrefix(fileAbs, prefix)
}
