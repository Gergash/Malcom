package worker

import "strings"

// ListeningQuery detects Termómetro / escucha social intents (keep in sync with
// app/listening/service.py LISTENING_KEYWORDS).
func ListeningQuery(message string) bool {
	lower := strings.ToLower(message)
	keys := []string{
		"termómetro", "termometro", "listening",
		"escucha social", "escucha ciudadana",
		"sentimiento social", "sentimiento ciudadano",
		"temas en tendencia", "tendencias sociales",
		"alerta cultural", "alertas culturales",
		"tuluá", "tulua",
		"cultura ciudadana",
		"opinión ciudadana", "opinion ciudadana",
	}
	for _, kw := range keys {
		if strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}

// PremiumListeningDeniedMessage — respuesta cuando un chat free pide Termómetro.
const PremiumListeningDeniedMessage = "El **Termómetro Cultural** (escucha social, sentimiento y gráficas en vivo) " +
	"está disponible solo en el plan **Premium**.\n\n" +
	"Activa Premium para consultar el motor de escucha y graficar resultados desde el chat."
