import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(
    title="Heat Resource Optimizer",
    description="AI-powered heat mitigation resource optimization system",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # Localhost by default; override for deployed frontends, e.g.
    # ALLOWED_ORIGIN_REGEX=^https://sentinel-frontend\.onrender\.com$
    allow_origin_regex=os.getenv(
        "ALLOWED_ORIGIN_REGEX",
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "heat-resource-optimizer",
    }
