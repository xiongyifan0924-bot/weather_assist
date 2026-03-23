from openai import OpenAI
import json
import datetime
import re
import streamlit as st
from weather_api import fetch_weather_for_city

# 1. 基础配置
API_KEY = st.secrets["DEEPSEEK_API_KEY"]
BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 2. 极简版 Tools
# 2. 极简版 Tools (加入强大的前置意图/景点转化逻辑)
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
                        # 👇 就是这里！把大模型变成一个超级地理翻译官
                        "description": "【极其重要】必须是标准的中国地级市行政区划名称！如果用户输入的是著名景点（如'泰山'、'迪士尼'）、简称（如'魔都'）或非标准名称，你必须先运用你的世界知识，将其转化为该景点所在的【标准地级市名称】（例如：输入'泰山'必须转化为'泰安'，输入'迪士尼'必须转化为'上海'），然后再输出本参数！"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

# 3. 温和但坚定（且极度严厉）的系统提示词
def get_dynamic_system_prompt():
    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日，%A")
    
    return f"""当前系统真实时间：{date_str}。
你是一个专业的出行天气决策助理。

【核心工作流与铁律】
1. 地点绝对忠实：当用户提供具体城市时，调用的 city 参数必须完全忠实于该城市！绝对禁止擅自替换为省会！
2. 静默调用：遇到时间+地点，直接在后台通过 Function Calling 调用 `get_weather`。
3. 相对时间推算：对于“明天”、“周末”等相对时间，直接利用系统时间推算，默认要素已齐，绝不要反问！
4. 【极其重要】：当你需要调用天气工具时，绝对禁止在回复中输出任何 `<|DSML|>`、`<tool_call>` 等内部控制流标签！必须严格使用标准的 JSON 结构调用工具！

【输出规范】
获取到天气数据后，结合用户的活动，输出以下 Markdown 结构：
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
            temperature=0.1
        )
    except Exception as e:
        return f"🚨 API 请求失败: {e}"
    
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    # ==========================================
    # 🛡️ Agent 自愈核心逻辑：处理 DeepSeek 的 DSML 泄漏
    # ==========================================
    if not tool_calls and response_message.content and "DSML" in response_message.content:
        # 用正则从乱码中强行挖出城市名
        match = re.search(r'name="city" string="true">(.*?)</', response_message.content)
        if match:
            city = match.group(1) # 拿到 "泰山"
            weather_result = fetch_weather_for_city(city)
            
            # 强行组装上下文，假装大模型正常发起了提问，并强行把天气塞给它
            messages_history.append({"role": "assistant", "content": f"（系统静默解析意图：查询{city}天气）"})
            messages_history.append({
                "role": "user", 
                "content": f"【系统后门传入数据】：{city}的天气数据如下：{weather_result}。请立刻基于此数据，输出最终的出行决策简报！"
            })
            
            # 发起二次调用（自愈循环）
            try:
                second_response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages_history,
                    temperature=0.1
                )
                return second_response.choices[0].message.content
            except Exception as e:
                return "🚨 获取最终决策时发生网络波动，请重试。"
        else:
            return "🧠 抱歉，我查询天气时遇到了一点格式问题，能换个说法问我吗？"

    # ==========================================
    # 正常、乖巧的 Function Calling 处理流程
    # ==========================================
    if tool_calls:
        messages_history.append(response_message)
        
        for tool_call in tool_calls:
            if tool_call.function.name == "get_weather":
                function_args = json.loads(tool_call.function.arguments)
                city = function_args.get("city", "")
                
                weather_result = fetch_weather_for_city(city)
                
                messages_history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": "get_weather",
                    "content": str(weather_result), # 确保传入的是字符串
                })
        
        # 二次调用生成最终结果
        second_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_history,
            temperature=0.1
        )
        return second_response.choices[0].message.content
        
    else:
        # 如果没有触发工具（比如纯聊天），直接返回文本
        return response_message.content
