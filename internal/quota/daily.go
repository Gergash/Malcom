// Package quota implements daily message limits (calendar day in a configured TZ).
package quota

import (
	"time"
)

const DefaultTimezone = "America/Bogota"

// LoadLocation returns the quota timezone or a fixed UTC-5 fallback.
func LoadLocation(tz string) *time.Location {
	tz = trimTZ(tz)
	if tz == "" {
		tz = DefaultTimezone
	}
	loc, err := time.LoadLocation(tz)
	if err != nil {
		return time.FixedZone("America/Bogota", -5*3600)
	}
	return loc
}

func trimTZ(s string) string {
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\t') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\t') {
		s = s[:len(s)-1]
	}
	return s
}

// TodayDate returns midnight of the current calendar day in loc.
func TodayDate(loc *time.Location) time.Time {
	if loc == nil {
		loc = LoadLocation("")
	}
	now := time.Now().In(loc)
	y, m, d := now.Date()
	return time.Date(y, m, d, 0, 0, 0, 0, loc)
}

// SameDay reports whether a and b are the same calendar day in loc.
func SameDay(a, b time.Time, loc *time.Location) bool {
	if loc == nil {
		loc = LoadLocation("")
	}
	ay, am, ad := a.In(loc).Date()
	by, bm, bd := b.In(loc).Date()
	return ay == by && am == bm && ad == bd
}

// NextResetUTC returns the instant when the next quota day begins (midnight loc), in UTC.
func NextResetUTC(loc *time.Location) time.Time {
	if loc == nil {
		loc = LoadLocation("")
	}
	next := TodayDate(loc).AddDate(0, 0, 1)
	return next.UTC()
}
