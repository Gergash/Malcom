package middleware

import (
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

// ChatRateLimit limita peticiones por IP (token bucket). rps<=0 desactiva el middleware.
func ChatRateLimit(rps float64, burst int) gin.HandlerFunc {
	if rps <= 0 || burst <= 0 {
		return func(c *gin.Context) { c.Next() }
	}
	cl := &chatLimiter{
		limiters: make(map[string]*rate.Limiter),
		lim:      rate.Limit(rps),
		burst:    burst,
	}
	return func(c *gin.Context) {
		ip := c.ClientIP()
		lim := cl.get(ip)
		if !lim.Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"detail": "Demasiadas peticiones. Espera un momento e inténtalo de nuevo.",
			})
			return
		}
		c.Next()
	}
}

type chatLimiter struct {
	mu       sync.Mutex
	limiters map[string]*rate.Limiter
	lim      rate.Limit
	burst    int
	lastGC   time.Time
}

func (cl *chatLimiter) get(ip string) *rate.Limiter {
	cl.mu.Lock()
	defer cl.mu.Unlock()
	if time.Since(cl.lastGC) > 5*time.Minute {
		cl.limiters = make(map[string]*rate.Limiter)
		cl.lastGC = time.Now()
	}
	lim, ok := cl.limiters[ip]
	if !ok {
		lim = rate.NewLimiter(cl.lim, cl.burst)
		cl.limiters[ip] = lim
	}
	return lim
}
