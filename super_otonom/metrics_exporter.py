from __future__ import annotations

"""
MetricsExporter v5.2
─────────────────────────────────────────────────────────────────────────────
YENİLİKLER (v5.1 → v5.2):
  • VR-21: Multi-labeled VaR/CVaR Prometheus gauges (conf × model × scope)
  • record_var_suite() — tek çağrıda tüm VaR/CVaR/stress metriklerini yazar
  • bot_var_pct{conf,model,scope}, bot_cvar_pct{conf,model,scope}
  • bot_stressed_var_pct, bot_component_var_pct{symbol}, bot_var_model_dispersion_pct
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

        # ── VR-14: Christoffersen Independence / CC ─────────────────────────
        try:
            self._gauges["christoffersen_ind_pvalue"] = Gauge(
                f"{namespace}_christoffersen_ind_pvalue",
                "Christoffersen independence test p-degeri (>0.05 = kumelenme yok)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["christoffersen_ind_pvalue"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_christoffersen_ind_pvalue"
            )
        try:
            self._gauges["christoffersen_cc_pvalue"] = Gauge(
                f"{namespace}_christoffersen_cc_pvalue",
                "Christoffersen CC test p-degeri (>0.05 = model gecerli)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["christoffersen_cc_pvalue"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_christoffersen_cc_pvalue"
            )

        # ── VR-15: Basel Traffic Light ───────────────────────────────────────
        try:
            self._gauges["var_traffic_light"] = Gauge(
                f"{namespace}_var_traffic_light",
                "Basel traffic light: 0=GREEN, 1=YELLOW, 2=RED",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_traffic_light"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_traffic_light"
            )
        try:
            self._gauges["var_traffic_light_exceedances"] = Gauge(
                f"{namespace}_var_traffic_light_exceedances",
                "VaR exceedance sayisi (Basel 250-gun penceresi)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_traffic_light_exceedances"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_traffic_light_exceedances"
            )
        try:
            self._gauges["var_traffic_light_capital_addon"] = Gauge(
                f"{namespace}_var_traffic_light_capital_addon",
                "Basel sermaye carpani ek yuklemesi (0.0 - 1.0)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_traffic_light_capital_addon"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_traffic_light_capital_addon"
            )

        # ── VR-16: PnL Attribution ──────────────────────────────────────────
        try:
            self._gauges["pnl_explained_pct"] = Gauge(
                f"{namespace}_pnl_explained_pct",
                "Aciklanan PnL yuzdesi (mark-to-market / toplam sermaye)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["pnl_explained_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_pnl_explained_pct"
            )
        try:
            self._gauges["pnl_unexplained_pct"] = Gauge(
                f"{namespace}_pnl_unexplained_pct",
                "Aciklanamayan PnL yuzdesi (drift gostergesi)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["pnl_unexplained_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_pnl_unexplained_pct"
            )
        try:
            self._gauges["pnl_attribution_health"] = Gauge(
                f"{namespace}_pnl_attribution_health",
                "PnL attribution sagligi: 1=saglikli, 0=drift tespit edildi",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["pnl_attribution_health"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_pnl_attribution_health"
            )

        # ── VR-17: Pre-trade VaR Gate ──────────────────────────────────────
        try:
            self._gauges["pre_trade_var_gate_passed"] = Gauge(
                f"{namespace}_pre_trade_var_gate_passed",
                "Pre-trade VaR gate: 1=onaylandi, 0=reddedildi",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["pre_trade_var_gate_passed"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_pre_trade_var_gate_passed"
            )
        try:
            self._gauges["pre_trade_var_gate_new_var"] = Gauge(
                f"{namespace}_pre_trade_var_gate_new_var",
                "Pre-trade tahmini yeni portfoy VaR (fraksiyon)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["pre_trade_var_gate_new_var"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_pre_trade_var_gate_new_var"
            )
        try:
            self._gauges["pre_trade_var_gate_marginal_var"] = Gauge(
                f"{namespace}_pre_trade_var_gate_marginal_var",
                "Pre-trade marjinal VaR katkisi (fraksiyon)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["pre_trade_var_gate_marginal_var"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_pre_trade_var_gate_marginal_var"
            )

        # ── VR-18: VaR-aware Position Sizer ────────────────────────────────
        try:
            self._gauges["position_sizer_var_cap_active"] = Gauge(
                f"{namespace}_position_sizer_var_cap_active",
                "VaR cap binding: 1=cap kisitladi, 0=Kelly daha kucuk",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["position_sizer_var_cap_active"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_position_sizer_var_cap_active"
            )
        try:
            self._gauges["position_sizer_var_capped_size"] = Gauge(
                f"{namespace}_position_sizer_var_capped_size",
                "VaR cap sonrasi pozisyon boyutu (USDT)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["position_sizer_var_capped_size"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_position_sizer_var_capped_size"
            )

        # ── VR-19: VaR Breach Kill-switch ──────────────────────────────────────
        try:
            self._gauges["var_breach_kill_switch"] = Gauge(
                f"{namespace}_var_breach_kill_switch",
                "VaR breach kill-switch: 0=normal, 1=var_99, 2=cvar_975, 3=stressed_var",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_breach_kill_switch"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_breach_kill_switch"
            )
        try:
            self._gauges["var_99_current"] = Gauge(
                f"{namespace}_var_99_current",
                "Guncel VaR 99% (fraksiyon)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_99_current"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_99_current"
            )
        try:
            self._gauges["cvar_975_current"] = Gauge(
                f"{namespace}_cvar_975_current",
                "Guncel CVaR 97.5% (fraksiyon)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["cvar_975_current"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_cvar_975_current"
            )
        try:
            self._gauges["model_dispersion_current"] = Gauge(
                f"{namespace}_model_dispersion_current",
                "Guncel model dispersion (fraksiyon)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["model_dispersion_current"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_model_dispersion_current"
            )

        # ── Faz 24: Portfolio risk phase gauges ─────────────────────────────
        for _gn, _gd in (
            ("portfolio_risk_permission", "Portfolio risk izni: 0=ALLOW 1=BLOCK 2=HALT"),
            ("portfolio_risk_score", "Portfolio risk skoru [0,1]"),
            ("portfolio_risk_var_max", "Portfolio VaR max (3 yontem) fraksiyon"),
            ("portfolio_risk_cvar", "Portfolio CVaR / Expected Shortfall fraksiyon"),
            ("portfolio_risk_hhi", "Herfindahl konsantrasyon endeksi [0,1]"),
        ):
            try:
                self._gauges[_gn] = Gauge(f"{namespace}_{_gn}", _gd)
            except ValueError:
                from prometheus_client import REGISTRY

                self._gauges[_gn] = REGISTRY._names_to_collectors.get(
                    f"{namespace}_{_gn}"
                )

        # ── VR-21: Multi-labeled VaR/CVaR full suite ─────────────────────────
        # var_topology sentinel
        self._prometheus_var_full_suite = True

        try:
            self._gauges["var_pct"] = Gauge(
                f"{namespace}_var_pct",
                "VaR as fraction of NAV (multi-dimensional)",
                ["conf", "model", "scope"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_pct"
            )
        try:
            self._gauges["cvar_pct"] = Gauge(
                f"{namespace}_cvar_pct",
                "CVaR / Expected Shortfall as fraction of NAV",
                ["conf", "model", "scope"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["cvar_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_cvar_pct"
            )
        try:
            self._gauges["stressed_var_pct"] = Gauge(
                f"{namespace}_stressed_var_pct",
                "Stressed VaR (Basel 2.5) as fraction of NAV",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["stressed_var_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_stressed_var_pct"
            )
        try:
            self._gauges["component_var_pct"] = Gauge(
                f"{namespace}_component_var_pct",
                "Component VaR per symbol as fraction of portfolio VaR",
                ["symbol"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["component_var_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_component_var_pct"
            )
        try:
            self._gauges["var_model_dispersion_pct"] = Gauge(
                f"{namespace}_var_model_dispersion_pct",
                "Model dispersion: max(VaR) / min(VaR) - 1",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_model_dispersion_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_model_dispersion_pct"
            )
        try:
            self._gauges["var_limit_utilisation"] = Gauge(
                f"{namespace}_var_limit_utilisation",
                "VaR / limit ratio (0-1+): approaching 1.0 means near limit",
                ["level"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_limit_utilisation"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_limit_utilisation"
            )

        # ── Basel FRTB 10-day VaR/CVaR ──────────────────────────────────────
        try:
            self._gauges["var_10d_99_pct"] = Gauge(
                f"{namespace}_var_10d_99_pct",
                "10-day VaR 99% (Basel FRTB sqrt-10 scaling)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["var_10d_99_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_var_10d_99_pct"
            )
        try:
            self._gauges["cvar_10d_975_pct"] = Gauge(
                f"{namespace}_cvar_10d_975_pct",
                "10-day CVaR 97.5% (Basel FRTB sqrt-10 scaling)",
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._gauges["cvar_10d_975_pct"] = REGISTRY._names_to_collectors.get(
                f"{namespace}_cvar_10d_975_pct"
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

    def record_pnl_attribution(
        self,
        explained_pct: float,
        unexplained_pct: float,
        drift_detected: bool,
    ) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["pnl_explained_pct"].set(explained_pct)
            self._gauges["pnl_unexplained_pct"].set(unexplained_pct)
            self._gauges["pnl_attribution_health"].set(0.0 if drift_detected else 1.0)
        except Exception as exc:
            log.debug("MetricsExporter.record_pnl_attribution hata: %s", exc)

    def record_traffic_light(
        self, zone: str, exceedances: int, capital_addon: float,
    ) -> None:
        if not self._enabled:
            return
        zone_map = {"GREEN": 0.0, "YELLOW": 1.0, "RED": 2.0}
        try:
            self._gauges["var_traffic_light"].set(zone_map.get(zone.upper(), -1.0))
            self._gauges["var_traffic_light_exceedances"].set(float(exceedances))
            self._gauges["var_traffic_light_capital_addon"].set(capital_addon)
        except Exception as exc:
            log.debug("MetricsExporter.record_traffic_light hata: %s", exc)

    def record_christoffersen(self, ind_pvalue: float, cc_pvalue: float) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["christoffersen_ind_pvalue"].set(ind_pvalue)
            self._gauges["christoffersen_cc_pvalue"].set(cc_pvalue)
        except Exception as exc:
            log.debug("MetricsExporter.record_christoffersen hata: %s", exc)

    def record_pre_trade_var_gate(
        self,
        approved: bool,
        new_var: float,
        marginal_var: float,
    ) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["pre_trade_var_gate_passed"].set(1.0 if approved else 0.0)
            self._gauges["pre_trade_var_gate_new_var"].set(new_var)
            self._gauges["pre_trade_var_gate_marginal_var"].set(marginal_var)
        except Exception as exc:
            log.debug("MetricsExporter.record_pre_trade_var_gate hata: %s", exc)

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

    def record_var_breach(
        self,
        breach_code: Optional[str],
        var_99: float,
        cvar_975: float,
        model_dispersion: float,
    ) -> None:
        """VR-19: VaR breach kill-switch metrikleri."""
        if not self._enabled:
            return
        code_map = {
            None: 0.0,
            "var_99_breach": 1.0,
            "cvar_975_breach": 2.0,
            "stressed_var_breach": 3.0,
        }
        try:
            self._gauges["var_breach_kill_switch"].set(code_map.get(breach_code, 0.0))
            self._gauges["var_99_current"].set(var_99)
            self._gauges["cvar_975_current"].set(cvar_975)
            self._gauges["model_dispersion_current"].set(model_dispersion)
        except Exception as exc:
            log.debug("MetricsExporter.record_var_breach hata: %s", exc)

    def record_var_cap(self, cap_binding: bool, capped_size: float) -> None:
        if not self._enabled:
            return
        try:
            self._gauges["position_sizer_var_cap_active"].set(1.0 if cap_binding else 0.0)
            self._gauges["position_sizer_var_capped_size"].set(capped_size)
        except Exception as exc:
            log.debug("MetricsExporter.record_var_cap hata: %s", exc)

    def record_portfolio_risk(self, result: Dict[str, Any]) -> None:
        """Faz 24 — portfolio risk phase Prometheus kaydı."""
        if not self._enabled:
            return
        try:
            perm = result.get("trade_permission", "ALLOW")
            perm_val = {"ALLOW": 0.0, "BLOCK": 1.0, "HALT": 2.0}.get(perm, -1.0)
            self._gauges["portfolio_risk_permission"].set(perm_val)
            self._gauges["portfolio_risk_score"].set(float(result.get("risk_score", 0)))
            pr = result.get("portfolio_risk", {})
            self._gauges["portfolio_risk_var_max"].set(float(pr.get("var_max", 0)))
            self._gauges["portfolio_risk_cvar"].set(float(pr.get("cvar", 0)))
            self._gauges["portfolio_risk_hhi"].set(float(pr.get("herfindahl_hhi", 0)))
        except Exception as exc:
            log.debug("MetricsExporter.record_portfolio_risk hata: %s", exc)

    def record_host_ntp(self, synced: Optional[bool]) -> None:
        if not self._enabled:
            return
        val = -1.0 if synced is None else (1.0 if synced else 0.0)
        try:
            self._gauges["host_ntp_synchronized"].set(val)
        except Exception as exc:
            log.debug("MetricsExporter.record_host_ntp hata: %s", exc)

    # ── VR-21: Comprehensive VaR suite recorder ──────────────────────────────

    def record_var_suite(
        self,
        metrics: Any,
        *,
        limits: Any = None,
        component_var: Optional[Dict[str, float]] = None,
    ) -> None:
        """VR-21: Tek çağrıda tüm VaR/CVaR/stress metriklerini Prometheus'a yazar.

        Parameters
        ----------
        metrics : RiskMetrics
            ``RiskEngine.compute()`` çıktısı.
        limits : VaRLimits, optional
            Aktif limit seti. Verilirse limit utilisation gauge'ları güncellenir.
        component_var : dict, optional
            ``{symbol: component_var_fraction}`` sözlüğü. RiskMetrics'te yoksa
            ayrıca verilebilir.
        """
        if not self._enabled:
            return

        # ── Per-model VaR at each confidence ─────────────────────────────────
        _var_map = {
            ("95", "historical", "portfolio"): "var_historical_95",
            ("95", "parametric_t", "portfolio"): "var_parametric_95",
            ("95", "monte_carlo", "portfolio"): "var_monte_carlo_95",
            ("95", "cornish_fisher", "portfolio"): "var_cornish_fisher_95",
            ("95", "aggregate", "portfolio"): "var_for_limits_95",
            ("99", "historical", "portfolio"): "var_historical_99",
            ("99", "parametric_t", "portfolio"): "var_parametric_99",
            ("99", "monte_carlo", "portfolio"): "var_monte_carlo_99",
            ("99", "cornish_fisher", "portfolio"): "var_cornish_fisher_99",
            ("99", "aggregate", "portfolio"): "var_for_limits_99",
            ("99", "evt", "portfolio"): "var_evt_99",
            ("95", "fhs", "portfolio"): "var_fhs_95",
            ("99", "fhs", "portfolio"): "var_fhs_99",
            ("95", "regime", "portfolio"): "var_regime_conditional_95",
            ("99", "regime", "portfolio"): "var_regime_conditional_99",
        }
        for (conf, model, scope), attr in _var_map.items():
            val = getattr(metrics, attr, None)
            if val is not None:
                try:
                    self._gauges["var_pct"].labels(
                        conf=conf, model=model, scope=scope,
                    ).set(float(val))
                except Exception:
                    pass

        # ── Per-model CVaR ───────────────────────────────────────────────────
        _cvar_map = {
            ("95", "historical", "portfolio"): "cvar_historical_95",
            ("95", "parametric", "portfolio"): "cvar_parametric_95",
            ("95", "monte_carlo", "portfolio"): "cvar_monte_carlo_95",
            ("99", "historical", "portfolio"): "cvar_historical_99",
            ("99", "parametric", "portfolio"): "cvar_parametric_99",
            ("99", "monte_carlo", "portfolio"): "cvar_monte_carlo_99",
            ("975", "aggregate", "portfolio"): "cvar_975_1d",
            ("95", "aggregate", "portfolio"): "cvar_95_1d",
            ("99", "aggregate", "portfolio"): "cvar_99_1d",
            ("99", "evt", "portfolio"): "cvar_evt_99",
            ("95", "fhs", "portfolio"): "cvar_fhs_95",
            ("99", "fhs", "portfolio"): "cvar_fhs_99",
        }
        for (conf, model, scope), attr in _cvar_map.items():
            val = getattr(metrics, attr, None)
            if val is not None:
                try:
                    self._gauges["cvar_pct"].labels(
                        conf=conf, model=model, scope=scope,
                    ).set(float(val))
                except Exception:
                    pass

        # ── Stressed VaR ─────────────────────────────────────────────────────
        svar = getattr(metrics, "stressed_var", None)
        if svar is not None:
            try:
                self._gauges["stressed_var_pct"].set(float(svar))
            except Exception:
                pass

        # ── 10-day VaR/CVaR (Basel FRTB) ─────────────────────────────────────
        for attr, gauge_key in (
            ("var_10d_99", "var_10d_99_pct"),
            ("cvar_10d_975", "cvar_10d_975_pct"),
        ):
            val = getattr(metrics, attr, None)
            if val is not None:
                try:
                    self._gauges[gauge_key].set(float(val))
                except Exception:
                    pass

        # ── Model dispersion ─────────────────────────────────────────────────
        disp = getattr(metrics, "model_dispersion_pct", None)
        if disp is not None:
            try:
                self._gauges["var_model_dispersion_pct"].set(float(disp))
            except Exception:
                pass

        # ── Component VaR per symbol ─────────────────────────────────────────
        comp = component_var or getattr(metrics, "component_var_per_position", None) or {}
        _vt = getattr(metrics, "var_for_limits_95", None)
        var_total = float(_vt) if _vt is not None and _vt != 0.0 else 0.0
        for symbol, cv in comp.items():
            ratio = abs(float(cv)) / abs(var_total) if abs(var_total) > 1e-12 else 0.0
            try:
                self._gauges["component_var_pct"].labels(symbol=symbol).set(ratio)
            except Exception:
                pass

        # ── Limit utilisation ────────────────────────────────────────────────
        if limits is not None:
            var_99 = getattr(metrics, "var_99_1d", 0.0) or 0.0
            cvar_975 = getattr(metrics, "cvar_975_1d", 0.0) or 0.0
            stressed = getattr(metrics, "stressed_var", 0.0) or 0.0
            lvar_val = getattr(metrics, "lvar", 0.0) or 0.0

            _util_map = {
                "var_99": (var_99, getattr(limits, "max_var_total_pct", 1.0)),
                "cvar_975": (cvar_975, getattr(limits, "max_cvar_total_pct", 1.0)),
                "stressed_var": (stressed, getattr(limits, "max_stressed_var_total_pct", 1.0)),
                "lvar": (lvar_val, getattr(limits, "max_lvar_to_nav", 1.0)),
            }
            for level, (current, limit) in _util_map.items():
                util = current / limit if limit > 1e-12 else 0.0
                try:
                    self._gauges["var_limit_utilisation"].labels(level=level).set(util)
                except Exception:
                    pass

    # ── Durum sorgusu ─────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._enabled

    def __repr__(self) -> str:
        return f"MetricsExporter(enabled={self._enabled} port={self._port} ns={self._ns})"
