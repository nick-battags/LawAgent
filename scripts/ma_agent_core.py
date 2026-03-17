"""Reusable M&A CRAG agent components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, TypedDict

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.graph import END, START, StateGraph


class GraphState(TypedDict, total=False):
    question: str
    generation: str
    documents: List[Document]
    search_needed: bool
    rewrites: int
    rewrite_history: List[str]


@dataclass
class AgentConfig:
    chroma_dir: Path = Path("chroma_db")
    collection: str = "ma_test"
    embed_model: str = "nomic-embed-text"
    llm_model: str = "qwen2.5:7b"
    k: int = 4
    max_rewrites: int = 2
    filters: dict[str, Any] | None = None


def ensure_vectorstore_ready(chroma_dir: Path) -> None:
    if not chroma_dir.exists() or not any(chroma_dir.iterdir()):
        raise FileNotFoundError(
            f"No vector store found at {chroma_dir.resolve()}.\n"
            "Run scripts/1_ingest_ma.py first."
        )


def serialize_documents(docs: List[Document], snippet_chars: int = 400) -> list[dict]:
    serialized = []
    for doc in docs:
        metadata = doc.metadata or {}
        snippet = " ".join(doc.page_content.split())
        serialized.append(
            {
                "source": str(metadata.get("source", "unknown")),
                "page": metadata.get("page", "unknown"),
                "source_file": str(metadata.get("source_file", "unknown")),
                "document_type": str(metadata.get("document_type", "Unknown")),
                "jurisdiction": str(metadata.get("jurisdiction", "Unspecified")),
                "practice_area": str(metadata.get("practice_area", "Unspecified")),
                "clause_type": str(metadata.get("clause_type", "General")),
                "section_heading": str(metadata.get("section_heading", "Unspecified")),
                "doc_id": str(metadata.get("doc_id", "unknown")),
                "snippet": snippet[:snippet_chars],
            }
        )
    return serialized


def context_from_documents(docs: List[Document]) -> str:
    return "\n\n".join(doc.page_content for doc in docs)


class MAAgent:
    def __init__(self, config: AgentConfig, verbose: bool = True):
        if config.k <= 0:
            raise ValueError("k must be > 0")
        if config.max_rewrites < 0:
            raise ValueError("max_rewrites must be >= 0")

        ensure_vectorstore_ready(config.chroma_dir)
        self.config = config
        self.verbose = verbose

        embeddings = OllamaEmbeddings(model=config.embed_model)
        vectorstore = Chroma(
            persist_directory=str(config.chroma_dir),
            embedding_function=embeddings,
            collection_name=config.collection,
        )
        search_kwargs: dict[str, Any] = {"k": config.k}
        if config.filters:
            search_kwargs["filter"] = config.filters
        self.retriever = vectorstore.as_retriever(search_kwargs=search_kwargs)
        self.llm = ChatOllama(model=config.llm_model, temperature=0.0)
        self.llm_json = ChatOllama(model=config.llm_model, temperature=0.0, format="json")
        self.app = self._build_graph(max_rewrites=config.max_rewrites)

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def _build_graph(self, max_rewrites: int):
        def retrieve(state: GraphState) -> GraphState:
            self._log("\n--- RETRIEVE ---")
            question = state["question"]
            docs = self.retriever.invoke(question)
            self._log(f"Retrieved {len(docs)} candidates.")
            return {"documents": docs, "question": question}

        def grade_documents(state: GraphState) -> GraphState:
            self._log("\n--- GRADE ---")
            question = state["question"]
            docs = state.get("documents", [])

            if not docs:
                self._log("No retrieved documents to grade.")
                return {"documents": [], "question": question, "search_needed": True}

            prompt = PromptTemplate(
                template=(
                    "You are an M&A paralegal.\n"
                    "Assess whether the contract excerpt is relevant to the due diligence question.\n\n"
                    "Question: {question}\n"
                    "Excerpt: {document}\n\n"
                    'Return JSON only: {{"score":"yes"}} for relevant, '
                    '{{"score":"no"}} for not relevant.'
                ),
                input_variables=["question", "document"],
            )
            chain = prompt | self.llm_json | JsonOutputParser()

            filtered = []
            for idx, doc in enumerate(docs, start=1):
                try:
                    result = chain.invoke(
                        {
                            "question": question,
                            "document": doc.page_content[:4000],
                        }
                    )
                    score = str(result.get("score", "")).strip().lower()
                    if score == "yes":
                        filtered.append(doc)
                        self._log(f"[Grader] Doc {idx}: relevant")
                    else:
                        self._log(f"[Grader] Doc {idx}: not relevant")
                except Exception as exc:  # pragma: no cover - runtime model errors
                    self._log(f"[Grader] Doc {idx}: error ({exc}); dropping")

            search_needed = len(filtered) == 0
            if search_needed:
                self._log("[Grader] No relevant excerpts left after grading.")

            return {"documents": filtered, "question": question, "search_needed": search_needed}

        def rewrite_query(state: GraphState) -> GraphState:
            self._log("\n--- REWRITE QUERY ---")
            question = state["question"]
            rewrites = state.get("rewrites", 0) + 1
            rewrite_history = list(state.get("rewrite_history", []))

            prompt = PromptTemplate(
                template=(
                    "Rewrite this due-diligence question to improve retrieval from legal contracts.\n"
                    "Focus on legal terms such as change of control, assignment, indemnification cap,\n"
                    "material adverse change, termination, and consent requirements.\n\n"
                    "Original: {question}\n"
                    "Rewritten query (single line only):"
                ),
                input_variables=["question"],
            )
            chain = prompt | self.llm | StrOutputParser()
            rewritten = chain.invoke({"question": question}).strip()
            if not rewritten:
                rewritten = question

            rewrite_history.append(rewritten)
            self._log(f"Rewrite #{rewrites}: {rewritten}")
            return {
                "question": rewritten,
                "documents": state.get("documents", []),
                "rewrites": rewrites,
                "rewrite_history": rewrite_history,
            }

        def generate(state: GraphState) -> GraphState:
            self._log("\n--- GENERATE ---")
            question = state["question"]
            docs = state.get("documents", [])
            context = context_from_documents(docs)
            if not context:
                context = "(No supporting excerpts retrieved.)"

            prompt = PromptTemplate(
                template=(
                    "You are an M&A legal consultant. Answer only from the provided excerpts.\n"
                    "If the excerpts do not support a claim, say: "
                    '"Not enough information in the provided documents."\n'
                    "Be concise and explicitly mention uncertainty where needed.\n\n"
                    "Context:\n{context}\n\n"
                    "Question: {question}\n"
                    "Answer:"
                ),
                input_variables=["question", "context"],
            )
            chain = prompt | self.llm | StrOutputParser()
            answer = chain.invoke({"context": context, "question": question})
            self._log(f"Generated answer preview: {answer[:200]}...")
            return {"generation": answer, "documents": docs, "question": question}

        def decide_route(state: GraphState) -> str:
            self._log("\n--- DECIDE ROUTE ---")
            if state.get("search_needed", False):
                if state.get("rewrites", 0) >= max_rewrites:
                    self._log("Max rewrite attempts reached -> generate")
                    return "generate"
                self._log("Need better retrieval -> rewrite")
                return "rewrite"
            self._log("Relevant context found -> generate")
            return "generate"

        workflow = StateGraph(GraphState)
        workflow.add_node("retrieve", retrieve)
        workflow.add_node("grade_documents", grade_documents)
        workflow.add_node("rewrite_query", rewrite_query)
        workflow.add_node("generate", generate)

        workflow.add_edge(START, "retrieve")
        workflow.add_edge("retrieve", "grade_documents")
        workflow.add_conditional_edges(
            "grade_documents",
            decide_route,
            {"rewrite": "rewrite_query", "generate": "generate"},
        )
        workflow.add_edge("rewrite_query", "retrieve")
        workflow.add_edge("generate", END)
        return workflow.compile()

    def run(self, query: str) -> dict:
        final_state = self.app.invoke({"question": query, "rewrites": 0, "rewrite_history": []})
        docs = final_state.get("documents", [])

        return {
            "query": query,
            "final_question": final_state.get("question", query),
            "answer": final_state.get("generation", ""),
            "rewrites": final_state.get("rewrites", 0),
            "rewrite_history": final_state.get("rewrite_history", []),
            "filters": self.config.filters or {},
            "documents": serialize_documents(docs),
            "context": context_from_documents(docs),
        }
