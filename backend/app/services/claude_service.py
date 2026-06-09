"""
Claude API Service — generate natural-language explanations for SQL variables.

Uses the Anthropic SDK with streaming to explain what each variable
represents in the GPS financial domain context.
"""

import json
import asyncio
from typing import AsyncGenerator

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

SYSTEM_PROMPT = """You are a financial SQL analyst specializing in GPS (Global Payments System) data.
Your job is to explain SQL variables in clear, business-focused natural language.

For each variable, provide:
1. **Business Meaning**: What this represents in the payments/settlement domain
2. **Computation**: How it's derived (the SQL expression explained in plain English)
3. **Data Lineage**: Which tables and columns contribute to this value
4. **Dependencies**: What other variables or table fields it depends on
5. **Business Significance**: Why this metric matters for financial operations

Keep explanations concise (2-3 sentences per point) but insightful.
Use financial domain terminology appropriately (settlement, reconciliation,
chargeback, net settlement, FX, risk scoring, etc.).

Respond in valid JSON format:
{
  "explanations": {
    "variable_id": {
      "business_meaning": "...",
      "computation": "...",
      "data_lineage": "...",
      "dependencies": "...",
      "business_significance": "..."
    }
  }
}"""


async def stream_explanation(
    analysis: dict, variable_ids: list[str] | None = None
) -> AsyncGenerator[str, None]:
    """Stream Claude's NL explanation via SSE.

    Args:
        analysis: The full analysis dict.
        variable_ids: Specific variable IDs to explain (None = all).

    Yields:
        SSE-formatted strings with explanation tokens.
    """
    import anthropic

    variables = analysis.get("variables", [])
    if variable_ids:
        variables = [v for v in variables if v["id"] in variable_ids]

    if not variables:
        yield f"data: {json.dumps({'error': 'No variables to explain'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Build the user prompt
    var_list = []
    for v in variables:
        var_list.append({
            "id": v["id"],
            "name": v["name"],
            "type": v.get("variable_type", "unknown"),
            "sql_expression": v.get("sql_expression", ""),
            "source_tables": v.get("source_tables", []),
            "defined_in": v.get("defined_in", ""),
            "is_output": v.get("is_output", False),
        })

    user_prompt = f"""Analyze the following SQL variables from a GPS (Global Payments System) script.

Script: {analysis.get('script_name', 'unknown')}

Variables to explain:
{json.dumps(var_list, indent=2)}

For each variable, explain its business meaning in the GPS domain, how it is
computed, its data lineage (source tables/columns), its dependencies, and its
business significance for financial operations.
"""

    try:
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        async with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"

        final = stream.get_final_message()
        # Try to cache the result
        try:
            response_text = ""
            for block in final.content:
                if block.type == "text":
                    response_text += block.text
            yield f"data: {json.dumps({'done': True, 'full_response': response_text})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'done': True})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
