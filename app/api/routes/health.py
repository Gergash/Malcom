from fastapi import APIRouter

try:
    from app.api.schemas import HealthResponse
except ModuleNotFoundError:
    from api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return HealthResponse(
        status="ok",
        service="InsightFlow Malcom API",
        version="2.0.0",
    )
