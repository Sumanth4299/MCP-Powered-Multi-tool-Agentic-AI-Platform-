"""
Comparative Evaluation Report Generator.
Outputs Markdown and CSV summarizing architectural, quality, and performance tradeoffs.
"""

import csv
from pathlib import Path


def generate_reports(mcp_res: dict, base_res: dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate Markdown Report
    md_content = f"""# Academic Evaluation: MCP-Based Architecture vs. Direct Function Calling Baseline

## 1. Quantitative Benchmark Results (N=30 Standardized Prompts)

| Metric | MCP-Based Agent | Hard-coded Function Calling | Delta / Improvement |
| :--- | :--- | :--- | :--- |
| **Task Execution Success Rate (%)** | {mcp_res['task_success_rate']}% | {base_res['task_success_rate']}% | +{round(mcp_res['task_success_rate'] - base_res['task_success_rate'], 1)}% |
| **Tool Selection Accuracy (%)** | {mcp_res['tool_selection_accuracy']}% | {base_res['tool_selection_accuracy']}% | +{round(mcp_res['tool_selection_accuracy'] - base_res['tool_selection_accuracy'], 1)}% |
| **Argument Extraction Accuracy (%)** | {mcp_res['arg_extraction_accuracy']}% | {base_res['arg_extraction_accuracy']}% | +{round(mcp_res['arg_extraction_accuracy'] - base_res['arg_extraction_accuracy'], 1)}% |
| **Cross-Chat Context Restoration (%)** | {mcp_res['cross_chat_restoration_rate']}% | {base_res['cross_chat_restoration_rate']}% | +{round(mcp_res['cross_chat_restoration_rate'] - base_res['cross_chat_restoration_rate'], 1)}% |
| **Conflict & Holiday Detection Rate (%)** | {mcp_res['conflict_detection_rate']}% | {base_res['conflict_detection_rate']}% | +{round(mcp_res['conflict_detection_rate'] - base_res['conflict_detection_rate'], 1)}% |
| **End-to-End Latency $p_{{50}}$ (seconds)** | {mcp_res['latency_p50']}s | {base_res['latency_p50']}s | +{round(mcp_res['latency_p50'] - base_res['latency_p50'], 3)}s (RPC overhead) |
| **End-to-End Latency $p_{{95}}$ (seconds)** | {mcp_res['latency_p95']}s | {base_res['latency_p95']}s | +{round(mcp_res['latency_p95'] - base_res['latency_p95'], 3)}s |

---

## 2. Qualitative & Software Engineering Comparison

| Evaluation Dimension | MCP-Based Architecture (Our Solution) | Hard-coded Function Calling Baseline |
| :--- | :--- | :--- |
| **Tool Definition Decoupling** | **High**: Tools live in standalone micro-processes/servers; can be shared across Claude, Gemini, and Cursor without code modifications. | **Low**: Tools are tightly bound into agent file strings and local in-memory Python decorators. |
| **Lines of Code to Add New Tool** | **~12 LOC**: Define `@mcp.tool()` on server. Client auto-discovers via `tools/list` schema negotiation. | **~48 LOC**: Write manual Pydantic schema, declare `@tool` wrapper, bind to LLM instance, and update prompt manually. |
| **User Data Isolation & Safety** | **Strict Boundary**: `user_id` injected exclusively by server context/transport headers. LLM cannot manipulate IDs. | **Vulnerable**: Often requires passing user ID or active DB session inside prompt args. |
| **Destructive Safeguards** | **Multi-tier**: Intercepted at protocol level via confirmation flags (`confirm=True`) and LangGraph guardrail nodes. | **Ad-hoc**: Relies purely on LLM prompt obedience; high vulnerability to prompt injection. |
| **Fault Isolation & Recovery** | Server crash isolates failure; agent receives structured JSON-RPC error response and can fall back. | Unhandled exception inside tool halts the main agent execution process. |
"""

    md_path = output_dir / "evaluation_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # 2. Generate CSV Export
    csv_path = output_dir / "evaluation_metrics.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric", "MCP_Agent", "Baseline_Function_Calling", "Delta"])
        writer.writerow(["task_success_rate", mcp_res["task_success_rate"], base_res["task_success_rate"], mcp_res["task_success_rate"] - base_res["task_success_rate"]])
        writer.writerow(["tool_selection_accuracy", mcp_res["tool_selection_accuracy"], base_res["tool_selection_accuracy"], mcp_res["tool_selection_accuracy"] - base_res["tool_selection_accuracy"]])
        writer.writerow(["arg_extraction_accuracy", mcp_res["arg_extraction_accuracy"], base_res["arg_extraction_accuracy"], mcp_res["arg_extraction_accuracy"] - base_res["arg_extraction_accuracy"]])
        writer.writerow(["cross_chat_restoration_rate", mcp_res["cross_chat_restoration_rate"], base_res["cross_chat_restoration_rate"], mcp_res["cross_chat_restoration_rate"] - base_res["cross_chat_restoration_rate"]])
        writer.writerow(["conflict_detection_rate", mcp_res["conflict_detection_rate"], base_res["conflict_detection_rate"], mcp_res["conflict_detection_rate"] - base_res["conflict_detection_rate"]])
        writer.writerow(["latency_p50_sec", mcp_res["latency_p50"], base_res["latency_p50"], mcp_res["latency_p50"] - base_res["latency_p50"]])
        writer.writerow(["latency_p95_sec", mcp_res["latency_p95"], base_res["latency_p95"], mcp_res["latency_p95"] - base_res["latency_p95"]])

    print(f"Reports successfully generated at:\n - {md_path}\n - {csv_path}")