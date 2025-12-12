from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import uvicorn
import json
import asyncio
import logging
import httpx
from uuid import uuid4
from typing import Dict, Any, AsyncGenerator
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendStreamingMessageRequest

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CVEAgentClient:
    def __init__(self, base_url: str = "http://localhost:9991"):
        self.base_url = base_url
        self.httpx_client = None
        self.a2a_client = None
        self.agent_card = None
    
    async def initialize(self):
        """初始化客户端"""
        self.httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        
        resolver = A2ACardResolver(
            httpx_client=self.httpx_client,
            base_url=self.base_url,
        )
        
        try:
            self.agent_card = await resolver.get_agent_card()
            logger.info('成功获取 Agent Card')
            
            self.a2a_client = A2AClient(
                httpx_client=self.httpx_client,
                agent_card=self.agent_card
            )
            logger.info('A2A 客户端初始化成功')
            
        except Exception as e:
            logger.error(f'初始化失败: {e}')
            if self.httpx_client:
                await self.httpx_client.aclose()
            raise
    
    async def close(self):
        """关闭客户端"""
        if self.httpx_client:
            await self.httpx_client.aclose()
            logger.info('HTTP 客户端已关闭')
    
    async def stream_cve_analysis(self, request_data: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """流式分析 CVE"""
        if not self.a2a_client:
            await self.initialize()
        
        try:
            # 构建消息
            message_text_dict = {
                "action": request_data.get("action", "branches-analysis"),
                "cve_id": request_data["cve_id"]
            }
            
            # 添加可选参数
            optional_params = ["branches", "signer_name", "signer_email"]
            for param in optional_params:
                if param in request_data and request_data[param]:
                    message_text_dict[param] = request_data[param]
            
            logger.info(f"分析参数: {message_text_dict}")
            
            send_message_payload = {
                'message': {
                    'role': 'user',
                    'parts': [
                        {'kind': 'text', 'text': json.dumps(message_text_dict)}
                    ],
                    'messageId': uuid4().hex,
                },
            }
            
            streaming_request = SendStreamingMessageRequest(
                id=str(uuid4()),
                params=MessageSendParams(**send_message_payload)
            )
            
            # 流式返回结果
            async for chunk in self.a2a_client.send_message_streaming(streaming_request):
                chunk_dict = chunk.model_dump(mode='json', exclude_none=True)
                
                # 格式化输出
                output = {
                    "timestamp": chunk_dict.get("timestamp"),
                    "type": chunk_dict.get("type"),
                    "data": chunk_dict.get("result", {})
                }
                
                yield f"{json.dumps(output, ensure_ascii=False)}\n"
                
        except Exception as e:
            error_output = {
                "error": str(e),
                "type": "error"
            }
            yield f"{json.dumps(error_output)}\n"

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 2.0+ 生命周期管理"""
    # 启动时
    app.state.client = CVEAgentClient()
    try:
        await app.state.client.initialize()
        logger.info("CVE Agent Client 启动完成")
        yield
    finally:
        # 关闭时
        await app.state.client.close()
        logger.info("CVE Agent Client 已关闭")

# 创建 FastAPI 应用
app = FastAPI(
    title="CVE Agent Client API",
    description="CVE 分析客户端 API 接口",
    version="1.0.0",
    lifespan=lifespan  # 使用新的生命周期管理
)

@app.post("/api/cve/analyze")
async def analyze_cve(request_data: Dict[str, Any]):
    """CVE 分析接口
    
    Args:
        request_data: 包含以下字段的字典
            - cve_id: 必需，CVE 编号
            - action: 可选，操作类型，默认 branches-analysis
            - branches: 可选，分支列表
            - signer_name: 可选，签名人姓名
            - signer_email: 可选，签名人邮箱
    """
    try:
        # 验证必需参数
        if not request_data.get("cve_id"):
            raise HTTPException(status_code=400, detail="cve_id 参数必需")
        
        # 从应用状态获取客户端
        client = app.state.client
        
        # 创建流式响应
        return StreamingResponse(
            client.stream_cve_analysis(request_data),
            media_type="application/x-ndjson",  # 换行分隔的 JSON
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # 禁用代理缓冲
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分析请求失败: {e}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy", 
        "service": "CVE Agent Client",
        "timestamp": asyncio.get_event_loop().time()
    }

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "CVE Agent Client API",
        "endpoints": {
            "健康检查": "/health",
            "CVE 分析": "POST /api/cve/analyze"
        }
    }

if __name__ == "__main__":
    # 修复 uvicorn 启动警告
    uvicorn.run(
        "app_client_fast:app",
        host="0.0.0.0", 
        port=8000, 
        reload=False,  
        log_level="info"
    )