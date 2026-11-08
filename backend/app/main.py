from contextlib import asynccontextmanager

from fastapi import FastAPI

from .categorization.providers import get_provider
from .routers import accounts, auth, dashboard, transactions, uploads


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on the first upload, if LLM_PROVIDER is misconfigured
    # (for example gemini without GEMINI_API_KEY).
    get_provider()
    yield


app = FastAPI(title="Spendlens", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(uploads.router)
app.include_router(transactions.router)
app.include_router(dashboard.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
