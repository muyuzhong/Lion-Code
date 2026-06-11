"""跨测试文件共享的最小工具与可注入假时钟。"""
from core.tool import Tool, ToolResult


class EchoTool(Tool):
    timeout_seconds = 5
    def name(self): return "echo"
    def description(self): return "回显输入文本"
    def input_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    async def call(self, params):
        return ToolResult(True, f"echo:{params['text']}", 0.0)


class DangerTool(EchoTool):
    requires_approval = True
    def name(self): return "danger"


class FakeSleep:
    def __init__(self): self.calls = []
    async def __call__(self, delay): self.calls.append(delay)


async def collect(aiter):
    return [event async for event in aiter]
