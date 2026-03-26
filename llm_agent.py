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
# 2. Tools 配置 (终极融合版：多城市 Array + 景点强转化)
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
                        "description": "【极其重要】必须是标准的中国地级市行政区划名称列表！支持同时传入多个城市。如果用户输入著名景点（如'玉龙雪山'、'泰山'、'迪士尼'）或简称（如'魔都'），你必须先运用你的世界知识，将其转化为该景点所在的【标准地级市名称】（如'丽江'、'泰安'、'上海'）后再放入列表查询。"
                    }
                },
                "required": ["cities"]
            }
        }
    }
]

# ==========================================
# 3. 铁腕级系统提示词
# ==========================================
def get_dynamic_system_prompt():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""当前系统真实时间：{date_str}。
你是一个专业的出行天气决策助理。

【核心工作流与铁律】
1. 地点绝对忠实：在不违背【工具参数规范】的前提下，忠实于用户的目的地规划。
2. 相对时间推算：直接利用系统时间推算。
3. 🛡️【能力边界与微气候免责】：你获取的天气数据精度仅为【市级大盘数据】。如果用户询问高海拔山区、海岛等特殊微气候场景的精细天气，你必须在回答中明确警示：“⚠️ 当前气象为市区宏观预报，山区/海岛微气候复杂多变，能否登顶/开展活动请务必参考景区官方实时通报。”
4. 【防格式崩溃】：调用工具时绝对禁止输出 `<|DSML|>` 等底层控制标签！必须严格使用标准的 JSON 格式！

【输出规范】
☁️ 【气象简报】（若查询多个城市，请分城市清晰列出）
🎯 【决策结论】
💡 【出行贴士】
"""

# ==========================================
# 4. 稳定的 ReAct 循环流
# ==========================================
def chat_with_agent(messages_history):
    dynamic_system_prompt = get_dynamic_system_prompt()
    
    if not messages_history or messages_history[0].get("role") != "system":
        messages_history.insert(0, {"role": "system", "content": dynamic_system_prompt})
    else:
        messages_history[0]["content"] = dynamic_system_prompt

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
        # 状况 A：工具调用
        # ------------------------------------------
        if response_message.tool_calls:
            messages_history.append(response_message)
            
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "get_weather":
                    function_args = json.loads(tool_call.function.arguments)
                    cities = function_args.get("cities", [])
                    
                    if isinstance(cities, str):
                        cities = [cities]
                    
                    all_weather_results = []
                    for city in cities:
                        weather_result = fetch_weather_for_city(city)
                        all_weather_results.append(f"【{city}】: {weather_result}")
                    
                    messages_history.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "get_weather",
                        "content": "\n".join(all_weather_results),
                    })
                    
            continue
            
        # ------------------------------------------
        # 状况 B：生成最终回复
        # ------------------------------------------
        content = response_message.content or ""
        
        if "DSML" in content:
            content = re.sub(r'<\s*\|\s*DSML\s*\|[^>]*>', '', content)
            return content + "\n\n(🧠 系统提示：尝试深入查询时遇到地名解析波动，已为您展示部分结果)"
            
        return content

    # ------------------------------------------
    # 状况 C：触发最大循环兜底防线
    # ------------------------------------------
    return "🧠 抱歉，该行程涉及的地点验证过于复杂，超出了我的单次思考上限，请尝试直接输入精确的市级名称（如'丽江市'）。"
