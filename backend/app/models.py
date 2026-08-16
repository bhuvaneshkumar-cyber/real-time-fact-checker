from pydantic import BaseModel, Field
from typing import List, Optional

class FactCheckRequest(BaseModel):
    """Request model for fact-checking a text chunk."""
    text: str = Field(..., description="The text chunk to fact-check.")
    videoId: Optional[str] = Field(None, description="Optional YouTube video ID for context.")
    videoTitle: Optional[str] = Field(None, description="Optional YouTube video title for context.")
    context: Optional[str] = Field(None, description="Optional preceding conversation context (e.g. past captions) to help resolve pronouns.")

class FactCheckResult(BaseModel):
    """Result model for a single fact-checked claim."""
    claim: str = Field(..., description="The extracted claim that was fact-checked.")
    verdict: str = Field(..., description="The verdict: TRUE, FALSE, VAGUE, UNRELATED, DISTRACTING, or ERROR.")
    explanation: str = Field(..., description="A one-sentence explanation of the verdict.")
    source: Optional[str] = Field(None, description="URL to the source that supports the verdict (if applicable).")
    confidence: Optional[str] = Field(None, description="Confidence level: HIGH, MEDIUM, or LOW.")

class FactCheckResponse(BaseModel):
    """Response model for the fact-check endpoint."""
    results: List[FactCheckResult] = Field(..., description="List of fact-checked claims.")
    processingTimeMs: int = Field(..., description="Total processing time in milliseconds.")
