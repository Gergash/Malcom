package bold

import "testing"

func TestNormalizeAmountCOP(t *testing.T) {
	tests := []struct {
		raw  int
		want int
	}{
		{40000, 40000},
		{4000000, 40000},
		{0, 0},
		{-1, 0},
		{50000, 50000},
	}
	for _, tc := range tests {
		if got := NormalizeAmountCOP(tc.raw); got != tc.want {
			t.Errorf("NormalizeAmountCOP(%d) = %d, want %d", tc.raw, got, tc.want)
		}
	}
}

func TestAmountMatchesPremium(t *testing.T) {
	if !AmountMatchesPremium(40000, 40000) {
		t.Fatal("expected 40000 to match 40000")
	}
	if !AmountMatchesPremium(4000000, 40000) {
		t.Fatal("expected centavos 4000000 to match 40000 COP")
	}
	if AmountMatchesPremium(30000, 40000) {
		t.Fatal("expected 30000 not to match 40000")
	}
}

func TestExtractChatIDFromReference(t *testing.T) {
	raw := []byte(`{"reference":"88442211","status":"succeeded","amount":40000}`)
	id := ExtractChatID(raw)
	if id == nil || *id != 88442211 {
		t.Fatalf("expected chat_id 88442211 from reference, got %v", id)
	}
}

func TestExtractChatIDFromDescriptionURL(t *testing.T) {
	raw := []byte(`{"description":"InsightFlow Pro ?chat_id=12345678","amount":40000}`)
	id := ExtractChatID(raw)
	if id == nil || *id != 12345678 {
		t.Fatalf("expected chat_id from description URL, got %v", id)
	}
}

func TestExtractChatIDFromInsightFlowOrderID(t *testing.T) {
	raw := []byte(`{"reference":"IF-88442211-1720564612","status":"succeeded","amount":40000}`)
	id := ExtractChatID(raw)
	if id == nil || *id != 88442211 {
		t.Fatalf("expected chat_id from IF-order reference, got %v", id)
	}
}

func TestIntegritySignatureOfficialExample(t *testing.T) {
	// Ejemplo documentación Bold: ORD-UNICO-1722528769 + 30000 COP
	sig := IntegritySignature("ORD-UNICO-1722528769", 30000, "COP", "9W4vjqvSoJFK96EV9c3tQg")
	want := "df8ad4095229988b54a42024e70cbf642670e1fdeaa3e21f856829bd19d35062"
	if sig != want {
		t.Fatalf("hash Bold oficial no coincide:\n got  %s\n want %s", sig, want)
	}
}

func TestIntegritySignaturePowerUpsPremium(t *testing.T) {
	sig := IntegritySignature("IF-12345-1720564612", 40000, "COP", "9W4vjqvSoJFK96EV9c3tQg")
	if len(sig) != 64 {
		t.Fatalf("expected sha256 hex, got len %d", len(sig))
	}
}

func TestIntegritySignatureDeterministic(t *testing.T) {
	sig := IntegritySignature("IF-1-99", 40000, "COP", "test-secret")
	if len(sig) != 64 {
		t.Fatalf("expected sha256 hex length 64, got %d", len(sig))
	}
	if IntegritySignature("IF-1-99", 40000, "COP", "test-secret") != sig {
		t.Fatal("integrity signature should be deterministic")
	}
}

func TestParseEventIsSuccessful(t *testing.T) {
	ev := ParseEvent([]byte(`{"type":"transaction.succeeded","status":"approved","amount":40000}`))
	if !ev.IsSuccessful() {
		t.Fatal("expected successful event")
	}
}

func TestExtractPayerEmailShapes(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{"top-level payer_email", `{"payer_email":"Ana@Mail.com"}`, "ana@mail.com"},
		{"nested data.payer_email", `{"data":{"payer_email":"user@dominio.co"}}`, "user@dominio.co"},
		{"customer.email object", `{"customer":{"email":"c@x.io"}}`, "c@x.io"},
		{"data.transaction.customer_email", `{"data":{"transaction":{"customer_email":"t@y.dev"}}}`, "t@y.dev"},
		{"whitespace trimmed", `{"payer_email":"  pad@mail.com  "}`, "pad@mail.com"},
		{"absent", `{"status":"approved"}`, ""},
		{"not an email", `{"payer_email":"sin-arroba"}`, ""},
		{"missing tld dot", `{"payer_email":"a@b"}`, ""},
		{"inner space rejected", `{"payer_email":"a b@mail.com"}`, ""},
	}
	for _, tc := range tests {
		if got := ExtractPayerEmail([]byte(tc.raw)); got != tc.want {
			t.Errorf("%s: ExtractPayerEmail = %q, want %q", tc.name, got, tc.want)
		}
	}
}

func TestParseEventIncludesPayerEmail(t *testing.T) {
	raw := []byte(`{"type":"transaction.succeeded","status":"approved","amount":40000,` +
		`"reference":"IF-555-1720564612","payer_email":"pago@cliente.com"}`)
	ev := ParseEvent(raw)
	if ev.PayerEmail != "pago@cliente.com" {
		t.Fatalf("expected payer email in event, got %q", ev.PayerEmail)
	}
	if ev.ChatID == nil || *ev.ChatID != 555 {
		t.Fatalf("expected chat_id 555, got %v", ev.ChatID)
	}
}
