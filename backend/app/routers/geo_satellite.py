from fastapi import APIRouter
from app.models import GeoSatelliteRequest, GeoSatelliteResponse
from app.services.geo_satellite_service import GeoSatelliteService
from loguru import logger
import time

router = APIRouter(tags=["Geo Satellite"])

@router.post(
    "/geo-satellite/observations",
    response_model=GeoSatelliteResponse,
    summary="Query geo-satellite observations",
    description=(
        "Return geo-satellite observation metadata and sample imagery links. "
        "This endpoint is documented in OpenAPI and can be used to query satellite "
        "mission metadata or imagery availability for a given location and time."
    ),
)
async def get_geo_satellite_observations(request: GeoSatelliteRequest):
    """Query geo-satellite observation metadata."""
    start_time = time.time()
    logger.info(f"Received geo-satellite query for satellite: '{request.satellite_id or 'any'}'.")

    observations = await GeoSatelliteService.query_observations(request)

    processing_time_ms = int((time.time() - start_time) * 1000)
    return GeoSatelliteResponse(
        observations=observations,
        requested=request,
        processingTimeMs=processing_time_ms,
    )
