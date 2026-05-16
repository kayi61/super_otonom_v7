package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"time"

	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
)

type KlineMsg struct {
	Stream string `json:"stream"`
	Data   struct {
		EventType string `json:"e"`
		EventTime int64  `json:"E"`
		Symbol    string `json:"s"`
		Kline     struct {
			StartTime int64           `json:"t"`
			CloseTime int64           `json:"T"`
			Symbol    string          `json:"s"`
			Interval  string          `json:"i"`
			Open      json.RawMessage `json:"o"`
			Close     json.RawMessage `json:"c"`
			High      json.RawMessage `json:"h"`
			Low       json.RawMessage `json:"l"`
			Volume    json.RawMessage `json:"v"`
			IsClosed  bool            `json:"x"`
		} `json:"k"`
	} `json:"data"`
}

type TickData struct {
	Symbol    string          `json:"symbol"`
	Open      json.RawMessage `json:"open"`
	High      json.RawMessage `json:"high"`
	Low       json.RawMessage `json:"low"`
	Close     json.RawMessage `json:"close"`
	Volume    json.RawMessage `json:"volume"`
	Timestamp int64           `json:"timestamp"`
	IsClosed  bool            `json:"is_closed"`
}

var symbols = []string{"btcusdt", "ethusdt", "bnbusdt", "solusdt"}
var interval = "5m"
var ctx = context.Background()

// redisKlineTTL — Python Faz 4 / data_freshness ile uyumlu; her SET ile yenilenir.
func redisKlineTTL() time.Duration {
	s := os.Getenv("REDIS_KLINE_TTL_SECONDS")
	if s == "" {
		return 900 * time.Second
	}
	sec, err := strconv.Atoi(s)
	if err != nil || sec < 120 {
		return 900 * time.Second
	}
	return time.Duration(sec) * time.Second
}

func redisKlineKeySuffix() string {
	if v := os.Getenv("REDIS_KLINE_KEY_SUFFIX"); v != "" {
		return v
	}
	return "kline_5m"
}

func buildStreamURL() string {
	// Exchange seçimi: EXCHANGE env (varsayılan: binance)
	exchange := os.Getenv("EXCHANGE")
	if exchange == "" {
		exchange = "binance"
	}

	// OKX desteği
	if exchange == "okx" {
		return "wss://ws.okx.com:8443/ws/v5/public"
	}

	// Binance testnet/mainnet
	baseURL := "wss://stream.binance.com:9443"
	testnet := os.Getenv("BINANCE_TESTNET")
	if testnet == "true" || testnet == "1" {
		baseURL = "wss://testnet.binance.vision"
	}

	streams := ""
	for i, s := range symbols {
		if i > 0 {
			streams += "/"
		}
		streams += fmt.Sprintf("%s@kline_%s", s, interval)
	}
	return fmt.Sprintf("%s/stream?streams=%s", baseURL, streams)
}

func newRedisClient() *redis.Client {
	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = "redis://redis:6379/0"
	}
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		opt = &redis.Options{Addr: "redis:6379", DB: 0}
	}
	return redis.NewClient(opt)
}

func connectAndStream(rdb *redis.Client) {
	url := buildStreamURL()
	log.Printf("[GO-WS] Bağlanıyor: %s", url)

	dialer := websocket.DefaultDialer
	dialer.HandshakeTimeout = 10 * time.Second

	conn, _, err := dialer.Dial(url, nil)
	if err != nil {
		log.Printf("[GO-WS] Bağlantı hatası: %v", err)
		return
	}
	defer conn.Close()

	// Ping/Pong handler - bağlantıyı canlı tutar
	conn.SetPingHandler(func(data string) error {
		log.Printf("[GO-WS] Ping alındı, Pong gönderiliyor")
		return conn.WriteControl(websocket.PongMessage, []byte(data), time.Now().Add(5*time.Second))
	})

	// Read deadline - 60 saniye içinde mesaj gelmezse yeniden bağlan
	conn.SetReadDeadline(time.Now().Add(60 * time.Second))

	log.Printf("[GO-WS] ✅ Binance WebSocket bağlantısı kuruldu!")
	log.Printf("[GO-WS] İzlenen semboller: %v", symbols)

	msgCount := 0
	for {
		// Her mesajda deadline uzat
		conn.SetReadDeadline(time.Now().Add(60 * time.Second))

		_, msg, err := conn.ReadMessage()
		if err != nil {
			log.Printf("[GO-WS] Mesaj okuma hatası: %v", err)
			return
		}

		msgCount++
		log.Printf("[GO-WS] 📨 Mesaj #%d alındı (%d byte)", msgCount, len(msg))

		var klineMsg KlineMsg
		if err := json.Unmarshal(msg, &klineMsg); err != nil {
			log.Printf("[GO-WS] JSON parse hatası: %v | msg: %s", err, string(msg[:min(100, len(msg))]))
			continue
		}

		k := klineMsg.Data.Kline
		if k.Symbol == "" {
			log.Printf("[GO-WS] Boş sembol, atlanıyor: %s", string(msg[:min(100, len(msg))]))
			continue
		}

		tick := TickData{
			Symbol:    k.Symbol,
			Open:      k.Open,
			High:      k.High,
			Low:       k.Low,
			Close:     k.Close,
			Volume:    k.Volume,
			Timestamp: k.StartTime,
			IsClosed:  k.IsClosed,
		}

		type TickFull struct {
			Symbol    string          `json:"symbol"`
			Open      json.RawMessage `json:"open"`
			High      json.RawMessage `json:"high"`
			Low       json.RawMessage `json:"low"`
			Close     json.RawMessage `json:"close"`
			Volume    json.RawMessage `json:"volume"`
			Timestamp int64           `json:"timestamp"`
			IsClosed  bool            `json:"is_closed"`
			UpdatedAt int64           `json:"updated_at"`
		}
		full := TickFull{
			Symbol: tick.Symbol, Open: tick.Open, High: tick.High,
			Low: tick.Low, Close: tick.Close, Volume: tick.Volume,
			Timestamp: tick.Timestamp, IsClosed: tick.IsClosed,
			UpdatedAt: time.Now().UnixMilli(),
		}
		tickJSON, _ := json.Marshal(full)
		sfx := redisKlineKeySuffix()
		key := fmt.Sprintf("market:%s:%s", tick.Symbol, sfx)
		ttl := redisKlineTTL()

		if err := rdb.Set(ctx, key, tickJSON, ttl).Err(); err != nil {
			log.Printf("[REDIS] ❌ Yazma hatası %s: %v", key, err)
		} else {
			// Pub/Sub: Python tarafına anlık bildirim
			rdb.Publish(ctx, "market:kline_update", tick.Symbol)

			if tick.IsClosed {
				// Kapanan mumu listeye ekle (tarihsel veri)
				histKey := fmt.Sprintf("market:%s:%s:history", tick.Symbol, sfx)
				rdb.LPush(ctx, histKey, tickJSON)
				rdb.LTrim(ctx, histKey, 0, 299) // Son 300 mum tut
				_ = rdb.Expire(ctx, histKey, ttl).Err()
				log.Printf("[GO-WS] ✅ MUM KAPANDI | %s | C:%s → Redis'e yazıldı + history", tick.Symbol, string(tick.Close))
			} else {
				log.Printf("[GO-WS] 📊 %s | Close: %s → Redis güncellendi", tick.Symbol, string(tick.Close))
			}
		}
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"service": "super_otonom_go",
		"time":    time.Now().Format(time.RFC3339),
	})
}

func main() {
	log.SetOutput(os.Stdout)
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	log.Println("🚀 Super Otonom GO Servisi başlatılıyor...")

	rdb := newRedisClient()

	pingCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := rdb.Ping(pingCtx).Err(); err != nil {
		log.Printf("[REDIS] ❌ Redis bağlantı hatası: %v", err)
	} else {
		log.Println("[REDIS] ✅ Redis bağlantısı kuruldu!")
	}

	go func() {
		http.HandleFunc("/health", healthHandler)
		log.Println("[GO-HTTP] Health check: http://localhost:8080/health")
		http.ListenAndServe(":8080", nil)
	}()

	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt)

	for {
		select {
		case <-interrupt:
			log.Println("[GO-WS] Servis durduruluyor...")
			return
		default:
			connectAndStream(rdb)
			log.Println("[GO-WS] Yeniden bağlanıyor... (5s)")
			time.Sleep(5 * time.Second)
		}
	}
}
