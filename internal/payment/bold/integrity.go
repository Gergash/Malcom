package bold

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strconv"
)

// IntegritySignature builds the Bold checkout hash:
// SHA256("{orderId}{amount}{currency}{secretKey}") in hex.
func IntegritySignature(orderID string, amountCOP int, currency, secretKey string) string {
	cadena := fmt.Sprintf("%s%s%s%s", orderID, strconv.Itoa(amountCOP), currency, secretKey)
	sum := sha256.Sum256([]byte(cadena))
	return hex.EncodeToString(sum[:])
}
