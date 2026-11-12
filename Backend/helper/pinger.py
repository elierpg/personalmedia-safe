import asyncio
import traceback

import aiohttp

from Backend.helper.settings_manager import SettingsManager
from Backend.logger import LOGGER


#----- Render free web services spin down after 15 minutes without inbound traffic.
#----- Self-ping the public status page every 10 minutes so the idle window never elapses.
#----- The request leaves through the public URL, so Render counts it as inbound traffic.
KEEPALIVE_INTERVAL = 600   # 10 minutes — must stay below the 15 minute idle window
KEEPALIVE_RETRY = 60       # retry quickly if a ping fails
KEEPALIVE_FIRST = 120      # first ping shortly after boot


async def _ping_once() -> bool:
    base = (SettingsManager.current().base_url or "").rstrip("/")
    if not base:
        LOGGER.warning("Ping skipped: base_url is not configured")
        return True

    ping_url = f"{base}/status"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(
                ping_url,
                allow_redirects=True,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as resp:
                if 200 <= resp.status < 400:
                    LOGGER.info("Keep-alive ping %s — Status: %s", ping_url, resp.status)
                    return True

                LOGGER.warning(
                    "Keep-alive ping to %s returned %s (check base_url / reverse proxy)",
                    ping_url,
                    resp.status,
                )
                return False
    except asyncio.TimeoutError:
        LOGGER.warning("Keep-alive ping timed out: %s", ping_url)
        return False
    except Exception:
        LOGGER.error("Keep-alive ping failed:\n" + traceback.format_exc())
        return False


#----- Periodically self-ping the public status page to keep the instance awake
async def ping():
    await asyncio.sleep(KEEPALIVE_FIRST)

    while True:
        ok = await _ping_once()
        await asyncio.sleep(KEEPALIVE_INTERVAL if ok else KEEPALIVE_RETRY)
