import asyncio
from loguru import logger
from app.config import config
from typing import List, Dict
from duckduckgo_search import DDGS

class SearchService:
    """Service for interacting with DuckDuckGo search."""

    @staticmethod
    def _search_sync(query: str, max_results: int) -> List[Dict[str, str]]:
        results = []
        try:
            with DDGS() as ddgs:
                ddgs_gen = ddgs.text(query, max_results=max_results)
                for r in ddgs_gen:
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "content": r.get("body", ""),
                    })
        except Exception as e:
            logger.error(f"Error during synchronous DDGS search: {e}")
        return results

    @staticmethod
    async def search(query: str) -> List[Dict[str, str]]:
        """
        Perform a search using DuckDuckGo and return a list of results.
        Each result is a dict with keys: 'title', 'url', 'content'.
        """
        try:
            logger.info(f"Executing web search for: '{query}'")
            max_results = getattr(config, 'TAVILY_MAX_RESULTS', 5)
            
            # Run the synchronous DDGS call in a background thread
            results = await asyncio.to_thread(SearchService._search_sync, query, max_results)
                    
            logger.debug(f"Search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Error during DuckDuckGo search: {e}")
            return []

    @staticmethod
    async def format_search_context(results: List[Dict[str, str]]) -> str:
        """
        Format a list of search results into a single string context for the LLM.
        """
        if not results:
            return "No search results found."

        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"Result {i}:\n"
                f"Title: {result['title']}\n"
                f"URL: {result['url']}\n"
                f"Content: {result['content']}\n"
            )

        return "\n---\n".join(context_parts)