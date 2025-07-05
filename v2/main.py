from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import RunnableLambda
from langgraph.graph import StateGraph
from langchain.memory import ConversationBufferWindowMemory
from llm_tools.tools import graph_nodes, paused_channels, faq_response_func
from dotenv import load_dotenv
from discord.ext import tasks
from utils.support_utils import create_channel, is_filtered, send_help, channel_activity
from config import constants
from typing import TypedDict
import os
import discord
import asyncio

# ────────────── 환경 변수 및 설정 ──────────────
load_dotenv()
TOKEN = os.getenv("TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FAQ = constants.FAQ
ALLOWED_CHANNEL_IDS = constants.ALLOWED_CHANNEL_IDS
THANK_WORDS = constants.THANK_WORDS
BLOCKED_WORDS = constants.BLOCKED_WORDS
INJECTION_KEYWORDS = constants.INJECTION_KEYWORDS

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True  # ✅ 이 줄 꼭 추가
client = discord.Client(intents=intents)
user_history = {}

channel_activity = channel_activity
paused_channels = paused_channels

class ChatState(TypedDict, total=False):
    input: str
    chat_history: list[dict]
    result: str
    branch: str
    guild: discord.Guild
# ────────────── LLM, Agent ──────────────
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.7,
    google_api_key=GEMINI_API_KEY
)

memory = ConversationBufferWindowMemory(k=10, memory_key="chat_history", return_messages=True)
# ────────────── LangGraph 구성 ──────────────
def route_node(state: ChatState) -> str:
    content = state["input"]

    # 1. 문의 관련
    if content.startswith("!문의"):
        return "문의"
    
    # 2. FAQ 매칭
    if faq_response_func(content) != "FAQ에서 답변을 찾을 수 없습니다.":
        return "faq_response"
    
    # 3. 마니또 관련
    if any(keyword in content for keyword in ["!마니또", "마니또", "마니띠", "이번 주 마니또"]):
        return "this_week_manittee"
    
    # 4. 공지 관련 (좀 더 자연어 포함)
    if any(keyword in content for keyword in ["!공지", "공지", "공지사항", "최근 공지", "무슨 공지", "무슨 소식", "최근 소식"]):
        return "notice_summary"

    # 5. 정지 관련
    if any(keyword in content for keyword in ["!정지", "멈춰", "말하지 마", "잠깐 쉬어"]):
        return "pause_messaging"
    
    # 6. 그 외 일반 질문은 Gemini로
    return "gemini_answer"
    
# Gemini node에 memory 포함
def gemini_with_memory(state: ChatState) -> ChatState:
     # 2) 이 함수에서 state 전체를 받아서 dict으로 반환
     prompt = "\n".join(
         f"{m['role']}: {m['content']}" for m in state["chat_history"]
     ) + f"\nuser: {state['input']}"
     response = llm.invoke(prompt).content
     return {
         **state,
         "result": response,
         "chat_history": state["chat_history"] + [
             {"role": "user",    "content": state["input"]},
             {"role": "assistant","content": response}
         ]
     }

router = RunnableLambda(lambda state: {
    **state,
    "branch": route_node(state)
})

builder = StateGraph(ChatState)
builder.set_entry_point("router")

faq_node = RunnableLambda(lambda state: {
    **state,
    "result": faq_response_func(state["input"])
})
gemini_node = RunnableLambda(gemini_with_memory)
manittee_node = graph_nodes["this_week_manittee"]
pause_node = graph_nodes["pause_messaging"]
notice_node = graph_nodes["notice_summary"]
inquiry_node  = RunnableLambda(lambda state: {
     **state,
     "result": "문의 채널"
 })

builder.add_node("router", router)
builder.add_node("faq_response",       faq_node)
builder.add_node("gemini_answer",      gemini_node)
builder.add_node("this_week_manittee", manittee_node)
builder.add_node("pause_messaging",    pause_node)
builder.add_node("notice_summary",     notice_node)
builder.add_node("문의",               inquiry_node)

builder.add_conditional_edges(
    "router",
    route_node,  # 라우터 함수 직접 전달
    {
        "faq_response":       "faq_response",
        "gemini_answer":      "gemini_answer",
        "this_week_manittee": "this_week_manittee",
        "pause_messaging":    "pause_messaging",
        "notice_summary":     "notice_summary",
        "문의":               "문의"
    }
)

chat_graph = builder.compile()
# ────────────── 디스코드 메시지 처리 ──────────────
async def handle_user_message(message):
    cid = message.channel.id
    now = asyncio.get_event_loop().time()
    if message.author == client.user:
        return

    content = message.content.strip()

    # 멈춤 여부 확인
    if paused_channels.get(cid) and now < paused_channels[cid]:
        return

    # 채널 활동 갱신
    if cid in ALLOWED_CHANNEL_IDS:
        channel_activity[cid] = discord.utils.utcnow()

    # 문의 채널 처리
    if content.startswith("!문의-운영진"):
        ch = await create_channel(message.guild, message.author, include_admin=True)
        await ch.send(f"{message.author.mention} 운영진에게 연결되었습니다.")
        return

    if content == "!문의":
        ch = await create_channel(message.guild, message.author, include_admin=False)
        if ch.name.endswith(f"-{message.author.name}"):
            await ch.send(f"{message.author.mention} 문의 채널이 생성되었습니다.")
        else:
            await message.channel.send(f"{message.author.mention} 이미 있어요: {ch.mention}")
        return

    # 금칙어 필터링
    if is_filtered(content.lower()):
        if content.lower().startswith(("도움", "헬프")) or content.lower() == "help":
            return await send_help(message.channel)
        return await message.channel.send("⚠️ 부적절하거나 처리할 수 없는 내용이에요.")

    # LangGraph 분기 실행
    uid = message.author.id  # 사용자 ID로 히스토리 분리

    try:
        result = await chat_graph.ainvoke({
            "input": content,
            "chat_history": user_history.get(uid, []),
            "guild": message.guild  # ✅ 이걸 전달
        })
        # 대화 히스토리 갱신
        user_history[uid] = result.get("chat_history", [])

        # 결과를 꺼내서 디스코드에 전송
        response = result.get("result", "⚠️ 결과가 없어요.")
        await message.channel.send(response)    # ← 여기서 실제로 보냄
    except Exception as e:
        await message.channel.send(f"❗️ 오류가 발생했어요: {e}")
# ────────────── 디스코드 이벤트 ──────────────
@client.event
async def on_ready():
    print(f"🌰 마롱 챗봇이 준비되었습니다! {client.user}")
    print(f"[DEBUG] 현재 연결된 서버 수: {len(client.guilds)}")
    for guild in client.guilds:
        print(f"[DEBUG] 서버 이름: {guild.name}, ID: {guild.id}")
        channel = guild.get_channel(1373910102913847366)
        if channel:
            print(f"[DEBUG] 공지 채널 이름: {channel.name}, 타입: {type(channel)}")
        else:
            print("[DEBUG] 공지 채널을 찾을 수 없습니다.")
    check_inactive_channels.start()

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    await handle_user_message(message)

@tasks.loop(minutes=5)
async def check_inactive_channels():
    now = discord.utils.utcnow()
    to_delete = []

    for channel_id, last_active in channel_activity.items():
        if (now - last_active).total_seconds() > 3600 * 12:
            to_delete.append(channel_id)

    for cid in to_delete:
        channel = client.get_channel(cid)
        if channel:
            try:
                await channel.send("12시간 동안 활동이 없어 자동으로 삭제됩니다.")
                await channel.delete()
                print(f"[INFO] 채널 자동 삭제됨: {channel.name}")
            except Exception as e:
                print(f"[ERROR] 채널 삭제 실패: {e}")
        channel_activity.pop(cid, None)

# ────────────── 실행 ──────────────
if __name__ == "__main__":
    client.run(TOKEN)