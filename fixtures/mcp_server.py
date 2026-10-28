"""The good fixture agent as an MCP stdio server: `python -m fixtures.mcp_server`."""

from mcp.server.mcpserver import MCPServer

from fixtures.agents import good_agent

server = MCPServer("orderbot")


@server.tool()
def chat(messages: list[dict]) -> str:
    """Reply to a conversation."""
    return good_agent(messages)


if __name__ == "__main__":
    server.run()
