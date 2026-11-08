from fastapi import FastAPI

from .routers import auth

app = FastAPI(title="Spendlens")
app.include_router(auth.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
