"""exchange_async — pytest-asyncio ile async testler; yalnızca _ex ağ yüzeyi AsyncMock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_get_order_status_maps_closed_to_filled() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_order = AsyncMock(return_value={"status": "closed"})

    assert await h.get_order_status("1", "BTC/USDT") == "filled"


@pytest.mark.asyncio
async def test_get_order_status_returns_raw_status() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.fetch_order = AsyncMock(return_value={"status": "open"})

    assert await h.get_order_status("1", "BTC/USDT") == "open"


@pytest.mark.asyncio
async def test_cancel_order_success_true() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.cancel_order = AsyncMock(return_value={"status": "canceled"})

    assert await h.cancel_order("1", "BTC/USDT") is True


@pytest.mark.asyncio
async def test_cancel_order_failure_returns_false() -> None:
    import super_otonom.exchange_async as ea

    h = object.__new__(ea.AsyncExchangeHandler)
    h._ex = MagicMock()
    h._ex.cancel_order = AsyncMock(side_effect=RuntimeError("down"))

    assert await h.cancel_order("1", "BTC/USDT") is False
