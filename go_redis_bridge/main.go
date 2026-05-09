package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
)

// ── Yapılandırma ──────────────────────────────────────────────────────────────

var (
	REDIS_URL  = getEnv("REDIS_URL", "redis://localhost:6379/0")
	WS_URL     = "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_5m/ethusdt@kline_5m/bnbusdt@kline_5m/solusdt@kline_5m"
	SYMBOLS    = []string{"btcusdt", "ethusdt", "bnbusdt", "solusdt"}
	REDIS_TTL  = 10 * time.Second // Veri bu kadar süre geçerli
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// ── Binance WebSocket veri yapıları ──────────────────────────────────────────

type KlineData struct {
	Symbol    string  `json:"symbol"`
	Timestamp int64   `json:"timestamp"`
	Open      float64 `json:"open,string"`
	High      float64 `json:"high,string"`
	Low       float64 `json:"low,string"`
	Close     float64 `json:"close,string"`
	Volume    float64 `json:"volume,string"`
	IsClosed  bool    `json:"is_closed"`
	UpdatedAt int64   `json:"updated_at"`
}

type BinanceStream struct {
	Stream string `json:"stream"`
	Data   struct {
		EventType string `json:"e"`
		EventTime int64  `json:"E"`
		Symbol    string `json:"s"`
		Kline     struct {
			StartTime int64  `json:"t"`
			Open      string `json:"o"`
			High      string `json:"h"`
			Low       string `json:"l"`
			Close     string `json:"c"`
			Volume    string `json:"v"`
			IsClosed  bool   `json:"x"`
		} `json:"k"`
	} `json:"data"`
}

// ── Redis client ──────────────────────────────────────────────────────────────

func newRedisClient() *redis.Client {
	opt, err := redis.ParseURL(REDIS_URL)
	if err != nil {
		log.Fatalf("[REDIS] URL parse hatası: %v", err)
	}
	client := redis.NewClient(opt)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		log.Fatalf("[REDIS] Bağlantı hatası: %v", err)
	}
	log.Println("[REDIS] ✅ Bağlantı kuruldu:", REDIS_URL)
	return client
}

// ── Redis'e yaz ───────────────────────────────────────────────────────────────

func writeToRedis(rdb *redis.Client, kline KlineData) {
	ctx := context.Background()

	data, err := json.Marshal(kline)
	if err != nil {
		log.Printf("[REDIS] JSON marshal hatası: %v", err)
		return
	}

	// Anahtar: market:BTCUSDT:kline_5m
	key := "market:" + kline.Symbol + ":kline_5m"

	if err := rdb.Set(ctx, key, data, REDIS_TTL).Err(); err != nil {
		log.Printf("[REDIS] Yazma hatası key=%s: %v", key, err)
		return
	}

	// Python'a bildirim — pub/sub
	rdb.Publish(ctx, "market:kline_update", kline.Symbol)

	log.Printf("[REDIS] ✅ %s | close=%.4f | closed=%v",
		kline.Symbol, kline.Close, kline.IsClosed)
}

// ── WebSocket döngüsü ─────────────────────────────────────────────────────────

func runWebSocket(rdb *redis.Client) {
	for {
		log.Println("[WS] Binance'e bağlanıyor...")

		conn, _, err := websocket.DefaultDialer.Dial(WS_URL, nil)
		if err != nil {
			log.Printf("[WS] Bağlantı hatası: %v — 5s sonra tekrar", err)
			time.Sleep(5 * time.Second)
			continue
		}
		log.Println("[WS] ✅ Binance WebSocket bağlantısı kuruldu!")

		for {
			_, msg, err := conn.ReadMessage()
			if err != nil {
				log.Printf("[WS] Okuma hatası: %v — yeniden bağlanıyor", err)
				conn.Close()
				break
			}

			var stream BinanceStream
			if err := json.Unmarshal(msg, &stream); err != nil {
				continue
			}

			if stream.Data.EventType != "kline" {
				continue
			}

			k := stream.Data.Kline
			kline := KlineData{
				Symbol:    stream.Data.Symbol,
				Timestamp: k.StartTime,
				Open:      parseFloat(k.Open),
				High:      parseFloat(k.High),
				Low:       parseFloat(k.Low),
				Close:     parseFloat(k.Close),
				Volume:    parseFloat(k.Volume),
				IsClosed:  k.IsClosed,
				UpdatedAt: time.Now().UnixMilli(),
			}

			writeToRedis(rdb, kline)
		}

		time.Sleep(2 * time.Second)
	}
}

func parseFloat(s string) float64 {
	var f float64
	json.Unmarshal([]byte(s), &f)
	return f
}

// ── Health check ──────────────────────────────────────────────────────────────

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok","service":"go-redis-bridge"}`))
}

// ── Main ─────────────────────────────────────────────────────────────────────

func main() {
	log.Println("🚀 Go Redis Bridge başlatılıyor...")

	rdb := newRedisClient()
	defer rdb.Close()

	go runWebSocket(rdb)

	http.HandleFunc("/health", healthHandler)
	log.Println("[HTTP] Health check: http://localhost:8080/health")
	log.Fatal(http.ListenAndServe(":8080", nil))
}
