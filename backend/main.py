"""
Morning Edge - Pre-Market Briefing System
FastAPI Backend Application
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    from backend.config import validate_config
    validate_config()
    logger.info("Morning Edge Pre-Market Briefing System starting up")
    yield
    logger.info("Shutting down")


# Create FastAPI app
app = FastAPI(
    title="Morning Edge",
    description="US Stock Pre-Market Briefing System",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors_origins_str = os.environ.get("CORS_ORIGINS", "").strip()
allow_origins = _default_origins if not _cors_origins_str else [o.strip().rstrip("/") for o in _cors_origins_str.split(",") if o.strip()]
logger.info("CORS allowed_origins: %s", allow_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from backend.routers.system import router as system_router
from backend.routers.watchlist import router as watchlist_router
from backend.routers.briefing import router as briefing_router
from backend.routers.macro import router as macro_router
from backend.routers.stories import router as stories_router
from backend.routers.news import router as news_router
from backend.routers.stocks import router as stocks_router

app.include_router(system_router)
app.include_router(watchlist_router)
app.include_router(briefing_router)
app.include_router(macro_router)
app.include_router(stories_router)
app.include_router(news_router)
app.include_router(stocks_router)


# Run with: uvicorn backend.main:app --reload  or  python -m backend.main (respects PORT env)
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
