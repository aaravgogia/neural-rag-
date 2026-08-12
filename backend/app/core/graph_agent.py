import logging
from typing import TypedDict, Annotated, List, Optional
import operator

from langchain_openai import ChatOpenAI
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.core.vector_store import VectorStoreManager
from app.core.conversation_memory import ConversationMemoryService

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    question: str
    context: str
    answer: str
    sources: List[dict]
    needs_retrieval: bool
    needs_improvement: bool
    iteration: int
    namespace: Optional[str]
    session_id: str
    user_id: str
    workspace_id: str
    conversation_context: str

class RAGGraphAgent:
    """
    LangGraph-powered agent: analyze -> retrieve -> generate -> grade -> (retry | end)
    Self-corrects up to 2 times if the grader thinks the answer is weak.
    """

    def __init__(self, vector_store: VectorStoreManager, memory_service: ConversationMemoryService | None = None):
        self.vector_store = vector_store
        self.llm = ChatOpenAI(model=settings.LLM_MODEL, temperature=0, openai_api_key=settings.OPENAI_API_KEY)
        self.memory = MemorySaver()
        self.conversation_memory = memory_service or ConversationMemoryService()
        self.graph = self._build_graph()

    async def analyze_query(self, state: AgentState) -> AgentState:
        try:
            conversation_context = (await self.conversation_memory.load(state.get("session_id"))).text
        except Exception:
            logger.warning("Conversation memory unavailable; continuing without history", exc_info=True)
            conversation_context = ""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Analyze if this question requires document retrieval.
            Return JSON: {{"needs_retrieval": true/false, "refined_query": "..."}}
            Return needs_retrieval=false for greetings, small talk, simple math, or general knowledge."""),
            ("human", "Conversation memory:\n{conversation_context}\n\nQuestion: {question}")
        ])
        from langchain_core.output_parsers import JsonOutputParser
        chain = prompt | self.llm | JsonOutputParser()
        result = await chain.ainvoke({"question": state["question"], "conversation_context": conversation_context})
        return {**state, "needs_retrieval": result.get("needs_retrieval", True),
                "question": result.get("refined_query", state["question"]), "conversation_context": conversation_context}

    async def retrieve_documents(self, state: AgentState) -> AgentState:
        docs = await self.vector_store.similarity_search(
            query=state["question"], user_id=state["user_id"], workspace_id=state["workspace_id"], k=settings.TOP_K_RESULTS, namespace=state.get("namespace")
        )
        context_parts, sources = [], []
        for i, (doc, score) in enumerate(docs):
            source_info = {
                "content": doc.page_content[:300],
                "source": doc.metadata.get("source", "Unknown"),
                "page": doc.metadata.get("page", "N/A"),
                "score": float(score),
                "document_id": doc.metadata.get("document_id"),
            }
            sources.append(source_info)
            context_parts.append(f"[Doc {i+1} | Source: {source_info['source']}]\n{doc.page_content}")
        return {**state, "context": "\n\n---\n\n".join(context_parts), "sources": sources}

    async def generate_answer(self, state: AgentState) -> AgentState:
        if state.get("needs_retrieval") and state.get("context"):
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert AI assistant. Answer based on the context.\n\nContext:\n{context}\n\nConversation memory:\n{conversation_context}"),
                ("human", "{question}")
            ])
            chain = prompt | self.llm
            response = await chain.ainvoke({"context": state["context"], "question": state["question"], "conversation_context": state.get("conversation_context", "")})
        else:
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are a helpful AI assistant. Use conversation memory to resolve follow-ups.\n{conversation_context}"), ("human", "{question}")
            ])
            chain = prompt | self.llm
            response = await chain.ainvoke({"question": state["question"], "conversation_context": state.get("conversation_context", "")})

        answer = response.content
        messages = state["messages"] + [HumanMessage(content=state["question"]), AIMessage(content=answer)]
        return {**state, "answer": answer, "messages": messages}

    async def grade_answer(self, state: AgentState) -> AgentState:
        if not state.get("needs_retrieval"):
            return {**state, "needs_improvement": False}
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Grade this answer. Return JSON: {{"score": 1-10, "needs_improvement": true/false}}
            Score >= 7 is good."""),
            ("human", "Question: {question}\nContext: {context}\nAnswer: {answer}")
        ])
        from langchain_core.output_parsers import JsonOutputParser
        chain = prompt | self.llm | JsonOutputParser()
        try:
            result = await chain.ainvoke({"question": state["question"], "context": state["context"], "answer": state["answer"]})
            needs_improvement = result.get("needs_improvement", False) and state.get("iteration", 0) < 2
        except Exception:
            needs_improvement = False
        return {**state, "needs_improvement": needs_improvement, "iteration": state.get("iteration", 0) + 1}

    async def handle_no_retrieval(self, state: AgentState) -> AgentState:
        return await self.generate_answer(state)

    def route_query(self, state: AgentState) -> str:
        return "retrieve" if state.get("needs_retrieval") else "direct_answer"

    def should_retry(self, state: AgentState) -> str:
        return "retry" if state.get("needs_improvement") else "end"

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(AgentState)
        workflow.add_node("analyze_query", self.analyze_query)
        workflow.add_node("retrieve_documents", self.retrieve_documents)
        workflow.add_node("generate_answer", self.generate_answer)
        workflow.add_node("grade_answer", self.grade_answer)
        workflow.add_node("direct_answer", self.handle_no_retrieval)

        workflow.set_entry_point("analyze_query")
        workflow.add_conditional_edges("analyze_query", self.route_query,
            {"retrieve": "retrieve_documents", "direct_answer": "direct_answer"})
        workflow.add_edge("retrieve_documents", "generate_answer")
        workflow.add_edge("generate_answer", "grade_answer")
        workflow.add_edge("direct_answer", END)
        workflow.add_conditional_edges("grade_answer", self.should_retry,
            {"retry": "retrieve_documents", "end": END})

        return workflow.compile(checkpointer=self.memory)

    async def run(self, question: str, session_id: str, user_id: str, workspace_id: str, namespace: Optional[str] = None) -> dict:
        initial_state = AgentState(
            messages=[], question=question, context="", answer="", sources=[],
            needs_retrieval=True, needs_improvement=False, iteration=0, namespace=namespace, user_id=user_id, workspace_id=workspace_id, session_id=session_id, conversation_context=""
        )
        config = {"configurable": {"thread_id": session_id}}
        result = await self.graph.ainvoke(initial_state, config=config)
        return {"answer": result["answer"], "sources": result.get("sources", []),
                "question": question, "session_id": session_id}
