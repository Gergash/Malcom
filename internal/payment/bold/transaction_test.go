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

func TestParseEventIsSuccessful(t *testing.T) {
	ev := ParseEvent([]byte(`{"type":"transaction.succeeded","status":"approved","amount":40000}`))
	if !ev.IsSuccessful() {
		t.Fatal("expected successful event")
	}
}
