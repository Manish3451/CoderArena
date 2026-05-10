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

    try:
        pool = await get_pool_async()
        if pool:
            log.info("db connected")

            async with pool.acquire() as conn:
                from arena.match.service import seed_problems
                await seed_problems(conn)
                log.info("problems seeded")
        else:
            log.warning("DATABASE_URL not set — using in-memory mode")
    except Exception as e:
        log.warning(f"DB connection failed, using in-memory mode: {e}")

    yield

    # Shutdown
    await close_pool()
    log.info("db pool closed")


app = FastAPI(
    title="CodeArena API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.app_url,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://coder-arean-frontend.vercel.app",
    ],
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
