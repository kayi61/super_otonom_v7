from __future__ import annotations

"""
MetricsExporter v5.1
─────────────────────────────────────────────────────────────────────────────
YENİLİKLER (v4 → v5):
  • slippage_avg gauge eklendi (sembol bazında ortalama execution kayması)
  • record_slippage(symbol, expected_price, actual_price) — yeni metod
  • regime gauge eklendi (0=NOISY, 1=MEAN_REVERTING, 2=TRENDING)
  • circuit_breaker_open gauge eklendi (0/1 sembol bazında)
"""

import logging
from typing import Any, Dict, Optional

log = logging.getLogger("super_otonom.metrics")

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    log.warning(
        "MetricsExporter: prometheus_client kurulu degil. "
        "pip install prometheus-client  ile kurun. No-op mod aktif."
    )

# Rejim → sayısal eşlem (Grafana'da filter/alert için)
_REGIME_MAP = {"NOISY": 0, "MEAN_REVERTING": 1, "TRENDING": 2}


class MetricsExporter:
    """
    v5 — Prometheus metrik ihracatçısı (Grafana uyumlu).

    Özellikler:
    - BotEngine.status() çıktısını otomatik olarak Gauge'lere yazar
    - Ek metrikler: trade_count (Counter), pnl_trade (Histogram)
    - Yeni v5: slippage_avg (sembol bazında), regime, circuit_breaker_open
    - prometheus_client kurulu değilse sessizce no-op çalışır
    - port=0 vererek HTTP sunucusunu devre dışı bırakabilirsiniz

    Grafana kurulumu:
    1. Prometheus datasource ekle → http://localhost:8000
    2. Dashboard oluştur → bot_equity, bot_pnl, bot_open_positions,
       bot_win_rate, bot_daily_loss, bot_drawdown_pct, bot_slippage_avg metriklerini seç.
    """

    def __init__(self, port: int = 8000, namespace: str = "bot"):
        self._enabled = _PROMETHEUS_AVAILABLE
        self._port = port
        self._ns = namespace
        self._gauges: Dict[str, Any] = {}
        self._counters: Dict[str, Any] = {}
        self._histos: Dict[str, Any] = {}

        if not self._enabled:
            return

        # ── Scalar Gauge'ler ──────────────────────────────────────────────────
        gauge_defs = [
            ("equity", "Anlık toplam sermaye (USDT)"),
            ("free_capital", "Kullanılabilir serbest sermaye"),
            ("total_pnl", "Kümülatif kar/zarar"),
            ("pnl_pct", "Kar/zarar yüzdesi"),
            ("open_positions", "Açık pozisyon sayısı"),
            ("trades_today", "Bugünkü işlem sayısı"),
            ("total_trades", "Toplam işlem sayısı"),
            ("win_rate", "Son 50 işlem kazanma oranı (%)"),
            ("rr_ratio", "Risk/ödül oranı"),
            ("var_95", "95. percentile Value at Risk"),
            ("daily_loss", "Günlük zarar (USDT)"),
            ("peak_drawdown_pct", "Peak-to-trough drawdown (%)"),
            ("emergency_stop", "Acil durdurma durumu (0/1)"),
            ("dynamic_daily_limit", "Dinamik günlük kayıp limiti (%)"),  # FIX v6.2
            ("hurst", "Son analiz Hurst exponent"),
            ("volatility", "Son analiz volatilite"),
            ("clock_skew_abs_ms", "Borsa-yerel saat farki mutlak (ms)"),
            (
                "host_ntp_synchronized",
                "Host NTP: 1=sync, 0=not sync, -1=unknown",
            ),
        ]
        for name, desc in gauge_defs:
            try:
                self._gauges[name] = Gauge(f"{namespace}_{name}", desc)
            except ValueError:
                from prometheus_client import REGISTRY

                self._gauges[name] = REGISTRY._names_to_collectors.get(f"{namespace}_{name}")

        # ── Sembol etiketli Gauge'ler (v5 yenilikleri) ───────────────────────
        try:
            self._gauges["slippage_avg"] = Gauge(
                f"{namespace}_slippage_avg",
                "Ortalama execution kayması (yüzde)",
                ["symbol"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["slippage_avg"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_slippage_avg"
            )
        try:
            self._gauges["regime"] = Gauge(
                f"{namespace}_regime",
                "Piyasa rejimi: 0=NOISY, 1=MEAN_REVERTING, 2=TRENDING",
                ["symbol"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["regime"] = REGISTRY._names_to_collectors.get(f"{namespace}_regime")
        try:
            self._gauges["circuit_breaker_open"] = Gauge(
                f"{namespace}_circuit_breaker_open",
                "CircuitBreaker açık mı: 0=KAPALI, 1=AÇIK",
                ["symbol"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["circuit_breaker_open"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_circuit_breaker_open"
            )
        try:
            self._gauges["clock_skew_exchange_ms"] = Gauge(
                f"{namespace}_clock_skew_exchange_ms",
                "Borsa timeDifference (ms); pozitif = yerel saat ileride",
                ["exchange"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["clock_skew_exchange_ms"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_clock_skew_exchange_ms"
            )

        # ── VR-12: Stress scenario grid ──────────────────────────────────────
        try:
            self._gauges["stress_worst_scenario_pnl_pct"] = Gauge(
                f"{namespace}_stress_worst_scenario_pnl_pct",
                "En kotu stres senaryosu PnL yüzdesi (negatif = kayip)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["stress_worst_scenario_pnl_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_stress_worst_scenario_pnl_pct"
            )
        try:
            self._gauges["reverse_stress_min_btc_shock_pct"] = Gauge(
                f"{namespace}_reverse_stress_min_btc_shock_pct",
                "Reverse stress: minimum BTC sok yüzdesi (hedef kayba ulasmak icin)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["reverse_stress_min_btc_shock_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_reverse_stress_min_btc_shock_pct"
            )

        # ── VR-13: Kupiec POF backtest ───────────────────────────────────────
        try:
            self._gauges["kupiec_pvalue"] = Gauge(
                f"{namespace}_kupiec_pvalue",
                "Kupiec POF test p-degeri (>0.05 = model gecerli)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["kupiec_pvalue"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_kupiec_pvalue"
            )
        try:
            self._gauges["kupiec_exceedances"] = Gauge(
                f"{namespace}_kupiec_exceedances",
                "VaR exceedance sayisi (Kupiec backtest)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["kupiec_exceedances"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_kupiec_exceedances"
            )

        # ── VR-08: LVaR (sembol bazında) ─────────────────────────────────────
        try:
            self._gauges["var_liquidity_adjusted"] = Gauge(
                f"{namespace}_var_liquidity_adjusted",
                "Liquidity-adjusted VaR (BDSS/TTL)",
                ["symbol"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_liquidity_adjusted"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_liquidity_adjusted"
            )

        # ── Counter'lar ───────────────────────────────────────────────────────
        try:
            self._counters["trades"] = Counter(
                f"{namespace}_trades_total",
                "Toplam kapatılan işlem sayısı",
                ["reason"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._counters["trades"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_trades_total"
            )
        try:
            self._counters["order_errors"] = Counter(
                f"{namespace}_order_errors_total",
                "Emir ve borsa islem hatalari",
                ["type"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._counters["order_errors"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_order_errors_total"
            )
        try:
            self._counters["ws_reconnects"] = Counter(
                f"{namespace}_ws_reconnects_total",
                "WebSocket yeniden baglanti sayisi",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._counters["ws_reconnects"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_ws_reconnects_total"
            )

        try:
            self._gauges["dependency_up"] = Gauge(
                f"{namespace}_dependency_up",
                "Bagimlilik sagligi: 1=up, 0=down",
                ["name"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["dependency_up"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_dependency_up"
            )

        # ── Histogram'lar ─────────────────────────────────────────────────────
        try:
            self._histos["pnl"] = Histogram(
                f"{namespace}_trade_pnl",
                "İşlem başına kar/zarar dağılımı",
                buckets=[-50, -20, -10, -5, -2, -1, 0, 1, 2, 5, 10, 20, 50, 100],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._histos["pnl"] = REGISTRY._names_to_collectors.get(f"{namespace}_trade_pnl")
        try:
            self._histos["slippage"] = Histogram(
                f"{namespace}_slippage_hist",
                "Execution kayması dağılımı (yüzde)",
                buckets=[0, 0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._histos["slippage"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_slippage_hist"
            )

        if port > 0:
            try:
                start_http_server(port)
                log.info("MetricsExporter: Prometheus HTTP sunucusu port=%d baslatildi.", port)
            except OSError as exc:
                log.error("MetricsExporter: HTTP sunucusu baslatılamadı port=%d err=%s", port, exc)

    # ── Ana güncelleme metodu ─────────────────────────────────────────────────

    def update(self, status: Dict[str, Any]) -> None:
        """
        BotEngine.status() çıktısını alır, tüm metrikler günceller.
        prometheus_client yoksa sessizce çıkar.
        """
        if not self._enabled:
            return

        mapping = {
            "equity": "equity",
            "free_capital": "free_capital",
            "total_pnl": "total_pnl",
            "pnl_pct": "pnl_pct",
            "open_positions": "open_positions",
            "trades_today": "trades_today",
            "total_trades": "total_trades",
            "win_rate": "win_rate",
            "rr_ratio": "rr_ratio",
            "var_95": "var_95",
            "daily_loss": "daily_loss",
            "peak_drawdown_pct": "peak_drawdown_pct",
            "dynamic_daily_limit": "dynamic_daily_limit",  # FIX v6.2
        }
        for status_key, gauge_key in mapping.items():
            val = status.get(status_key)
            if val is not None:
                try:
                    self._gauges[gauge_key].set(float(val))
                except (TypeError, ValueError):
                    pass

        es = status.get("emergency_stop", False)
        self._gauges["emergency_stop"].set(1.0 if es else 0.0)

    def record_analysis(self, analysis: Dict[str, Any]) -> None:
        """
        analyzer.py çıktısındaki hurst, volatility ve regime gibi
        anlık teknik göstergeleri Prometheus'a yazar.
        """
        if not self._enabled:
            return
        symbol = analysis.get("symbol", "unknown")
        hurst = analysis.get("hurst")
        vol = analysis.get("volatility")
        regime = analysis.get("regime", "NOISY")

        if hurst is not None:
            self._gauges["hurst"].set(float(hurst))
        if vol is not None:
            self._gauges["volatility"].set(float(vol))

        # Rejimi sayısal değere çevir
        regime_val = _REGIME_MAP.get(str(regime).upper(), 0)
        try:
            self._gauges["regime"].labels(symbol=symbol).set(regime_val)
        except Exception:
            pass

    # ── v5 YENİLİK: Slippage kaydı ───────────────────────────────────────────

    def record_slippage(self, symbol: str, expected_price: float, actual_price: float) -> None:
        """
        İşlem sonrası beklenen fiyat ile gerçekleşen fiyat arasındaki
        kayma yüzdesini Prometheus'a yazar.

        Çağrı örneği (bot_engine._handle_entry / _close içinde):
            self.metrics.record_slippage(symbol, price, fill_price)
        """
        if not self._enabled:
            return
        if expected_price <= 0:
            return
        slippage = abs(actual_price - expected_price) / expected_price
        try:
            self._gauges["slippage_avg"].labels(symbol=symbol).set(slippage)
            self._histos["slippage"].observe(slippage)
        except Exception as exc:
            log.debug("MetricsExporter.record_slippage hata: %s", exc)

    # ── v5 YENİLİK: CircuitBreaker durum sync ────────────────────────────────

    def update_circuit_breakers(self, cb_status: Dict[str, str]) -> None:
        """
        AsyncExchangeHandler.circuit_breaker_status() çıktısını alır,
        her sembol için gauge günceller.

        cb_status örneği:
            {"BTC/USDT": "CLOSED", "ETH/USDT": "OPEN (recovery=45s kaldı)"}
        """
        if not self._enabled:
            return
        for symbol, state in cb_status.items():
            is_open = 1.0 if state.startswith("OPEN") else 0.0
            try:
                self._gauges["circuit_breaker_open"].labels(symbol=symbol).set(is_open)
            except Exception:
                pass

    # ── İşlem kaydı ──────────────────────────────────────────────────────────

    def record_trade(self, pnl: float, reason: str = "unknown") -> None:
        """
        Kapanan her işlemde çağrılır.
        - trade_counter[reason] artar
        - pnl histogram'a yazılır
        """
        if not self._enabled:
            return
        try:
            self._counters["trades"].labels(reason=reason).inc()
            self._histos["pnl"].observe(float(pnl))
        except Exception as exc:
            log.debug("MetricsExporter.record_trade hata: %s", exc)

    def inc_order_error(self, err_type: str = "order") -> None:
        if not self._enabled:
            return
        try:
            self._counters["order_errors"].labels(type=err_type).inc()
        except Exception as exc:
            log.debug("MetricsExporter.inc_order_error hata: %s", exc)

    def inc_ws_reconnect(self) -> None:
        if not self._enabled:
            return
        try:
            self._counters["ws_reconnects"].inc()
        except Exception as exc:
            log.debug("MetricsExporter.inc_ws_reconnect hata: %s", exc)

    def set_dependency_up(self, name: str, up: bool) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["dependency_up"].labels(name=name).set(1.0 if up else 0.0)
        except Exception as exc:
            log.debug("MetricsExporter.set_dependency_up hata: %s", exc)

    def record_clock_skew(self, exchange_id: str, skew_ms: int) -> None:
        if not self._enabled:
            return
        try:
            skew_f = float(skew_ms)
            self._gauges["clock_skew_exchange_ms"].labels(exchange=exchange_id).set(skew_f)
            self._gauges["clock_skew_abs_ms"].set(abs(skew_f))
        except Exception as exc:
            log.debug("MetricsExporter.record_clock_skew hata: %s", exc)

    def record_kupiec(self, p_value: float, exceedances: int) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["kupiec_pvalue"].set(p_value)
            self._gauges["kupiec_exceedances"].set(float(exceedances))
        except Exception as exc:
            log.debug("MetricsExporter.record_kupiec hata: %s", exc)

    def record_stress_grid(
        self, worst_pnl_pct: float, reverse_btc_shock_pct: float,
    ) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["stress_worst_scenario_pnl_pct"].set(worst_pnl_pct)
            self._gauges["reverse_stress_min_btc_shock_pct"].set(reverse_btc_shock_pct)
        except Exception as exc:
            log.debug("MetricsExporter.record_stress_grid hata: %s", exc)

    def record_lvar(self, symbol: str, lvar: float) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["var_liquidity_adjusted"].labels(symbol=symbol).set(lvar)
        except Exception as exc:
            log.debug("MetricsExporter.record_lvar hata: %s", exc)

    def record_host_ntp(self, synced: Optional[bool]) -> None:
        if not self._enabled:
            return
        val = -1.0 if synced is None else (1.0 if synced else 0.0)
        try:
            self._gauges["host_ntp_synchronized"].set(val)
        except Exception as exc:
            log.debug("MetricsExporter.record_host_ntp hata: %s", exc)

    # ── Durum sorgusu ─────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._enabled

    def __repr__(self) -> str:
        return f"MetricsExporter(enabled={self._enabled} port={self._port} ns={self._ns})"
