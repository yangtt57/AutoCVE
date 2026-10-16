"""验证证据契约。

这个模块是"真实动态验证"和"模型嘴炮"之间的唯一分界线，因此校验刻意偏严：

  - 结构不合法 → 直接判定该次验证失败（宁可白跑，也不要把垃圾写进漏洞管理）；
  - ``verdict=confirmed`` 必须附带**原始输出**，没有原始证据就不许确认；
  - ``refuted`` / ``unverifiable`` 必须给出理由；
  - 所有超长字段截断并打标，避免把整个构建日志灌进数据库。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

VERDICTS = ("confirmed", "refuted", "inconclusive", "unverifiable")
CONFIDENCE_LEVELS = ("high", "medium", "low")
ENVIRONMENT_METHODS = ("compose", "dockerfile", "minimal", "harness", "none")

DEFAULT_MAX_FIELD_CHARS = 20_000
# 证据整体上限：单字段 20k × 200 步理论上能到 8MB，JSON 列撑不住，
# 所以归一化后还要过一次总量预算。
DEFAULT_MAX_TOTAL_CHARS = 400_000
MIN_FIELD_CHARS_AFTER_TRIM = 200
MAX_STEPS = 200
MAX_HTTP_EXCHANGES = 100
MAX_ARTIFACTS = 200
MAX_LIST_ITEMS = 100


class VerificationEvidenceError(ValueError):
    """证据结构不合法。调用方应把这次验证标记为失败，而不是落库成结论。"""


def normalize_evidence(
    payload: Any,
    *,
    run_id: str,
    max_field_chars: int = DEFAULT_MAX_FIELD_CHARS,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
) -> dict[str, Any]:
    """校验并归一化 Agent 产出的证据。不合法就抛 ``VerificationEvidenceError``。"""
    if not isinstance(payload, dict):
        raise VerificationEvidenceError("evidence must be a JSON object")

    reported_run_id = _required_str(payload.get("run_id"))
    if reported_run_id and reported_run_id != run_id:
        raise VerificationEvidenceError(
            f"evidence run_id mismatch: expected {run_id!r}, got {reported_run_id!r}"
        )

    verdict = _as_str(payload.get("verdict")).lower()
    if verdict not in VERDICTS:
        raise VerificationEvidenceError(
            f"verdict must be one of {', '.join(VERDICTS)}; got {verdict!r}"
        )

    confidence = _as_str(payload.get("confidence")).lower()
    if confidence not in CONFIDENCE_LEVELS:
        raise VerificationEvidenceError(
            f"confidence must be one of {', '.join(CONFIDENCE_LEVELS)}; got {confidence!r}"
        )

    summary = _required_str(payload.get("summary"), max_field_chars)
    if not summary:
        raise VerificationEvidenceError("summary is required")

    environment = _normalize_environment(payload.get("environment"), max_field_chars)
    steps = _normalize_steps(payload.get("steps"), max_field_chars)
    http_exchanges = _normalize_http_exchanges(payload.get("http_exchanges"), max_field_chars)
    artifacts = _normalize_artifacts(payload.get("artifacts"), max_field_chars)
    reproduction = _normalize_str_list(payload.get("reproduction"), max_field_chars, "reproduction")
    limitations = _normalize_str_list(payload.get("limitations"), max_field_chars, "limitations")

    impact = _required_str(payload.get("impact"), max_field_chars)
    refutation_reason = _required_str(payload.get("refutation_reason"), max_field_chars)
    unverifiable_reason = _required_str(payload.get("unverifiable_reason"), max_field_chars)

    if verdict == "confirmed":
        if not _has_raw_evidence(steps, http_exchanges):
            raise VerificationEvidenceError(
                "verdict=confirmed requires at least one step with raw stdout/stderr "
                "or one HTTP exchange with a raw body"
            )
        if not reproduction:
            raise VerificationEvidenceError("verdict=confirmed requires a non-empty reproduction list")
        if not impact:
            raise VerificationEvidenceError("verdict=confirmed requires a non-empty impact")
    elif verdict == "refuted":
        if not refutation_reason:
            raise VerificationEvidenceError("verdict=refuted requires refutation_reason")
    elif verdict == "unverifiable":
        if not unverifiable_reason:
            raise VerificationEvidenceError("verdict=unverifiable requires unverifiable_reason")

    evidence = {
        "run_id": run_id,
        "verdict": verdict,
        "confidence": confidence,
        "summary": summary,
        "environment": environment,
        "steps": steps,
        "http_exchanges": http_exchanges,
        "impact": impact or None,
        "reproduction": reproduction,
        "refutation_reason": refutation_reason or None,
        "unverifiable_reason": unverifiable_reason or None,
        "limitations": limitations,
        "artifacts": artifacts,
    }
    _enforce_total_budget(evidence, max_total_chars=max_total_chars)
    return evidence


def _enforce_total_budget(evidence: dict[str, Any], *, max_total_chars: int) -> None:
    """把证据压到总量预算内：先对半裁最大的文本，再丢掉靠后的步骤。

    裁剪只影响可读性，不影响结论字段；被判为 confirmed 所需的"至少一条原始输出"
    仍然保留（先裁尾部，不裁首条）。
    """
    budget = max(1_000, int(max_total_chars))
    if _encoded_length(evidence) <= budget:
        return

    texts = list(_iter_large_texts(evidence))
    for index, _ in enumerate(range(6)):
        if _encoded_length(evidence) <= budget:
            return
        texts.sort(key=lambda item: len(item[2]), reverse=True)
        trimmed_any = False
        for container, key, value in texts:
            if len(value) <= MIN_FIELD_CHARS_AFTER_TRIM:
                continue
            container[key] = value[: max(MIN_FIELD_CHARS_AFTER_TRIM, len(value) // 2)] + " [truncated]"
            trimmed_any = True
            break
        if not trimmed_any:
            break

    # 极端情况下（单条输出就超预算），按顺序保留靠前的步骤与请求。
    while _encoded_length(evidence) > budget and evidence["steps"]:
        evidence["steps"].pop()
        evidence.setdefault("limitations", []).append("证据过大，已丢弃靠后的执行记录。")
    while _encoded_length(evidence) > budget and evidence["http_exchanges"]:
        evidence["http_exchanges"].pop()
        evidence.setdefault("limitations", []).append("证据过大，已丢弃靠后的 HTTP 交互记录。")


def _encoded_length(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _iter_large_texts(evidence: dict[str, Any]):
    for step in evidence.get("steps") or []:
        for key in ("stdout", "stderr"):
            value = step.get(key)
            if isinstance(value, str) and value:
                yield step, key, value
    for exchange in evidence.get("http_exchanges") or []:
        request = exchange.get("request") or {}
        response = exchange.get("response") or {}
        for container, key in ((request, "body"), (response, "body")):
            value = container.get(key) if isinstance(container, dict) else None
            if isinstance(value, str) and value:
                yield container, key, value
    for key in ("summary", "impact", "refutation_reason", "unverifiable_reason"):
        value = evidence.get(key)
        if isinstance(value, str) and value:
            yield evidence, key, value


def canonical_evidence_digest(evidence: dict[str, Any]) -> str:
    """给归一化后的证据算一个稳定摘要，用于判断"是不是同一次结论"。"""
    encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _has_raw_evidence(steps: list[dict[str, Any]], http_exchanges: list[dict[str, Any]]) -> bool:
    # 用 _required_str：只有空白字符的输出不算"原始证据"。
    for step in steps:
        if _required_str(step.get("stdout")) or _required_str(step.get("stderr")):
            return True
    for exchange in http_exchanges:
        response = exchange.get("response")
        if isinstance(response, dict) and _required_str(response.get("body")):
            return True
    return False


def _normalize_environment(raw: Any, max_field_chars: int) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise VerificationEvidenceError("environment must be a JSON object")
    method = _as_str(raw.get("method")).lower() or "none"
    if method not in ENVIRONMENT_METHODS:
        raise VerificationEvidenceError(
            f"environment.method must be one of {', '.join(ENVIRONMENT_METHODS)}; got {method!r}"
        )
    build_seconds = raw.get("build_seconds")
    try:
        build_seconds_value = max(0, int(build_seconds)) if build_seconds is not None else None
    except (TypeError, ValueError):
        build_seconds_value = None
    return {
        "method": method,
        "app_url": _required_str(raw.get("app_url"), max_field_chars) or None,
        "commit_sha": _required_str(raw.get("commit_sha"), max_field_chars) or None,
        "image_digest": _required_str(raw.get("image_digest"), max_field_chars) or None,
        "build_seconds": build_seconds_value,
        "notes": _required_str(raw.get("notes"), max_field_chars) or None,
    }


def _normalize_steps(raw: Any, max_field_chars: int) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise VerificationEvidenceError("steps must be a JSON array")
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:MAX_STEPS], start=1):
        if not isinstance(item, dict):
            raise VerificationEvidenceError(f"steps[{index}] must be a JSON object")
        exit_code = item.get("exit_code")
        try:
            exit_code_value = int(exit_code) if exit_code is not None else None
        except (TypeError, ValueError):
            exit_code_value = None
        steps.append(
            {
                "seq": _as_int(item.get("seq"), index),
                "intent": _as_str(item.get("intent"), max_field_chars),
                "command": _as_str(item.get("command"), max_field_chars),
                "exit_code": exit_code_value,
                "stdout": _as_str(item.get("stdout"), max_field_chars),
                "stderr": _as_str(item.get("stderr"), max_field_chars),
            }
        )
    return steps


def _normalize_http_exchanges(raw: Any, max_field_chars: int) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise VerificationEvidenceError("http_exchanges must be a JSON array")
    exchanges: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:MAX_HTTP_EXCHANGES], start=1):
        if not isinstance(item, dict):
            raise VerificationEvidenceError(f"http_exchanges[{index}] must be a JSON object")
        request = item.get("request")
        response = item.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise VerificationEvidenceError(
                f"http_exchanges[{index}] requires both 'request' and 'response' objects"
            )
        exchanges.append(
            {
                "seq": _as_int(item.get("seq"), index),
                "intent": _as_str(item.get("intent"), max_field_chars),
                "request": {
                    "method": _required_str(request.get("method"), 32).upper() or "GET",
                    "url": _required_str(request.get("url"), max_field_chars),
                    "headers": _normalize_headers(request.get("headers"), max_field_chars),
                    "body": _as_str(request.get("body"), max_field_chars),
                },
                "response": {
                    "status": _as_int(response.get("status"), 0),
                    "headers": _normalize_headers(response.get("headers"), max_field_chars),
                    "body": _as_str(response.get("body"), max_field_chars),
                },
            }
        )
    return exchanges


def _normalize_headers(raw: Any, max_field_chars: int) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    headers: dict[str, str] = {}
    for key, value in list(raw.items())[:MAX_LIST_ITEMS]:
        headers[_as_str(key, 200)] = _as_str(value, max_field_chars)
    return headers


def _normalize_artifacts(raw: Any, max_field_chars: int) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise VerificationEvidenceError("artifacts must be a JSON array")
    artifacts: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:MAX_ARTIFACTS], start=1):
        if not isinstance(item, dict):
            raise VerificationEvidenceError(f"artifacts[{index}] must be a JSON object")
        artifacts.append(
            {
                "path": _as_str(item.get("path"), max_field_chars),
                "sha256": _as_str(item.get("sha256"), 128),
                "bytes": _as_int(item.get("bytes"), 0),
            }
        )
    return artifacts


def _normalize_str_list(raw: Any, max_field_chars: int, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = _as_str(raw, max_field_chars)
        return [text] if text else []
    if not isinstance(raw, list):
        raise VerificationEvidenceError(f"{field_name} must be a JSON array of strings")
    values: list[str] = []
    for item in raw[:MAX_LIST_ITEMS]:
        text = _required_str(item, max_field_chars)
        if text:
            values.append(text)
    return values


def _as_str(value: Any, limit: int = 0) -> str:
    """转成字符串。

    ``limit > 0`` 时**不做 strip**：这个分支专门用于 stdout / stderr / HTTP body
    这类原始证据，保留原样的空白（缩进、换行对证据有含义）。
    需要"有没有真的填"的语义字段请用 ``_required_str``。
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    if limit == 0:
        return text.strip()
    if len(text) > limit:
        return text[:limit] + " [truncated]"
    return text


def _required_str(value: Any, limit: int = 0) -> str:
    """语义字段用：先去空白，空字符串（或纯空白）视为"没有提供"。"""
    return _as_str(value, limit).strip()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
