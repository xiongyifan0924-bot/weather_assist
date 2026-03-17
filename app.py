import streamlit as st
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
    # 过滤掉底层系统 Prompt 和底层 Tool 返回的数据，保持 UI 纯净
    if msg["role"] in ["user", "assistant"] and isinstance(msg["content"], str):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# 接收用户指令并触发管线 (Pipeline)
if user_input := st.chat_input("输入您的出行计划..."):
    # 1. 渲染用户输入
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # 2. 调度 Agent 处理
    with st.chat_message("assistant"):
        # 恢复你喜欢的转圈圈提示语
        with st.spinner("正在为您调取最新天气并定制出行方案..."):
            
            # 一次性拿到完整的回复字符串
            response = chat_with_agent(st.session_state.messages)
            
            # 使用 markdown 瞬间将完整报告打印在屏幕上
            st.markdown(response)
            
    # 将完整回复追加到历史记录
    st.session_state.messages.append({"role": "assistant", "content": response})

