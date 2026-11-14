import asyncio

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from Backend import __version__
from Backend.helper.settings_manager import SettingsManager
from Backend.fastapi.themes import get_theme, theme_key
from Backend.fastapi.routes.api_routes import (
    add_custom_catalog_item_api,
    apply_media_rescan_api,
    assign_plan_api,
    auto_catalog_sync_status_api,
    auto_sync_custom_catalogs_api,
    cancel_dbcheck_api,
    cancel_duplicate_check_api,
    cancel_scan_api,
    clear_cache_api,
    clear_stream_analytics_api,
    create_custom_catalog_api,
    create_token_api,
    grant_lifetime_api,
    set_token_lifetime_api,
    set_token_expiry_api,
    dbcheck_status_api,
    duplicate_check_status_api,
    delete_custom_catalog_api,
    delete_media_api,
    delete_movie_quality_api,
    export_config_api,
    import_config_api,
    delete_tv_episode_api,
    delete_tv_quality_api,
    delete_tv_season_api,
    download_logs_api,
    get_admin_stats_api,
    get_db_stats_api,
    get_all_tokens_api,
    get_auto_catalog_settings_api,
    get_catalog_order_api,
    update_catalog_order_api,
    get_user_activity_api,
    session_send_code_api,
    session_verify_code_api,
    session_verify_password_api,
    session_status_api,
    session_disconnect_api,
    session_reconnect_api,
    session_remove_api,
    get_custom_catalog_items_api,
    get_dead_links_api,
    get_media_visibility_api,
    get_stream_analytics_api,
    get_settings_api,
    get_logs_api,
    get_manual_session_api,
    get_system_stats_api,
    get_tools_channels_api,
    bot_admin_scan_api,
    bot_admin_apply_api,
    bot_admin_apply_status_api,
    clear_manual_session_api,
    search_manual_session_api,
    set_manual_session_api,
    health_api,
    health_report_api,
    version_status_api,
    setup_status_api,
    link_token_user_api,
    list_custom_catalogs_api,
    list_media_api,
    manual_add_media_api,
    list_manual_add_catalogs_api,
    resolve_manual_metadata_api,
    purge_dead_links_api,
    purge_duplicates_api,
    remove_custom_catalog_item_api,
    resolve_telegram_api,
    resolve_subtitle_api,
    list_subtitle_languages_api,
    list_subtitles_api,
    add_subtitles_api,
    remove_subtitle_api,
    restart_app_api,
    revoke_token_api,
    scan_status_api,
    search_catalog_media_api,
    set_media_visibility_api,
    search_media_rescan_api,
    tag_media_api,
    speed_test_api,
    speed_test_stream_api,
    start_dbcheck_api,
    start_duplicate_check_api,
    start_scan_api,
    update_auto_catalog_settings_api,
    update_custom_catalog_api,
    update_media_api,
    update_settings_api,
    update_token_limits_api,
)
from Backend.fastapi.routes.stream_routes import decay_client_failures
from Backend.fastapi.routes.stream_routes import router as stream_router
from Backend.fastapi.routes.addon_routes import router as addon_router
from Backend.fastapi.routes.webdav_routes import router as webdav_router
from Backend.fastapi.routes.template_routes import (
    admin_access_page,
    admin_dashboard_page,
    custom_catalogs_page,
    dashboard_page,
    edit_media_page,
    login_page,
    login_post,
    logout,
    media_management_page,
    settings_page,
    set_theme,
    tools_page,
)
from Backend.fastapi.security.credentials import require_auth
from Backend.pyrofork.bot import work_loads_summary

templates = Jinja2Templates(directory="Backend/fastapi/templates")

app = FastAPI(
    title="Mi Media Server",
    description="Servidor multimedia personal autoalojado para uso privado.",
    version=__version__
)

#----- Middleware

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    app.mount("/static", StaticFiles(directory="Backend/fastapi/static"), name="static")
except Exception:
    pass


@app.on_event("startup")
async def _startup():
    asyncio.create_task(decay_client_failures())
    from Backend.helper.version_check import version_check_loop
    asyncio.create_task(version_check_loop())


#----- Media routers
app.include_router(stream_router)
app.include_router(addon_router)
app.include_router(webdav_router)


#----- Public routes (no authentication)
@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return await login_page(request)

@app.post("/login", response_class=HTMLResponse)
async def login_post_route(request: Request, username: str = Form(...), password: str = Form(...)):
    return await login_post(request, username, password)

@app.get("/logout")
async def logout_route(request: Request):
    return await logout(request)

@app.post("/set-theme")
async def set_theme_route(request: Request, theme: str = Form(None)):
    return await set_theme(request, theme)

def _hex_to_rgb(h: str):
    h = (h or "#2563eb").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return (37, 99, 235)

def _make_app_icon_png(size: int = 180, primary: str = "#2563eb") -> bytes:
    import struct, zlib
    pr, pg, pb = _hex_to_rgb(primary)
    w = h = size
    # simple play triangle
    cx, cy = w * 0.54, h * 0.5
    tri_w, tri_h = w * 0.28, h * 0.34
    x0, y0 = cx - tri_w * 0.45, cy - tri_h / 2
    x1, y1 = cx - tri_w * 0.45, cy + tri_h / 2
    x2, y2 = cx + tri_w * 0.55, cy
    def inside_tri(px, py):
        # barycentric
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-6:
            return False
        a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
        b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
        c = 1 - a - b
        return a >= -0.01 and b >= -0.01 and c >= -0.01
    raw = bytearray()
    radius = w * 0.22
    for y in range(h):
        raw.append(0)  # filter
        for x in range(w):
            # rounded rect mask
            dx = max(abs(x - w/2) - (w/2 - radius), 0)
            dy = max(abs(y - h/2) - (h/2 - radius), 0)
            if dx*dx + dy*dy > radius*radius:
                raw.extend((0, 0, 0, 0))
            elif inside_tri(x + 0.5, y + 0.5):
                raw.extend((255, 255, 255, 255))
            else:
                raw.extend((pr, pg, pb, 255))
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    return png

@app.get("/manifest.webmanifest")
async def pwa_manifest(request: Request):
    theme = get_theme(theme_key(request))
    return JSONResponse(
        {
            "id": "/",
            "name": "Mi Biblioteca",
            "short_name": "Mi Biblioteca",
            "description": "Gestión multimedia personal",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "display_override": ["standalone", "minimal-ui"],
            "orientation": "portrait-primary",
            "background_color": theme["colors"]["background"],
            "theme_color": theme["colors"]["primary"],
            "lang": "es",
            "categories": ["entertainment", "utilities"],
            "icons": [
                {
                    "src": "/pwa-icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any"
                },
                {
                    "src": "/pwa-icon.svg",
                    "sizes": "512x512",
                    "type": "image/svg+xml",
                    "purpose": "maskable"
                },
                {
                    "src": "/apple-touch-icon.png",
                    "sizes": "180x180",
                    "type": "image/png",
                    "purpose": "any"
                }
            ]
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"}
    )

@app.get("/pwa-icon.svg")
async def pwa_icon(request: Request):
    theme = get_theme(theme_key(request))
    primary = theme["colors"]["primary"]
    on_primary = theme["colors"].get("on_primary", "#FFFFFF")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
        f'<rect width="512" height="512" rx="112" fill="{primary}"/>'
        f'<path d="M210 160l168 96-168 96z" fill="{on_primary}"/>'
        f'</svg>'
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache"}
    )

@app.get("/apple-touch-icon.png")
async def apple_touch_icon(request: Request):
    theme = get_theme(theme_key(request))
    primary = theme["colors"]["primary"]
    try:
        png = _make_app_icon_png(180, primary)
    except Exception:
        # fallback tiny transparent-ish png generation attempt
        png = _make_app_icon_png(180, "#2563eb")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"}
    )

@app.get("/sw.js")
async def service_worker():
    js = r"""
const CACHE = 'mibiblioteca-v3';
const APP_SHELL = ['/', '/login', '/manifest.webmanifest'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(APP_SHELL).catch(()=>{})));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // never cache API/stream/dl responses
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/dl/') || url.pathname.startsWith('/v1/')) {
    e.respondWith(fetch(req));
    return;
  }
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(()=>{});
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match('/login'))));
    return;
  }
  e.respondWith(caches.match(req).then(cached => cached || fetch(req).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)).catch(()=>{}); }
    return res;
  }).catch(() => cached)));
});
"""
    return Response(
        content=js.strip(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"}
    )

#----- Public liveness probe (no auth, no DB). Used by the keep-alive pinger and uptime monitors.
@app.get("/status")
async def public_status():
    return JSONResponse(
        {"status": "ok", "version": __version__},
        headers={"Cache-Control": "no-store, no-cache, max-age=0"},
    )

@app.get("/open/{app_name}/{media_type}/{content_id}", response_class=HTMLResponse)
async def open_in_app(app_name: str, media_type: str, content_id: str, _: bool = Depends(require_auth)):
    base = SettingsManager.current().base_url.rstrip("/")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Abrir</title></head><body><p><a href="{base}/">Ir al panel</a></p></body></html>"""
    return HTMLResponse(html)


#----- Protected routes (authentication required)
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, _: bool = Depends(require_auth)):
    return await dashboard_page(request, _)

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, _: bool = Depends(require_auth)):
    return await admin_dashboard_page(request, _)

@app.get("/media/manage", response_class=HTMLResponse)
async def media_management(request: Request, media_type: str = "movie", custom: bool = False, _: bool = Depends(require_auth)):
    return await media_management_page(request, media_type, custom, _)

@app.get("/catalogs", response_class=HTMLResponse)
async def custom_catalogs(request: Request, _: bool = Depends(require_auth)):
    return await custom_catalogs_page(request, _)

@app.get("/media/edit", response_class=HTMLResponse)
async def edit_media(request: Request, tmdb_id: int, db_index: int, media_type: str, _: bool = Depends(require_auth)):
    return await edit_media_page(request, tmdb_id, db_index, media_type, _)

@app.get("/api/media/list")
async def list_media(
    media_type: str = Query("movie", regex="^(movie|tv)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    search: str = Query("", max_length=100),
    custom: bool = Query(False),
    _: bool = Depends(require_auth)
):
    return await list_media_api(media_type, page, page_size, search, custom)

@app.delete("/api/media/delete")
async def delete_media(tmdb_id: int, db_index: int, media_type: str, _: bool = Depends(require_auth)):
    return await delete_media_api(tmdb_id, db_index, media_type)

@app.put("/api/media/update")
async def update_media(request: Request, tmdb_id: int, db_index: int, media_type: str, _: bool = Depends(require_auth)):
    return await update_media_api(request, tmdb_id, db_index, media_type)

@app.delete("/api/media/delete-quality")
async def delete_movie_quality(tmdb_id: int, db_index: int, id: str, _: bool = Depends(require_auth)):
    return await delete_movie_quality_api(tmdb_id, db_index, id)

@app.delete("/api/media/delete-tv-quality")
async def delete_tv_quality(tmdb_id: int, db_index: int, season: int, episode: int, id: str, _: bool = Depends(require_auth)):
    return await delete_tv_quality_api(tmdb_id, db_index, season, episode, id)

@app.delete("/api/media/delete-tv-episode")
async def delete_tv_episode(tmdb_id: int, db_index: int, season: int, episode: int, _: bool = Depends(require_auth)):
    return await delete_tv_episode_api(tmdb_id, db_index, season, episode)

@app.delete("/api/media/delete-tv-season")
async def delete_tv_season(tmdb_id: int, db_index: int, season: int, _: bool = Depends(require_auth)):
    return await delete_tv_season_api(tmdb_id, db_index, season)

@app.get("/api/system/workloads")
async def get_workloads(_: bool = Depends(require_auth)):
    try:
        return {"loads": work_loads_summary()}
    except Exception:
        return {"loads": {}}

@app.post("/api/tokens")
async def create_token(payload: dict, _: bool = Depends(require_auth)):
    return await create_token_api(payload)

@app.put("/api/tokens/{token}")
async def update_token(token: str, payload: dict, _: bool = Depends(require_auth)):
    return await update_token_limits_api(token, payload)

@app.delete("/api/tokens/{token}")
async def revoke_token(token: str, _: bool = Depends(require_auth)):
    return await revoke_token_api(token)

@app.get("/api/system/stats")
async def get_system_stats(_: bool = Depends(require_auth)):
    return await get_system_stats_api()

@app.get("/api/admin/system-stats")
async def admin_system_stats(_: bool = Depends(require_auth)):
    return await get_admin_stats_api()

@app.post("/api/admin/clear-cache")
async def clear_cache(_: bool = Depends(require_auth)):
    return await clear_cache_api()

@app.get("/api/admin/dead-links")
async def get_dead_links(_: bool = Depends(require_auth)):
    return await get_dead_links_api()

@app.get("/api/admin/stream-analytics")
async def get_stream_analytics(_: bool = Depends(require_auth)):
    return await get_stream_analytics_api()

@app.get("/api/admin/user-activity")
async def get_user_activity(page: int = 1, per_page: int = 5, _: bool = Depends(require_auth)):
    return await get_user_activity_api(page, per_page)

@app.post("/api/admin/clear-analytics")
async def clear_analytics(_: bool = Depends(require_auth)):
    return await clear_stream_analytics_api()

#----- Access management
@app.get("/admin/access", response_class=HTMLResponse)
async def admin_access(request: Request, _: bool = Depends(require_auth)):
    return await admin_access_page(request, _)

@app.get("/api/admin/access/tokens")
async def get_access_tokens(_: bool = Depends(require_auth)):
    return await get_all_tokens_api()

@app.delete("/api/admin/access/tokens/{token}")
async def delete_access_token(token: str, _: bool = Depends(require_auth)):
    return await revoke_token_api(token)

@app.post("/api/admin/access/users/{user_id}/assign-plan")
async def assign_access_plan(user_id: int, payload: dict, _: bool = Depends(require_auth)):
    days = int(payload.get("days", 0))
    return await assign_plan_api(user_id, days)

@app.patch("/api/admin/access/tokens/{token}/link-user")
async def link_token_to_user(token: str, payload: dict, _: bool = Depends(require_auth)):
    user_id = int(payload.get("user_id", 0))
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    return await link_token_user_api(token, user_id)

@app.patch("/api/admin/access/tokens/{token}/lifetime")
async def set_token_lifetime(token: str, payload: dict, _: bool = Depends(require_auth)):
    return await set_token_lifetime_api(token, payload)

@app.post("/api/admin/access/tokens/{token}/expiry")
async def set_token_expiry(token: str, payload: dict, _: bool = Depends(require_auth)):
    return await set_token_expiry_api(token, payload)

@app.post("/api/admin/access/grant-lifetime")
async def grant_lifetime(_: bool = Depends(require_auth)):
    return await grant_lifetime_api()

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

@app.get("/api/system/speedtest")
async def speed_test(
    quality_id: str = Query(...),
    tmdb_id: int = Query(...),
    db_index: int = Query(...),
    media_type: str = Query(...),
    _: bool = Depends(require_auth)
):
    return await speed_test_api(quality_id, tmdb_id, db_index, media_type)

@app.get("/api/system/speedtest/stream")
async def speed_test_stream(
    quality_id: str = Query(...),
    tmdb_id: int = Query(...),
    db_index: int = Query(...),
    media_type: str = Query(...),
    _: bool = Depends(require_auth)
):
    return await speed_test_stream_api(quality_id, tmdb_id, db_index, media_type)

@app.get("/api/media/rescan/search")
async def search_media_rescan(
    media_type: str,
    query: str,
    year: int | None = None,
    _: bool = Depends(require_auth)
):
    return await search_media_rescan_api(media_type, query, year)

@app.post("/api/media/rescan/apply")
async def apply_media_rescan(
    request: Request,
    tmdb_id: int,
    db_index: int,
    media_type: str,
    _: bool = Depends(require_auth)
):
    return await apply_media_rescan_api(request, tmdb_id, db_index, media_type)

@app.post("/api/media/tag")
async def tag_media(tmdb_id: int, db_index: int, media_type: str, _: bool = Depends(require_auth)):
    return await tag_media_api(tmdb_id, db_index, media_type)


#----- Manual add (custom movie/tv/season/episode/stream)
@app.post("/api/media/resolve-telegram")
async def resolve_telegram(payload: dict, _: bool = Depends(require_auth)):
    return await resolve_telegram_api(payload)

@app.post("/api/media/manual-add")
async def manual_add_media(payload: dict, _: bool = Depends(require_auth)):
    return await manual_add_media_api(payload)

@app.get("/api/media/manual-add/catalogs")
async def manual_add_catalogs(_: bool = Depends(require_auth)):
    return await list_manual_add_catalogs_api()

@app.get("/api/media/manual-add/resolve-meta")
async def manual_add_resolve_meta(media_type: str, selected_id: str, _: bool = Depends(require_auth)):
    return await resolve_manual_metadata_api(media_type, selected_id)


#----- Manual subtitle management
@app.get("/api/media/subtitles/languages")
async def subtitle_languages(_: bool = Depends(require_auth)):
    return list_subtitle_languages_api()

@app.get("/api/media/subtitles")
async def list_subtitles(media_type: str, tmdb_id: int, db_index: int, _: bool = Depends(require_auth)):
    return await list_subtitles_api(media_type, tmdb_id, db_index)

@app.post("/api/media/subtitles/resolve")
async def resolve_subtitle(payload: dict, _: bool = Depends(require_auth)):
    return await resolve_subtitle_api(payload)

@app.post("/api/media/subtitles/add")
async def add_subtitles(payload: dict, _: bool = Depends(require_auth)):
    return await add_subtitles_api(payload)

@app.post("/api/media/subtitles/remove")
async def remove_subtitle_route(payload: dict, _: bool = Depends(require_auth)):
    return await remove_subtitle_api(payload)


#----- Custom catalog management
@app.get("/api/custom-catalogs")
async def list_custom_catalogs(
    tmdb_id: int | None = None,
    db_index: int | None = None,
    media_type: str | None = None,
    _: bool = Depends(require_auth)
):
    return await list_custom_catalogs_api(tmdb_id, db_index, media_type)

@app.post("/api/custom-catalogs")
async def create_custom_catalog(payload: dict, _: bool = Depends(require_auth)):
    return await create_custom_catalog_api(payload)

@app.put("/api/custom-catalogs/{catalog_id}")
async def update_custom_catalog(catalog_id: str, payload: dict, _: bool = Depends(require_auth)):
    return await update_custom_catalog_api(catalog_id, payload)

@app.delete("/api/custom-catalogs/{catalog_id}")
async def delete_custom_catalog(catalog_id: str, _: bool = Depends(require_auth)):
    return await delete_custom_catalog_api(catalog_id)

@app.post("/api/custom-catalogs/media-visibility")
async def set_media_visibility(payload: dict, _: bool = Depends(require_auth)):
    return await set_media_visibility_api(payload)

@app.get("/api/custom-catalogs/media-visibility")
async def get_media_visibility(
    tmdb_id: int,
    db_index: int,
    media_type: str = Query("movie", regex="^(movie|tv|series)$"),
    _: bool = Depends(require_auth)
):
    return await get_media_visibility_api(tmdb_id, db_index, media_type)

@app.get("/api/custom-catalogs/search-media")
async def search_catalog_media(
    query: str,
    media_type: str = Query("movie", regex="^(movie|tv)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    _: bool = Depends(require_auth)
):
    return await search_catalog_media_api(query, media_type, page, page_size)

@app.post("/api/custom-catalogs/auto-sync")
async def auto_sync_custom_catalogs(
    force_refresh: bool = Query(False),
    _: bool = Depends(require_auth)
):
    return await auto_sync_custom_catalogs_api(force_refresh)

@app.get("/api/custom-catalogs/auto-sync/status")
async def auto_catalog_sync_status(_: bool = Depends(require_auth)):
    return await auto_catalog_sync_status_api()

@app.get("/api/custom-catalogs-order")
async def get_catalog_order_route(_: bool = Depends(require_auth)):
    return await get_catalog_order_api()

@app.put("/api/custom-catalogs-order")
async def update_catalog_order_route(payload: dict, _: bool = Depends(require_auth)):
    return await update_catalog_order_api(payload)

@app.get("/api/custom-catalogs/auto-sync/settings")
async def get_auto_catalog_settings_route(_: bool = Depends(require_auth)):
    return await get_auto_catalog_settings_api()

@app.put("/api/custom-catalogs/auto-sync/settings")
async def update_auto_catalog_settings_route(payload: dict, _: bool = Depends(require_auth)):
    return await update_auto_catalog_settings_api(payload)

@app.get("/api/custom-catalogs/{catalog_id}/items")
async def get_custom_catalog_items(
    catalog_id: str,
    media_type: str | None = Query(None, regex="^(movie|tv)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    _: bool = Depends(require_auth)
):
    return await get_custom_catalog_items_api(catalog_id, media_type, page, page_size)

@app.post("/api/custom-catalogs/{catalog_id}/items")
async def add_custom_catalog_item(catalog_id: str, payload: dict, _: bool = Depends(require_auth)):
    return await add_custom_catalog_item_api(catalog_id, payload)

@app.delete("/api/custom-catalogs/{catalog_id}/items")
async def remove_custom_catalog_item(
    catalog_id: str,
    tmdb_id: int,
    db_index: int,
    media_type: str = Query("movie", regex="^(movie|tv)$"),
    _: bool = Depends(require_auth)
):
    return await remove_custom_catalog_item_api(catalog_id, tmdb_id, db_index, media_type)


#----- Settings
@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, _: bool = Depends(require_auth)):
    return await settings_page(request, _)

@app.get("/api/admin/settings")
async def get_settings(_: bool = Depends(require_auth)):
    return await get_settings_api()

@app.put("/api/admin/settings")
async def update_settings(payload: dict, _: bool = Depends(require_auth)):
    return await update_settings_api(payload)


@app.post("/api/admin/settings/formatter-preview")
async def formatter_preview(payload: dict, _: bool = Depends(require_auth)):
    from Backend.helper.stream_formatter import PRESETS, build_parse_value, render
    tpl = PRESETS.get(payload.get("preset")) or {"name": str(payload.get("name") or ""), "description": str(payload.get("description") or "")}
    pv = build_parse_value(str(payload.get("filename") or "video.mkv"), 2_500_000_000, channel="My Channel",
                           meta={"queryType": "movie", "type": "movie"})
    return {"name": render(tpl["name"], pv), "description": render(tpl["description"], pv)}


#----- Telegram user session login (replaces manual USER_SESSION_STRING)
@app.get("/api/admin/settings/session")
async def session_status(_: bool = Depends(require_auth)):
    return await session_status_api()

@app.post("/api/admin/settings/session/send-code")
async def session_send_code(payload: dict, _: bool = Depends(require_auth)):
    return await session_send_code_api(payload)

@app.post("/api/admin/settings/session/verify-code")
async def session_verify_code(payload: dict, _: bool = Depends(require_auth)):
    return await session_verify_code_api(payload)

@app.post("/api/admin/settings/session/verify-password")
async def session_verify_password(payload: dict, _: bool = Depends(require_auth)):
    return await session_verify_password_api(payload)

@app.post("/api/admin/settings/session/disconnect")
async def session_disconnect(_: bool = Depends(require_auth)):
    return await session_disconnect_api()

@app.post("/api/admin/settings/session/reconnect")
async def session_reconnect(_: bool = Depends(require_auth)):
    return await session_reconnect_api()

@app.delete("/api/admin/settings/session")
async def session_remove(_: bool = Depends(require_auth)):
    return await session_remove_api()


#----- System & Maintenance (WebUI replacement for /stats, /log, /restart bot commands)
@app.get("/api/admin/stats")
async def admin_db_stats(_: bool = Depends(require_auth)):
    return await get_db_stats_api()

@app.get("/api/admin/health")
async def admin_health(_: bool = Depends(require_auth)):
    return await health_api()

@app.get("/api/admin/health/report")
async def admin_health_report(fresh: bool = Query(False), _: bool = Depends(require_auth)):
    return await health_report_api(force=fresh)

@app.get("/api/admin/version")
async def admin_version(force: bool = Query(False), _: bool = Depends(require_auth)):
    return await version_status_api(force=force)

@app.get("/api/admin/setup-status")
async def admin_setup_status(_: bool = Depends(require_auth)):
    return await setup_status_api()

@app.get("/api/admin/backup/export")
async def admin_backup_export(_: bool = Depends(require_auth)):
    from fastapi.responses import JSONResponse
    data = await export_config_api()
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": 'attachment; filename="mi-biblioteca-backup.json"'},
    )

@app.post("/api/admin/backup/import")
async def admin_backup_import(payload: dict, _: bool = Depends(require_auth)):
    return await import_config_api(payload)

@app.get("/api/admin/logs")
async def admin_logs(lines: int = Query(300, ge=1, le=2000), _: bool = Depends(require_auth)):
    return await get_logs_api(lines)

@app.get("/api/admin/logs/download")
async def admin_logs_download(_: bool = Depends(require_auth)):
    return await download_logs_api()

@app.post("/api/admin/restart")
async def admin_restart(_: bool = Depends(require_auth)):
    return await restart_app_api()


#----- Tools (WebUI replacement for /scan, /rescan, /dbcheck bot commands)
@app.get("/admin/tools", response_class=HTMLResponse)
async def admin_tools(request: Request, _: bool = Depends(require_auth)):
    return await tools_page(request, _)

@app.get("/api/admin/tools/channels")
async def tools_channels(_: bool = Depends(require_auth)):
    return await get_tools_channels_api()

@app.get("/api/admin/tools/bot-admin/scan")
async def tools_bot_admin_scan(_: bool = Depends(require_auth)):
    return await bot_admin_scan_api()

@app.post("/api/admin/tools/bot-admin/apply")
async def tools_bot_admin_apply(payload: dict, _: bool = Depends(require_auth)):
    return await bot_admin_apply_api(payload)

@app.get("/api/admin/tools/bot-admin/apply/status")
async def tools_bot_admin_apply_status(_: bool = Depends(require_auth)):
    return await bot_admin_apply_status_api()

@app.get("/api/admin/tools/manual-session")
async def tools_manual_session_get(_: bool = Depends(require_auth)):
    return await get_manual_session_api()

@app.get("/api/admin/tools/manual-session/search")
async def tools_manual_session_search(query: str = Query(""), _: bool = Depends(require_auth)):
    return await search_manual_session_api(query)

@app.post("/api/admin/tools/manual-session")
async def tools_manual_session_set(payload: dict, _: bool = Depends(require_auth)):
    return await set_manual_session_api(payload)

@app.delete("/api/admin/tools/manual-session")
async def tools_manual_session_clear(_: bool = Depends(require_auth)):
    return await clear_manual_session_api()

@app.post("/api/admin/tools/scan/start")
async def tools_scan_start(payload: dict, _: bool = Depends(require_auth)):
    return await start_scan_api(payload)

@app.post("/api/admin/tools/scan/cancel")
async def tools_scan_cancel(_: bool = Depends(require_auth)):
    return await cancel_scan_api()

@app.get("/api/admin/tools/scan/status")
async def tools_scan_status(_: bool = Depends(require_auth)):
    return await scan_status_api()

@app.post("/api/admin/tools/dbcheck/start")
async def tools_dbcheck_start(_: bool = Depends(require_auth)):
    return await start_dbcheck_api()

@app.post("/api/admin/tools/dbcheck/cancel")
async def tools_dbcheck_cancel(_: bool = Depends(require_auth)):
    return await cancel_dbcheck_api()

@app.get("/api/admin/tools/dbcheck/status")
async def tools_dbcheck_status(_: bool = Depends(require_auth)):
    return await dbcheck_status_api()

@app.post("/api/admin/tools/dead-links/purge")
async def tools_purge_dead_links(payload: dict | None = None, _: bool = Depends(require_auth)):
    return await purge_dead_links_api(payload)

@app.post("/api/admin/tools/duplicates/start")
async def tools_duplicates_start(_: bool = Depends(require_auth)):
    return await start_duplicate_check_api()

@app.post("/api/admin/tools/duplicates/cancel")
async def tools_duplicates_cancel(_: bool = Depends(require_auth)):
    return await cancel_duplicate_check_api()

@app.get("/api/admin/tools/duplicates/status")
async def tools_duplicates_status(_: bool = Depends(require_auth)):
    return await duplicate_check_status_api()

@app.post("/api/admin/tools/duplicates/purge")
async def tools_duplicates_purge(payload: dict | None = None, _: bool = Depends(require_auth)):
    return await purge_duplicates_api(payload)


@app.exception_handler(401)
async def auth_exception_handler(request: Request, exc):
    # API / stream / WebDAV clients must receive a real 401, not an HTML login redirect.
    path = request.url.path or ""
    if path.startswith(("/webdav", "/dl/", "/sub/", "/v1/", "/api/", "/thumb/")):
        from fastapi.responses import JSONResponse
        detail = getattr(exc, "detail", "Unauthorized")
        headers = {}
        # Preserve WWW-Authenticate for WebDAV Basic auth prompts
        if hasattr(exc, "headers") and exc.headers:
            headers.update(exc.headers)
        return JSONResponse(status_code=401, content={"detail": detail}, headers=headers)
    return RedirectResponse(url="/login", status_code=302)
