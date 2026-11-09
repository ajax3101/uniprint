"""UniPrint application package."""


def main() -> None:
    """Run the local development server."""
    import uvicorn

    uvicorn.run("uniprint.api:app", host="127.0.0.1", port=8000, reload=False)
