// Package listening: cliente HTTP hacia listening-api (Termómetro Cultural).
package listening

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/go-resty/resty/v2"
)

const defaultTimeout = 25 * time.Second

// Client proxea peticiones al Termómetro Cultural en la red Compose.
type Client struct {
	base          string
	webhookSecret string
	http          *resty.Client
}

// New crea un cliente. baseURL ej. http://listening-api:8002
func New(baseURL, webhookSecret string) *Client {
	base := strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if base == "" {
		base = "http://listening-api:8002"
	}
	rc := resty.New().SetTimeout(defaultTimeout).SetHeader("Accept", "application/json")
	return &Client{base: base, webhookSecret: strings.TrimSpace(webhookSecret), http: rc}
}

// BaseURL expone la URL configurada.
func (c *Client) BaseURL() string { return c.base }

// ProxyGET reenvía query string al path del listening-api y devuelve status + body.
func (c *Client) ProxyGET(ctx context.Context, path string, query url.Values) (int, []byte, string, error) {
	u := c.base + path
	if len(query) > 0 {
		u = u + "?" + query.Encode()
	}
	res, err := c.http.R().SetContext(ctx).Get(u)
	if err != nil {
		return 0, nil, "", fmt.Errorf("listening GET %s: %w", path, err)
	}
	ct := res.Header().Get("Content-Type")
	if ct == "" {
		ct = "application/json"
	}
	return res.StatusCode(), res.Body(), ct, nil
}

// ProxyPOSTJSON envía JSON al path (p. ej. webhooks).
func (c *Client) ProxyPOSTJSON(ctx context.Context, path string, body any, useWebhookAuth bool) (int, []byte, string, error) {
	req := c.http.R().SetContext(ctx).SetBody(body)
	if useWebhookAuth && c.webhookSecret != "" {
		req.SetHeader("X-Webhook-Secret", c.webhookSecret)
	}
	res, err := req.Post(c.base + path)
	if err != nil {
		return 0, nil, "", fmt.Errorf("listening POST %s: %w", path, err)
	}
	ct := res.Header().Get("Content-Type")
	if ct == "" {
		ct = "application/json"
	}
	return res.StatusCode(), res.Body(), ct, nil
}

// Health comprueba /health del listening-api.
func (c *Client) Health(ctx context.Context) error {
	status, body, _, err := c.ProxyGET(ctx, "/health", nil)
	if err != nil {
		return err
	}
	if status >= 300 {
		return fmt.Errorf("listening health %d: %s", status, truncate(body, 200))
	}
	return nil
}

func truncate(b []byte, n int) string {
	s := string(b)
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
