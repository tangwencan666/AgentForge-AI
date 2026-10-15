from langgraph.graph import StateGraph, START, END
from app.services.orchestration.graph import GraphState


def build_chat_graph(runtime, saver):
    async def chat(state):
        options = await runtime.options()
        result = await runtime.operation(options['chat_role'], 0, {'summary': '[MOCK] Chat response; no external model was called'})
        return {'chat': result['operation_id']}
    class ChatState(GraphState, total=False):
        chat: str
    builder = StateGraph(ChatState)
    builder.add_node('chat', chat)
    builder.add_edge(START, 'chat')
    builder.add_edge('chat', END)
    return builder.compile(checkpointer=saver)
