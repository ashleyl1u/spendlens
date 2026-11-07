from fastapi import FastAPI

app = FastAPI(title="Spendlens")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
