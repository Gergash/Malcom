// resolved_token.go: resultado de resolver un token de descarga o sesión.
package handlers

// ResolvedToken agrupa ruta en disco y/o JSON embebido tras validar el token.
type ResolvedToken struct {
	ChatID       int64
	FilePath     string
	PayloadJSON  *string
	ResourceType string
}
