import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from arena.config import settings
from arena.db import get_pool_async, close_pool
from arena.auth.router import router as auth_router
from arena.match.router import router as match_router
from arena.ws.router import router as ws_router
from arena.sse.router import router as sse_router

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    log.info("starting", environment=settings.environment)

    if not settings.database_url:
        log.error("DATABASE_URL is not set — auth and matches will not work")
    else:
        try:
            pool = await get_pool_async()
            log.info("db connected")
            async with pool.acquire() as conn:
                from arena.match.service import seed_problems
                await seed_problems(conn)
                log.info("problems seeded")
        except Exception as e:
            log.error(f"DB startup failed: {e}")
            # Don't crash — let /health work so we can debug, but log loudly

    yield

    # Shutdown
    try:
        await close_pool()
        log.info("db pool closed")
    except Exception:
        pass


app = FastAPI(
    title="CodeArena API",
    version="0.1.0",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://coder-arean-frontend.vercel.app",
]

if settings.app_url and settings.app_url not in ALLOWED_ORIGINS:
    ALLOWED_ORIGINS.append(settings.app_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Allow any Vercel preview URL on the same project (coder-arean-frontend-*.vercel.app)
    allow_origin_regex=r"https://coder-arean-frontend.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(match_router)
app.include_router(ws_router)
app.include_router(sse_router)


@app.get("/health")
async def health():
    return {"ok": True, "env": settings.environment}


@app.get("/")
async def root():
    return {"service": "CodeArena API", "docs": "/docs"}
