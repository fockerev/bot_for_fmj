"""Web Search Plugin for Semantic Kernel using MCP"""
import logging
from typing import Annotated

from semantic_kernel.functions import kernel_function


class WebSearchPlugin:
    """Plugin for web search functionality using MCP client"""

    def __init__(self, mcp_client, search_result_limit: int = 5):
        """
        Initialize web search plugin

        Args:
            mcp_client: MCP client instance for web search
            search_result_limit: Maximum number of search results to return
        """
        self.mcp_client = mcp_client
        self.search_result_limit = search_result_limit
        self.logger = logging.getLogger("web_search_plugin")

    @kernel_function(
        name="web_search",
        description="Searches the web for information using a search query and returns relevant results. Use this when you need current information or facts from the internet."
    )
    async def search(
        self,
        query: Annotated[str, "The search query to find information on the web"]
    ) -> Annotated[str, "Search results from the web"]:
        """
        Search the web using MCP client

        Args:
            query: Search query string

        Returns:
            Formatted search results as a string
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info("🔍 [PLUGIN CALLED] WebSearchPlugin.search()")
            self.logger.info(f"📝 Query: {query}")
            self.logger.info("=" * 80)

            # Start MCP client
            self.logger.info("🔌 Starting MCP client...")
            await self.mcp_client.start()
            self.logger.info("✅ MCP client started")

            # Perform web search
            self.logger.info(f"🌐 Performing web search (limit: {self.search_result_limit})...")
            search_results = await self.mcp_client.full_web_search(
                query,
                limit=self.search_result_limit
            )
            self.logger.info(f"✅ Search completed: {len(search_results)} results found")

            # Format results
            self.logger.info("📄 Formatting search results...")
            formatted_results = self._format_search_results(search_results)
            self.logger.info(f"✅ Results formatted ({len(formatted_results)} characters)")

            self.logger.info("=" * 80)
            self.logger.info("✨ [PLUGIN COMPLETED] WebSearchPlugin.search()")
            self.logger.info("=" * 80)

            return formatted_results

        except Exception as e:
            self.logger.error("=" * 80)
            self.logger.error(f"❌ [PLUGIN ERROR] WebSearchPlugin.search() failed: {e}")
            self.logger.error("=" * 80)
            return f"検索エラーが発生しました: {str(e)}"

        finally:
            # Stop MCP client
            if self.mcp_client:
                self.logger.info("🔌 Stopping MCP client...")
                await self.mcp_client.stop()
                self.logger.info("✅ MCP client stopped")

    def _format_search_results(self, results: list) -> str:
        """
        Format search results into a readable string

        Args:
            results: List of search result dictionaries

        Returns:
            Formatted search results string
        """
        if not results:
            return "検索結果が見つかりませんでした。"

        formatted = "以下は検索結果です:\n\n"
        for i, result in enumerate(results, 1):
            if isinstance(result, dict):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", result.get("snippet", ""))

                formatted += f"{i}. {title}\n"
                if url:
                    formatted += f"   URL: {url}\n"
                formatted += f"   {content[:500]}...\n\n"
            else:
                formatted += f"{i}. {str(result)[:500]}...\n\n"

        return formatted
