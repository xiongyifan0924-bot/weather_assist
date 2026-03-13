from openai import OpenAI
import json
import datetime
import streamlit as st
from weather_api import fetch_weather_for_city

# 1. 基础配置
API_KEY = st.secrets["DEEPSEEK_API_KEY"]
BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 2. 极简版 Tools (去掉了干扰它的推算参数，回归最纯粹的城市查询)
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气。当用户提到地点和出行计划时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "标准城市名，如'广州'、'宜春'"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

# 3. 温和但坚定的系统提示词
def get_dynamic_system_prompt():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""当前系统真实时间：{date_str}。
你是一个专业的出行天气决策助理。

【核心工作流与铁律】
1. 地点绝对忠实：当用户提供具体城市（如“宜春市”、“大理市”）时，你调用的 city 参数**必须完全忠实于该城市**！绝对、绝对禁止擅自将其替换为省会（如“南昌”、“昆明”）！
2. 静默调用：遇到时间+地点，直接在后台通过 Function Calling 调用 `get_weather`，不需要输出任何思考过程。
3. 对于“明天”、“周末”等相对时间，直接利用系统时间在心中推算，默认要素已齐，绝不要反问！

【输出规范】
获取到天气数据后，结合用户的活动（如：看油菜花需要晴朗无风），输出以下 Markdown 结构：
☁️ 【气象简报】
🎯 【决策结论】
💡 【出行贴士】
"""

# 4. 核心调度逻辑
def chat_with_agent(messages_history):
    dynamic_system_prompt = get_dynamic_system_prompt()
    
    if not messages_history or messages_history[0].get("role") != "system":
        messages_history.insert(0, {"role": "system", "content": dynamic_system_prompt})
    else:
        messages_history[0]["content"] = dynamic_system_prompt

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
            tools=tools,
            tool_choice="auto",
            temperature=0.1  # <--- 【新增这一行！】极度降低温度，强制模型变成无情的机器，禁止它自作聪明
        )
    except Exception as e:
        return f"🚨 API 请求失败: {e}"
    
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    # 【拦截底层代码泄漏】如果大模型依然犯病输出 DSML，我们直接拦截并提醒
    if response_message.content and "DSML" in response_message.content:
        return "🧠 哎呀，我的大脑刚才处理这串复杂的日期时稍微短路了一下，能麻烦您换种说法再问一次吗？比如直接告诉我几月几号。"

    # 正常的 Function Calling 处理流程
    if tool_calls:
        messages_history.append(response_message)
        
        for tool_call in tool_calls:
            if tool_call.function.name == "get_weather":
                function_args = json.loads(tool_call.function.arguments)
                city = function_args.get("city", "")
                
                weather_result = fetch_weather_for_city(city)
                
                # ... 前面解析 city 和调用 fetch_weather_for_city 的代码保持不变 ...
                
                messages_history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "get_weather",
                    "content": weather_result,
                })
        
        # 恢复成一次性生成并返回完整结果
        second_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
            temperature=0.1  # 依然保留低温度，防止发散和幻觉
        )
        return second_response.choices[0].message.content
        
    else:
        # 如果没有触发工具，也直接返回完整文本
        return response_message.content



