from openai import OpenAI
import json
import datetime
import re
import streamlit as st
from weather_api import fetch_weather_for_city

# ==========================================
# 1. 基础配置初始化
# ==========================================
API_KEY = st.secrets["DEEPSEEK_API_KEY"]
BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ==========================================
# 2. Tools 配置 (升维：支持多城市 Array 架构)
# ==========================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取城市天气。当用户提到地点和出行计划时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cities": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "【极其重要】需要查询天气的城市列表，支持同时传入多个城市。必须是标准的中国地级市行政区划名称！如果查不到，请尝试加上'市'字重试（如'丽江市'）。"
                    }
                },
                "required": ["cities"]
            }
        }
    }
]

# ==========================================
# 3. 铁腕级系统提示词 (注入物理时间与安全红线)
# ==========================================
def get_dynamic_system_prompt():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""当前系统真实时间：{date_str}。
你是一个专业的出行天气决策助理。

【核心工作流与铁律】
1. 地点绝对忠实：当用户提供具体城市时，必须完全忠实于该城市！
2. 相对时间推算：直接利用系统时间推算。
3. 🛡️【能力边界与微气候免责】：你获取的天气数据精度仅为【市级大盘数据】。如果用户询问高海拔山区、海岛等特殊微气候场景的精细天气，你必须在回答中明确警示：“⚠️ 当前气象为市区宏观预报，山区/海岛微气候复杂多变，能否登顶/开展活动请务必参考景区官方实时通报。”
4. 【防格式崩溃】：调用工具时绝对禁止输出 `<|DSML|>` 等底层控制标签！必须严格使用标准的 JSON 格式！

【输出规范】
☁️ 【气象简报】（若查询多个城市，请分城市清晰列出）
🎯 【决策结论】
💡 【出行贴士】
"""

# ==========================================
# 4. 🌟 终极架构：带有安全界限的 ReAct 循环流
# ==========================================
def chat_with_agent(messages_history):
    dynamic_system_prompt = get_dynamic_system_prompt()
    
    # 确保系统提示词始终在最前面且是最新的
    if not messages_history or messages_history[0].get("role") != "system":
        messages_history.insert(0, {"role": "system", "content": dynamic_system_prompt})
    else:
        messages_history[0]["content"] = dynamic_system_prompt

    # 设置最大重试次数，防止大模型陷入无限死循环卡死服务器
    max_loops = 3  
    
    for turn in range(max_loops):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages_history,
                tools=tools,
                tool_choice="auto",
                temperature=0.1
            )
        except Exception as e:
            return f"🚨 API 请求失败: {e}"
        
        response_message = response.choices[0].message
        
        # ------------------------------------------
        # 状况 A：大模型正常发起工具调用 (包括纠错时的二次调用)
        # ------------------------------------------
        if response_message.tool_calls:
            # 将大模型的调用意图存入上下文记忆
            messages_history.append(response_message)
            
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "get_weather":
                    function_args = json.loads(tool_call.function.arguments)
                    cities = function_args.get("cities", [])
                    
                    # 容错兜底：如果模型调皮只传了一个字符串，强制转为列表
                    if isinstance(cities, str):
                        cities = [cities]
                    
                    # 遍历查询所有城市
                    all_weather_results = []
                    for city in cities:
                        weather_result = fetch_weather_for_city(city)
                        all_weather_results.append(f"【{city}】: {weather_result}")
                    
                    # 将合并后的数据回传给大模型
                    messages_history.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "get_weather",
                        "content": "\n".join(all_weather_results),
                    })
                    
            # ‼️ 极其关键：查完天气后，使用 continue 进入下一轮循环，让大模型自行阅读数据并生成自然语言
            continue
            
        # ------------------------------------------
        # 状况 B：大模型认为资料收集完毕，输出最终文本
        # ------------------------------------------
        content = response_message.content or ""
        
        # 终极物理防线：不管大模型怎么发癫，只要文本里混进了底层标签，直接正则切除
        if "DSML" in content:
            content = re.sub(r'<\s*\|\s*DSML\s*\|[^>]*>', '', content)
            return content + "\n\n(🧠 系统提示：尝试深入查询时遇到地名解析波动，已为您展示部分结果)"
            
        return content

    # ------------------------------------------
    # 状况 C：兜底防线 - 如果循环了 3 次还在纠结，强行切断保护系统
    # ------------------------------------------
    return "🧠 抱歉，该行程涉及的地点验证过于复杂，超出了我的单次思考上限，请尝试直接输入精确的市级名称（如'丽江市'）。"
