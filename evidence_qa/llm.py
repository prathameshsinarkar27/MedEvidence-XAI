"""Provider-independent LLM access (optional). The default is the deterministic extractive composer: no model needed.

`OpenAICompatibleProvider` speaks the widely implemented `/chat/completions` protocol, so one setting covers local open-source
servers (Ollama, llama.cpp server, vLLM, LM Studio) and, optionally, external APIs. Standard library only (urllib).

The model receives ONLY the verified evidence context (supporting evidence and evidence involved in a conflict) and must
return JSON claims that cite evidence aliases. Whatever it returns is validated by `guard.validate`; on any problem the
caller falls back to the extractive answer. Patient-document text is sent only to the configured endpoint; for a
non-local endpoint `LLM_ALLOW_EXTERNAL=true` must be set explicitly.
"""

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from evidence_qa.types import AnswerContext, Claim, Draft

SYSTEM_PROMPT = (
    "You write short, factual answers about uploaded medical documents. You are given a question and a list of evidence items "
    "extracted from those documents. Rules: use ONLY the evidence items; every claim must cite one or more evidence ids (E1, E2, ...); "
    "copy numbers, units and dates exactly as in the evidence; do not add medical knowledge, interpretation, diagnosis, advice or "
    "treatment recommendations; report negated, uncertain and family-history items as such; if the evidence conflicts, say so and do not "
    "choose a side; if the evidence is incomplete, say what is missing in a caveat. Reply with JSON only: "
    '{"claims": [{"text": "...", "evidence_ids": ["E1"]}], "caveats": ["..."], "acknowledges_conflict": false}.'
)


class ProviderError(Exception):
    """The provider could not produce a usable draft (unreachable, misconfigured, or malformed output)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def is_local_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in ("localhost", "host.docker.internal"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        try:
            return ipaddress.ip_address(socket.gethostbyname(host)).is_loopback
        except OSError:
            return False


def build_messages(ctx: AnswerContext) -> tuple[list[dict], dict[str, str]]:
    """The prompt. Returns the messages and alias -> real evidence id. Only verified evidence is included."""
    allowed = {e.id for e in ctx.supporting} | set(ctx.conflicting_ids)
    items = [e for e in ctx.by_id().values() if e.id in allowed]
    aliases = {e.id: f"E{n}" for n, e in enumerate(sorted(items, key=lambda x: (x.entity_name, x.date_iso or "", x.id)), start=1)}
    evidence = [{
        "id": aliases[e.id], "entity": e.entity_name, "type": e.entity_type, "statement": e.assertion, "value": e.value_text,
        "comparator": e.value_comparator, "unit": e.unit_text, "date": e.date_iso, "source_sentence": e.source_text,
        "document": e.document_filename, "page": e.page_number} for e in items]
    payload = {
        "question": ctx.question, "evidence_state": ctx.state,
        "state_notes": [text for _code, text, kind in ctx.state_reasons if kind in ("decisive", "limiting")],
        "evidence": evidence,
        "conflicts": [{"between": [aliases[i] for i in p.evidence_ids if i in aliases], "entity": p.entity_name, "kind": p.category}
                      for p in ctx.conflicts if p.in_scope and p.category == "possible_contradiction" and set(p.evidence_ids) <= set(aliases)],
    }
    return ([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            {alias: real for real, alias in aliases.items()})


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_response(text: str, alias_to_id: dict[str, str], provider: str) -> Draft:
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
        claims = [Claim(f"c{n}", str(c["text"]).strip(), [alias_to_id.get(str(i), str(i)) for i in c.get("evidence_ids", [])], "fact")
                  for n, c in enumerate(data["claims"], start=1) if str(c.get("text", "")).strip()]
        caveats = [str(x).strip() for x in data.get("caveats", []) if str(x).strip()]
        return Draft(claims, caveats, bool(data.get("acknowledges_conflict", False)), provider)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("invalid_model_output", "The model did not return the required JSON structure.") from exc


@dataclass(frozen=True)
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 60.0
    max_tokens: int = 600
    temperature: float = 0.0
    allow_external: bool = False
    name: str = "openai_compatible"

    @property
    def external(self) -> bool:
        return not is_local_url(self.base_url)

    def generate(self, ctx: AnswerContext) -> Draft:
        if not self.model:
            raise ProviderError("llm_not_configured", "LLM_MODEL is not set.")
        if self.external and not self.allow_external:
            raise ProviderError("external_not_allowed", "The LLM endpoint is not on this machine; set LLM_ALLOW_EXTERNAL=true to allow "
                                "sending the evidence text there.")
        messages, alias_to_id = build_messages(ctx)
        body = json.dumps({"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": self.max_tokens}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.base_url.rstrip("/") + "/chat/completions", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (URL comes from configuration)
                payload = json.loads(response.read().decode())
            content = payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError("llm_unavailable", "The language model endpoint could not be reached.") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid_model_output", "The model endpoint returned an unexpected response.") from exc
        return parse_response(content, alias_to_id, self.name)
