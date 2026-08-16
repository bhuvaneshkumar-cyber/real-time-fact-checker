from loguru import logger
from app.services.llm_service import LLMService
from app.services.search_service import SearchService
from app.config import config
from typing import List, Dict
import asyncio
import time

class VerificationPipeline:
    """Orchestrates the fact-checking pipeline: extract claims, [optionally search], classify/verdict."""

    @staticmethod
    async def process_text_chunk(text: str, video_title: str = None, context: str = None) -> List[Dict]:
        """
        Process a text chunk through the fact-checking pipeline.
        Returns a list of fact-checked claim results.
        """
        start_time = time.time()
        logger.info(f"Processing text chunk: '{text[:100]}...'")

        # Step 1: Extract claims
        claims = await LLMService.extract_claims(text, video_title, context)
        if not claims:
            logger.info("No claims extracted from text chunk.")
            return []

        logger.info(f"Extracted {len(claims)} claims: {claims}")

        # Step 2 & 3: For each claim, either search+synthesize or classify directly
        tasks = []
        for claim in claims:
            task = VerificationPipeline._process_single_claim(claim)
            tasks.append(task)

        # Run all claim processing concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results, handling any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error processing claim '{claims[i]}': {result}")
                # Provide a fallback result
                processed_results.append({
                    "claim": claims[i],
                    "verdict": "ERROR",
                    "explanation": "Error during processing.",
                    "source": None,
                    "confidence": "LOW"
                })
            else:
                processed_results.append(result)

        end_time = time.time()
        processing_time_ms = int((end_time - start_time) * 1000)
        logger.info(f"Finished processing text chunk in {processing_time_ms}ms. Results: {processed_results}")

        return processed_results

    @staticmethod
    async def _process_single_claim(claim: str) -> Dict:
        """
        Process a single claim: either search for it and synthesize verdict, 
        or classify it directly using LLM knowledge.
        """
        try:
            if config.USE_SEARCH:
                # Original flow: search then synthesize verdict
                return await VerificationPipeline._process_with_search(claim)
            else:
                # New flow: classify directly using LLM knowledge
                return await VerificationPipeline._process_without_search(claim)

        except Exception as e:
            logger.error(f"Error in _process_single_claim for claim '{claim}': {e}")
            return {
                "claim": claim,
                "verdict": "ERROR",
                "explanation": "Error during claim processing.",
                "source": None,
                "confidence": "LOW"
            }

    @staticmethod
    async def _process_with_search(claim: str) -> Dict:
        """Original flow: search for evidence then synthesize verdict."""
        try:
            # Step 2: Search for the claim
            search_results = await SearchService.search(claim)
            search_context = await SearchService.format_search_context(search_results)

            # Step 3: Synthesize verdict
            verdict_dict = await LLMService.synthesize_verdict(claim, search_context)

            # Find the best source URL from search results (if any)
            source_url = verdict_dict.get("source")
            if source_url is None and search_results:
                # Use the first result's URL as a fallback source
                source_url = search_results[0].get("url")

            return {
                "claim": claim,
                "verdict": verdict_dict["verdict"],
                "explanation": verdict_dict["explanation"],
                "source": source_url,
                "confidence": "MEDIUM"  # Default confidence for search-based approach
            }

        except Exception as e:
            logger.error(f"Error in _process_with_search for claim '{claim}': {e}")
            return {
                "claim": claim,
                "verdict": "ERROR",
                "explanation": "Error during search-based processing.",
                "source": None,
                "confidence": "LOW"
            }

    @staticmethod
    async def _process_without_search(claim: str) -> Dict:
        """New flow: classify claim directly using LLM knowledge."""
        try:
            # Classify the claim directly
            classification_result = await LLMService.classify_claim_directly(claim)

            return {
                "claim": claim,
                "verdict": classification_result["verdict"],
                "explanation": classification_result["explanation"],
                "source": None,  # No source when using direct classification
                "confidence": classification_result.get("confidence", "MEDIUM")
            }

        except Exception as e:
            logger.error(f"Error in _process_without_search for claim '{claim}': {e}")
            return {
                "claim": claim,
                "verdict": "ERROR",
                "explanation": "Error during direct classification.",
                "source": None,
                "confidence": "LOW"
            }
