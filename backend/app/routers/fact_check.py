from fastapi import APIRouter, HTTPException
from app.models import FactCheckRequest, FactCheckResponse, FactCheckResult
from app.services.verification_pipeline import VerificationPipeline
from loguru import logger
import time

router = APIRouter()

@router.post("/fact-check", response_model=FactCheckResponse)
async def fact_check_endpoint(request: FactCheckRequest):
    """
    Endpoint to fact-check a text chunk.
    """
    start_time = time.time()
    logger.info(f"Received fact-check request for text: '{request.text[:100]}...'")

    try:
        # Process the text through the verification pipeline
        results = await VerificationPipeline.process_text_chunk(
            text=request.text,
            video_title=request.videoTitle,
            context=request.context
        )

        # Convert to FactCheckResult models
        fact_check_results = [
            FactCheckResult(
                claim=result["claim"],
                verdict=result["verdict"],
                explanation=result["explanation"],
                source=result.get("source"),  # Use .get() for safety
                confidence=result.get("confidence")  # Include confidence if available
            )
            for result in results
        ]

        end_time = time.time()
        processing_time_ms = int((end_time - start_time) * 1000)

        response = FactCheckResponse(
            results=fact_check_results,
            processingTimeMs=processing_time_ms
        )

        logger.info(f"Returning fact-check response with {len(fact_check_results)} results in {processing_time_ms}ms.")
        return response

    except Exception as e:
        logger.error(f"Unexpected error in fact-check endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during fact-checking.")
