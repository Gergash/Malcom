package worker

import "testing"

func TestListeningQuery(t *testing.T) {
	if !ListeningQuery("muéstrame el termómetro cultural") {
		t.Fatal("expected match with accent")
	}
	if !ListeningQuery("termometro cultural") {
		t.Fatal("expected match without accent")
	}
	if ListeningQuery("analiza este csv") {
		t.Fatal("false positive")
	}
}
