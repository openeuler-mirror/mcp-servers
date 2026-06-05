#!/usr/bin/env python3
"""
API连接测试脚本
用于验证LLM API服务是否正常运行
"""

import logging
import requests
import json
from src.config import LLM_API_URL

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('api_test.log')
    ]
)

def test_api_connection():
    """测试API连接"""
    logging.info("🚀 开始测试API连接...")
    logging.info(f"🌐 API地址: {LLM_API_URL}")
    
    # 简单的测试请求
    test_prompt = "Hello, please respond with 'API is working'"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    data = {
        "mode": "instruct",
        "prompt": test_prompt,
        "max_tokens": 50,
        "temperature": 0.1,
        "top_p": 0.5,
        "seed": 10,
        "do_sample": True,
    }
    
    try:
        logging.info("📤 发送测试请求...")
        logging.debug(f"请求数据: {json.dumps(data, indent=2)}")
        
        response = requests.post(
            LLM_API_URL, 
            headers=headers, 
            json=data, 
            verify=False, 
            timeout=30
        )
        
        logging.info(f"📡 响应状态码: {response.status_code}")
        logging.debug(f"📡 响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                result_data = response.json()
                logging.info("✅ API连接成功！")
                logging.debug(f"📥 完整响应: {json.dumps(result_data, indent=2, ensure_ascii=False)}")
                
                if 'choices' in result_data and len(result_data['choices']) > 0:
                    result_text = result_data['choices'][0]['text']
                    logging.info(f"🤖 模型响应: {result_text}")
                    return True
                else:
                    logging.error("❌ 响应格式异常，缺少choices字段")
                    return False
                    
            except json.JSONDecodeError as e:
                logging.error(f"❌ JSON解析失败: {e}")
                logging.error(f"原始响应: {response.text}")
                return False
        else:
            logging.error(f"❌ API请求失败: {response.status_code}")
            logging.error(f"错误信息: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        logging.error("🔌 连接错误！请检查API服务是否启动")
        logging.error("💡 提示: 请确保API服务在 http://127.0.0.1:5000 上运行")
        return False
    except requests.exceptions.Timeout:
        logging.error("⏰ 请求超时！API服务响应太慢")
        return False
    except Exception as e:
        logging.error(f"💥 未知错误: {e}")
        return False

def test_code_fix_functionality():
    """测试代码修复功能"""
    logging.info("🔧 开始测试代码修复功能...")
    
    # 导入修复函数
    try:
        from src.llm import codellama_fix
        from src.common import Language
        
        # 测试数据
        test_patch = """
        - if (ptr == NULL) {
        -     return -1;
        - }
        + if (ptr == NULL) {
        +     return -1;
        + }
        """
        
        test_vulcode = """
        int vulnerable_function(char* ptr) {
            if (ptr == NULL) {
                return -1;
            }
            return 0;
        }
        """
        
        logging.info("📝 测试补丁:")
        logging.debug(test_patch)
        logging.info("📝 测试代码:")
        logging.debug(test_vulcode)
        
        result = codellama_fix(test_patch, test_vulcode, Language.C)
        
        if result:
            logging.info("✅ 代码修复功能正常！")
            logging.info(f"🔧 修复结果: {result[:200]}...")
            return True
        else:
            logging.error("❌ 代码修复功能失败")
            return False
            
    except ImportError as e:
        logging.error(f"❌ 导入模块失败: {e}")
        return False
    except Exception as e:
        logging.error(f"💥 测试代码修复功能时出错: {e}")
        return False

def main():
    """主函数"""
    logging.info("=" * 60)
    logging.info("🧪 LLM API 连接测试")
    logging.info("=" * 60)
    
    # 测试1: API连接
    api_ok = test_api_connection()
    
    if api_ok:
        logging.info("=" * 60)
        # 测试2: 代码修复功能
        fix_ok = test_code_fix_functionality()
        
        if fix_ok:
            logging.info("🎉 所有测试通过！API服务运行正常")
        else:
            logging.error("❌ 代码修复功能测试失败")
    else:
        logging.error("❌ API连接测试失败")
        logging.error("💡 请检查以下事项:")
        logging.error("   1. API服务是否在 http://127.0.0.1:5000 上运行")
        logging.error("   2. 服务是否正常启动")
        logging.error("   3. 防火墙是否阻止了连接")
    
    logging.info("=" * 60)

if __name__ == "__main__":
    main()
