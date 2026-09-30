"""JSON schemas sent to providers, derived from the strict Pydantic contract.

Providers differ in how much JSON Schema they accept (``$ref`` support, ``title``
keys ...), so we send a self-contained, reference-free version.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

from sentinel.core.domain.ai import AIFixPayload, AIReviewPayload

_DROP_KEYS = {"title", "default"}


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema with ``$ref``s resolved and noise keys removed."""
    schema = model.model_json_schema()
    defs: dict[str, Any] = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(copy.deepcopy(defs[name]))
            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in _DROP_KEYS:
                    continue
                out[k] = resolve(v)
            # Simplify Optional[X] (anyOf [X, null]) for providers with limited support.
            if set(out) >= {"anyOf"} and len(out["anyOf"]) == 2:
                non_null = [s for s in out["anyOf"] if s.get("type") != "null"]
                if len(non_null) == 1:
                    merged = {k: v for k, v in out.items() if k != "anyOf"}
                    merged.update(non_null[0])
                    merged["nullable"] = True
                    return merged
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    result: dict[str, Any] = resolve(schema)
    return result


def strip_nullable(schema: Any) -> Any:
    """Remove the OpenAPI-style ``nullable`` marker for strict JSON-Schema consumers."""
    if isinstance(schema, dict):
        return {k: strip_nullable(v) for k, v in schema.items() if k != "nullable"}
    if isinstance(schema, list):
        return [strip_nullable(v) for v in schema]
    return schema


REVIEW_SCHEMA = inline_schema(AIReviewPayload)
FIX_SCHEMA = inline_schema(AIFixPayload)
