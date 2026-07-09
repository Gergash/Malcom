package quota

import (
	"testing"
	"time"
)

func TestSameDayBogota(t *testing.T) {
	loc := LoadLocation("America/Bogota")
	// 2026-07-09 23:00 Bogotá and 2026-07-10 01:00 Bogotá are different days.
	a := time.Date(2026, 7, 9, 23, 0, 0, 0, loc)
	b := time.Date(2026, 7, 10, 1, 0, 0, 0, loc)
	if SameDay(a, b, loc) {
		t.Fatal("expected different quota days")
	}
	c := time.Date(2026, 7, 9, 8, 0, 0, 0, loc)
	if !SameDay(a, c, loc) {
		t.Fatal("expected same quota day")
	}
}

func TestNextResetUTCAfterToday(t *testing.T) {
	loc := LoadLocation("America/Bogota")
	reset := NextResetUTC(loc)
	if !reset.After(time.Now().UTC()) {
		t.Fatalf("next reset should be in the future, got %v", reset)
	}
}
