from mcp.server.mcpserver import MCPServer

mcp = MCPServer("My First MCP Server")


# @mcp.tool()
# def add(a: int, b: int) -> int:
#     """Add two numbers."""
#     return a + b + 100


@mcp.tool()
def create_post(text: str) -> str:
    """Create a social media post."""
    return f"Post received: {text}"


if __name__ == "__main__":
    mcp.run()
    
# V8uxUP4GB8jYEh4T10IuwVRDY
# JUneFiW8nn46SqtDfwu9V0PXwYiF9tco9teuSIx4x4l6E9eXIn
# AAAAAAAAAAAAAAAAAAAAAEQR%2FgEAAAAAOiRIAlHwxPHvmlZDw882hFbi24Q%3DqFh9tHVp0EgWpscI0QzIAlnyIKqdGs2Y0GbV3CfC3Xq2xpcAob

# cl
# NXZIWGsyaThVWHRlaUhKQ0dyTy06MTpjaQ
# W3XpXUXMCfGRkTkzmao6FbJGx-y7WYIjOUfcC7C3Ic7yBtZ1vs