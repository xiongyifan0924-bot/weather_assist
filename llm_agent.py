from openai import OpenAI
import json
import datetime
from weather_api import fetch_weather_for_city

# ==========================================
# 1. 基础配置
# ==========================================
API_KEY = "sk-5b527f3b414c43eba6cbbb0ac272ffcb"  # 确保账号内有充足的 Token 余额
BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ==========================================
# 2. Function Calling 接口定义 (骨骼)
# ==========================================
# 这就是最正宗的 Function Calling Schema！
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市未来气象数据。只要用户提到地点和时间（哪怕是相对时间），必须立即调用此工具获取客观数据！",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "标准的城市名称，如'广州'、'北京'"
                    },
                    "inferred_date": {
                        "type": "string",
                        "description": "利用系统时间自行推算出的具体日期范围，例如'3月14日-15日'。必须由模型自行推算填入，禁止向用户提问确认！"
                    }
                },
                # 强校验：逼迫模型输出 JSON 时必须带上推算好的时间，阻断其聊天的欲望
                "required": ["city", "inferred_date"] 
            }
        }
    }
]

# ==========================================
# 3. 动态 Prompt 与业务风控 (大脑)
# ==========================================
def get_dynamic_system_prompt():
    """动态注入真实时间，消除大模型的时间盲区"""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""【系统物理时间与最高指令】
当前系统真实时间是：{date_str}。
请严格依靠此锚点进行日历推算。例如，今天之后的周六日即为“本周末”。

# 核心红线规则（违反将导致系统崩溃）
当用户使用“这周末、下周末”等相对时间时，你已具备足够的信息！
你必须立刻、马上将推算出的日期填入 `get_weather` 插件的 `inferred_date` 参数中并触发插件！
**禁止说“我需要确认一下具体时间”！**
**直接调用工具！直接调用工具！直接调用工具！**

# Role
你是一位拥有资深气象学知识与丰富生活经验的“智能场景化出行决策助理”。
获取真实天气数据后，结合用户行为意图（如户外/室内），输出包含「☁️ 气象简报」、「🎯 决策结论」、「💡 出行贴士」的专业 Markdown 报告。
"""

# ==========================================
# 4. Agent 核心调度编排 (中枢神经)
# ==========================================
def chat_with_agent(messages_history):
    dynamic_system_prompt = get_dynamic_system_prompt()
    
    # 注入系统架构设定
    if not messages_history or messages_history[0].get("role") != "system":
        messages_history.insert(0, {"role": "system", "content": dynamic_system_prompt})
    else:
        messages_history[0]["content"] = dynamic_system_prompt

    # 【第一次交互】：发送 Prompt 和 Tools，等待模型决策
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
            tools=tools,         # <--- 明确向模型宣告 Function Calling 能力
            tool_choice="auto"   # <--- 让模型自行决定是否调用工具
        )
    except Exception as e:
        return f"🚨 API 请求失败，请检查网络或 Key 余额。错误: {e}"
    
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    # 【处理 Function Calling 结果】
    if tool_calls:
        # 1. 记录模型发出的“函数调用”请求
        messages_history.append(response_message) 
        
        # 2. 遍历执行每一个函数（本例中主要是 get_weather）
        for tool_call in tool_calls:
            if tool_call.function.name == "get_weather":
                # 解析模型生成的 JSON 参数
                function_args = json.loads(tool_call.function.arguments)
                city = function_args.get("city")
                # inferred_date 被大模型算出并传进来了，但查询天气其实只需要城市即可
                
                # 3. 运行本地 Python 函数去向第三方拿数据
                weather_result = fetch_weather_for_city(city)
                
                # 4. 将第三方拿到的真实天气数据，按 Function Calling 规范塞回给大模型
                messages_history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "get_weather",
                    "content": weather_result,
                })
        
        # 【第二次交互】：模型拿着最新的天气数据，进行最终推理并输出人类语言
        second_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
        )
        return second_response.choices[0].message.content
        
    else:
        # 未触发 Function Calling，通常是因为闲聊或信息极度不足
        return response_message.content