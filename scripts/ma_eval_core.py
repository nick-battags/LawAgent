"""Reusable answer-faithfulness evaluator."""

from __future__ import annotations

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama


def evaluate_ma_faithfulness(
    query: str,
    context: str,
    answer: str,
    model: str = "qwen2.5:7b",
    verbose: bool = True,
) -> dict:
    judge = ChatOllama(model=model, temperature=0.0, format="json")
    prompt = PromptTemplate(
        template=(
            "You are an M&A quality auditor.\n"
            "Evaluate whether the ANSWER is fully supported by the provided CONTEXT.\n"
            "Use only these two scores:\n"
            "1 = answer includes any unsupported claim\n"
            "5 = every claim is supported by context\n\n"
            "QUERY:\n{query}\n\n"
            "CONTEXT:\n{context}\n\n"
            "ANSWER:\n{answer}\n\n"
            'Return JSON only: {{"score": 1 or 5, "reasoning": "..."}}'
        ),
        input_variables=["query", "context", "answer"],
    )

    chain = prompt | judge | JsonOutputParser()
    result = chain.invoke({"query": query, "context": context, "answer": answer})
    raw_score = result.get("score", 1)
    score = 5 if str(raw_score).strip() == "5" else 1
    reasoning = str(result.get("reasoning", "")).strip()

    if verbose:
        print(f"Faithfulness Score: {score}/5")
        print(f"Reasoning: {reasoning}")
        if score < 5:
            print("Potential hallucination detected.")

    return {"score": score, "reasoning": reasoning}

