from fastapi import FastAPI

from .routers import accounts, auth, transactions, uploads

app = FastAPI(title="Spendlens")
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(uploads.router)
app.include_router(transactions.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
