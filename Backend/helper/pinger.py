import asyncio
import traceback
from datetime import datetime, timezone

import aiohttp

from Backend.helper.settings_manager import SettingsManager
from Backend.logger import LOGGER


#----- Render free web services spin down after 15 minutes without inbound traffic.
#----- Self-ping the public status page every 10 minutes so the idle window never elapses.
#----- The request leaves through the public URL, so Render counts it as inbound traffic.
KEEPALIVE_INTERVAL = 600   # 10 minutes — must stay below the 15 minute idle window
KEEPALIVE_RETRY = 60       # retry quickly if a ping fails
KEEPALIVE_FIRST = 120      # first ping shortly after boot

_PING_STATE = {
    "pings": 0,
    "failures": 0,
    "last_ping": None,
    "last_status": None,
    "last_ok": None,
}


def get_ping_status() -> dict:
    """Diagnostics for /api/admin/health: proves the keep-alive loop is running."""
    return {
        "interval_seconds": KEEPALIVE_INTERVAL,
        "idle_window_seconds": 900,
        **_PING_STATE,
    }


async def _ping_once() -> bool:
    base = (SettingsManager.current().base_url or "").rstrip("/")
    if not base:
        LOGGER.warning("Ping skipped: base_url is not configured")
        return True

    ping_url = f"{base}/status"
    _PING_STATE["last_ping"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(
                ping_url,
                allow_redirects=True,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as resp:
                _PING_STATE["last_status"] = resp.status
                if 200 <= resp.status < 400:
                    _PING_STATE["pings"] += 1
                    _PING_STATE["last_ok"] = True
                    LOGGER.info("Keep-alive ping %s — Status: %s", ping_url, resp.status)
                    return True

                _PING_STATE["failures"] += 1
                _PING_STATE["last_ok"] = False
                LOGGER.warning(
                    "Keep-alive ping to %s returned %s (check base_url / reverse proxy)",
                    ping_url,
                    resp.status,
                )
                return False
    except asyncio.TimeoutError:
        _PING_STATE["failures"] += 1
        _PING_STATE["last_ok"] = False
        LOGGER.warning("Keep-alive ping timed out: %s", ping_url)
        return False
    except Exception:
        _PING_STATE["failures"] += 1
        _PING_STATE["last_ok"] = False
        LOGGER.error("Keep-alive ping failed:\n" + traceback.format_exc())
        return False


#----- Periodically self-ping the public status page to keep the instance awake
async def ping():
    await asyncio.sleep(KEEPALIVE_FIRST)

    while True:
        ok = await _ping_once()
        await asyncio.sleep(KEEPALIVE_INTERVAL if ok else KEEPALIVE_RETRY)
