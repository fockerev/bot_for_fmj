"""MCP (Model Context Protocol) Client for web-search integration."""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path


class MCPClient:
    """Client for communicating with MCP web-search server via stdio."""

    def __init__(self, mcp_command: str, mcp_args: List[str], logger: Optional[logging.Logger] = None):
        """
        Initialize MCP client.

        Args:
            mcp_command: Command to start MCP server (e.g., "node")
            mcp_args: Arguments for the command (e.g., ["/path/to/dist/index.js"])
            logger: Logger instance
        """
        self.mcp_command = mcp_command
        self.mcp_args = mcp_args
        self.logger = logger or logging.getLogger(__name__)
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0

    async def start(self) -> None:
        """Start the MCP server process and initialize the connection."""
        try:
            self.logger.info(f"Starting MCP server: {self.mcp_command} {' '.join(self.mcp_args)}")
            # Increase buffer limit for large JSON-RPC responses (default is 64KB, increase to 10MB)
            self.process = await asyncio.create_subprocess_exec(
                self.mcp_command,
                *self.mcp_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,  # 10MB buffer for large search results
            )
            self.logger.info("MCP server process started")

            # Wait a moment for the server to initialize
            await asyncio.sleep(0.5)

            # Send initialize request per MCP protocol
            try:
                init_result = await self._send_request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "discord-bot-mcp-client",
                            "version": "1.0.0"
                        }
                    }
                )
                self.logger.info(f"MCP server initialized: {init_result}")
            except Exception as e:
                self.logger.warning(f"MCP initialize handshake failed (may not be required): {e}")

        except Exception as e:
            self.logger.error(f"Failed to start MCP server: {e}")
            raise

    async def stop(self) -> None:
        """Stop the MCP server process."""
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
                self.logger.info("MCP server stopped")
            except Exception as e:
                self.logger.error(f"Error stopping MCP server: {e}")

    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a JSON-RPC request to the MCP server.

        Args:
            method: JSON-RPC method name
            params: Method parameters

        Returns:
            Response from the server
        """
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP server process not started")

        request_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            # Send request
            request_json = json.dumps(request) + "\n"
            self.logger.debug(f"Sending MCP request: {request_json.strip()}")
            self.process.stdin.write(request_json.encode())
            await self.process.stdin.drain()

            # Read response - skip non-JSON log lines
            response_text = None
            max_attempts = 1000  # Allow for many log lines from MCP server
            attempts = 0

            while not response_text and attempts < max_attempts:
                attempts += 1
                response_line = await asyncio.wait_for(
                    self.process.stdout.readline(),
                    timeout=60.0  # 60 second timeout for web search
                )

                if not response_line:
                    # Check stderr for error messages
                    stderr_output = ""
                    if self.process.stderr:
                        try:
                            stderr_data = await asyncio.wait_for(
                                self.process.stderr.read(1024),
                                timeout=0.1
                            )
                            stderr_output = stderr_data.decode() if stderr_data else ""
                        except asyncio.TimeoutError:
                            pass

                    error_msg = "MCP server closed connection"
                    if stderr_output:
                        error_msg += f". Stderr: {stderr_output}"
                    raise RuntimeError(error_msg)

                line_text = response_line.decode().strip()
                if not line_text:
                    continue

                # Skip log lines (lines that start with '[' but are not JSON-RPC)
                # Valid JSON-RPC responses start with '{'
                if line_text.startswith('{'):
                    response_text = line_text
                    self.logger.debug(f"Received MCP response: {response_text}")
                else:
                    # This is a log line, skip it
                    self.logger.debug(f"Skipping MCP log line: {line_text}")
                    continue

            if not response_text:
                raise RuntimeError("MCP server did not return valid JSON-RPC response")

            response = json.loads(response_text)

            if "error" in response:
                raise RuntimeError(f"MCP error: {response['error']}")

            return response.get("result", {})

        except asyncio.TimeoutError:
            self.logger.error("MCP request timed out")
            raise RuntimeError("MCP request timed out")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse MCP response: {e}")
            raise RuntimeError(f"Invalid MCP response: {e}")
        except Exception as e:
            self.logger.error(f"MCP request failed: {e}")
            raise

    async def full_web_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform a full web search with content extraction.

        Args:
            query: Search query string
            limit: Number of results to return (1-10, default 5)

        Returns:
            List of search results with full content
        """
        try:
            self.logger.info(f"Performing web search: {query} (limit: {limit})")
            result = await self._send_request(
                "tools/call",
                {
                    "name": "full-web-search",
                    "arguments": {
                        "query": query,
                        "limit": max(1, min(10, limit))
                    }
                }
            )

            # Parse the result
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    # Extract text from content blocks
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_content = item.get("text", "")
                            # Try to parse as JSON if it looks like structured data
                            try:
                                return json.loads(text_content)
                            except json.JSONDecodeError:
                                # Return as plain text wrapped in dict
                                return [{"content": text_content}]

            return []

        except Exception as e:
            self.logger.error(f"Web search failed: {e}")
            raise

    async def get_web_search_summaries(self, query: str, limit: int = 5) -> List[Dict[str, str]]:
        """
        Get web search summaries without full content extraction (faster).

        Args:
            query: Search query string
            limit: Number of results to return (1-10, default 5)

        Returns:
            List of search result summaries
        """
        try:
            self.logger.info(f"Getting search summaries: {query} (limit: {limit})")
            result = await self._send_request(
                "tools/call",
                {
                    "name": "get-web-search-summaries",
                    "arguments": {
                        "query": query,
                        "limit": max(1, min(10, limit))
                    }
                }
            )

            # Parse the result similar to full_web_search
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_content = item.get("text", "")
                            try:
                                return json.loads(text_content)
                            except json.JSONDecodeError:
                                return [{"content": text_content}]

            return []

        except Exception as e:
            self.logger.error(f"Search summaries failed: {e}")
            raise

    async def get_single_page_content(self, url: str) -> str:
        """
        Get content from a single web page.

        Args:
            url: URL to fetch

        Returns:
            Extracted page content
        """
        try:
            self.logger.info(f"Fetching page content: {url}")
            result = await self._send_request(
                "tools/call",
                {
                    "name": "get-single-web-page-content",
                    "arguments": {
                        "url": url
                    }
                }
            )

            # Parse the result
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            return item.get("text", "")

            return ""

        except Exception as e:
            self.logger.error(f"Failed to fetch page content: {e}")
            raise


class MCPClientManager:
    """Manager for MCP client lifecycle."""

    def __init__(self, mcp_command: str, mcp_args: List[str], logger: Optional[logging.Logger] = None):
        """
        Initialize MCP client manager.

        Args:
            mcp_command: Command to start MCP server
            mcp_args: Arguments for the command
            logger: Logger instance
        """
        self.client = MCPClient(mcp_command, mcp_args, logger)
        self.logger = logger or logging.getLogger(__name__)
        self._started = False

    async def __aenter__(self):
        """Context manager entry."""
        await self.start()
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.stop()

    async def start(self) -> None:
        """Start the MCP client."""
        if not self._started:
            await self.client.start()
            self._started = True

    async def stop(self) -> None:
        """Stop the MCP client."""
        if self._started:
            await self.client.stop()
            self._started = False
