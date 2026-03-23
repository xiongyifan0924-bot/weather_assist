import streamlit as st
import re
from llm_agent import chat_with_agent

# 页面基础配置
st.set_page_config(page_title="AI 场景化出行助理", page_icon="🧭", layout="centered")
st.title("🧭 AI 场景化出行决策助理")

# 初始化 Session 记忆体系
if "messages" not in st.session_state:
    st.session_state.messages = []
    # 模拟良好的开场白体验
    st.session_state.messages.append({
        "role": "assistant", 
        "content": "您好！我是您开发的 AI 出行决策助理。您可以问我类似“这周末去广州看小蛮腰天气怎么样？”的问题，我将为您调取气象基座数据并提供决策指引。"
    })

# 渲染历史气泡
for msg in st.session_state.messages:
    # 【防御性编程核心】：增加 isinstance(msg, dict) 的判断！
    # 哪怕历史缓存里混入了对象或纯字符串等脏数据，这一层装甲也能保证页面不崩溃
    if isinstance(msg, dict) and msg.get("role") in ["user", "assistant"]:
        content = msg.get("content", "")
        if isinstance(content, str):
            with st.chat_message(msg.get("role")):
                st.markdown(content)

# 接收用户指令并触发管线 (Pipeline)
if user_input := st.chat_input("输入您的出行计划..."):
    # 1. 渲染用户输入
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # 2. 调度 Agent 处理
    with st.chat_message("assistant"):
        with st.spinner("正在为您调取最新天气并定制出行方案..."):
            
            # 获取 Agent 回复
            response = chat_with_agent(st.session_state.messages)
            
            # 【强制类型转换】：防止底层 API 返回非字符串对象导致后续崩溃
            response_text = str(response) if response is not None else "抱歉，系统暂时无法响应。"
            
            # 【前端正则兜底拦截】：干掉大模型暴露的 < | DSML | xxx > 机器代码乱码
            # 将所有带有 DSML 的尖括号标签替换为空字符串
            clean_response = re.sub(r'<\s*\|\s*DSML\s*\|[^>]*>', '', response_text)
            
            # 打印经过清洗的干净回复
            st.markdown(clean_response)
            
    # 3. 将完整且干净的回复追加到历史记录
    st.session_state.messages.append({
        "role": "assistant", 
        # 注意：这里存入的是 clean_response，确保后续多轮对话喂给模型的上下文也是干净的
        "content": clean_response 
    })
