package bold

// NormalizeAmountCOP converts Bold amount fields to whole pesos (COP).
// Bold may send 40000 (pesos) or 4000000 (centavos × 100).
func NormalizeAmountCOP(rawAmount int) int {
	if rawAmount <= 0 {
		return 0
	}
	if rawAmount >= 1_000_000 && rawAmount%100 == 0 {
		return rawAmount / 100
	}
	return rawAmount
}

// AmountMatchesPremium reports whether rawAmount equals the configured premium price.
// When expectedCOP is zero or negative, any positive amount is accepted (dev only).
func AmountMatchesPremium(rawAmount, expectedCOP int) bool {
	if expectedCOP <= 0 {
		return rawAmount > 0
	}
	return NormalizeAmountCOP(rawAmount) == expectedCOP
}
