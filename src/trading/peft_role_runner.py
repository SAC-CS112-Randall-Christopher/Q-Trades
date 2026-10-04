"""Inference-only private child. No dataset access, training, server or financial tools."""

import hashlib
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from trading.numerical_resources import constrain_child, own_limits
from trading.peft_profile import PROFILE, digest, metadata, read, regular


def windows_profile() -> bool:
    return os.name == "nt"


def generate(request: dict[str, Any]) -> dict[str, Any]:
    # Imports intentionally occur only after explicit dispatch and ownership.
    psutil = importlib.import_module("psutil")
    torch = importlib.import_module("torch")
    lab_model = importlib.import_module("llm_lab.model")
    Recipe = importlib.import_module("llm_lab.config").Recipe
    sha_file = importlib.import_module("llm_lab.io").sha_file
    token_ids = importlib.import_module("llm_lab.masking").token_ids
    PeftModel = importlib.import_module("peft").PeftModel
    transformers = importlib.import_module("transformers")

    started = time.perf_counter()
    if request["settings"] != PROFILE or not windows_profile():
        raise ValueError("Actual serving requires the frozen Windows CPU development profile")
    constrain_child(os.getpid())
    placement = own_limits()
    if placement["priority_class"] != 0x40 or placement["processors_allowed"] != 2:
        raise ValueError("Development child placement differs")
    if lab_model.source_identity()["source_sha256"] != request["lab_source_sha256"]:
        raise ValueError("Lab loader source changed")
    environment = lab_model.environment()
    if environment["python"] != PROFILE["python"] or any(
        environment.get(k) != v for k, v in PROFILE["packages"].items()
    ):
        raise ValueError("Actual CPU loader packages differ from the frozen development profile")
    linked = metadata(request["config"], Path(request["private_root"]))
    alias, run = linked["alias"], linked["run"]
    base, adapter = Path(alias["base_directory"]), Path(alias["adapter_directory"])
    identity = lab_model.verify_model(base)
    if identity["base_sha256"] != alias["base_sha256"] or (
        identity["revision"] != alias["base_revision"]
    ):
        raise ValueError("Pinned text base identity/revision differs")
    names = {p.name for p in adapter.iterdir()}
    if names != set(alias["adapter_files"]):
        raise ValueError("Frozen adapter membership differs")
    for name, expected in alias["adapter_files"].items():
        if Path(name).name != name or sha_file(regular(adapter / name)) != expected:
            raise ValueError("Trained adapter bytes changed")
    # Inference overrides are explicit. Do not reuse the CUDA/NF4 training recipe.
    recipe = Recipe.model_validate(
        run["recipe"]
        | {
            "name": "qtrades-v2-cpu-development",
            "device": "cpu",
            "precision": "float32",
            "quantization": "none",
            "cpu_threads": 2,
            "gradient_checkpointing": False,
            "max_length": PROFILE["max_context"],
        }
    )
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    tokenizer = lab_model.tokenizer_at(base)
    template_sha = digest(tokenizer.chat_template)
    if template_sha != run["masking"]["template_sha256"]:
        raise ValueError("Frozen training tokenizer template differs")
    ids = token_ids(
        tokenizer.apply_chat_template(
            [
                {"role": "system", "content": request["system"]},
                {"role": "user", "content": request["packet_json"]},
            ],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    )
    if len(ids) + PROFILE["max_new_tokens"] > PROFILE["max_context"]:
        raise ValueError("Complete role packet exceeds tokenized context; no truncation")
    if time.perf_counter() - started >= PROFILE["timeout_seconds"]:
        raise TimeoutError("Development verification consumed the complete wall budget")
    if psutil.virtual_memory().available < PROFILE["minimum_available_bytes"]:
        raise ValueError("Available memory reserve constrains development inference")
    loaded_at = time.perf_counter()
    model = PeftModel.from_pretrained(
        lab_model.load_base(base, recipe),
        adapter,
        is_trainable=False,
        local_files_only=True,
    )
    model.set_adapter("default")
    model.requires_grad_(False)
    model.eval()
    status = model.get_model_status()
    if (
        status.enabled is not True
        or status.active_adapters != ["default"]
        or status.merged_adapters
        or status.trainable_params != 0
        or any(
            p.requires_grad
            or p.device.type != "cpu"
            or (p.is_floating_point() and p.dtype != torch.float32)
            for p in model.parameters()
        )
    ):
        raise ValueError("Actual active frozen adapter/CPU precision differs")

    StoppingCriteria = transformers.StoppingCriteria

    class Stop(StoppingCriteria):  # type: ignore[misc,valid-type]
        def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
            return bool(time.perf_counter() - started >= PROFILE["timeout_seconds"])

    tokens = torch.tensor([ids], device="cpu")
    load_seconds = time.perf_counter() - loaded_at
    torch.manual_seed(PROFILE["seed"])
    generated_at = time.perf_counter()
    with torch.inference_mode():
        output = model.generate(
            tokens,
            attention_mask=torch.ones_like(tokens),
            do_sample=False,
            use_cache=True,
            max_new_tokens=PROFILE["max_new_tokens"],
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            stopping_criteria=transformers.StoppingCriteriaList([Stop()]),
        )[0, len(ids) :]
    raw = tokenizer.decode(output, skip_special_tokens=True)
    expired = time.perf_counter() - started >= PROFILE["timeout_seconds"]
    stopped = bool(len(output) and int(output[-1]) == tokenizer.eos_token_id and not expired)
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = None
    return {
        "raw_answer": raw,
        "answer": answer,
        "complete": stopped,
        "stop_reason": "wall_timeout" if expired else "eos" if stopped else "incomplete",
        "wall_seconds": time.perf_counter() - started,
        "load_seconds": load_seconds,
        "generation_seconds": time.perf_counter() - generated_at,
        "tokens": {"prompt_eval_count": len(ids), "eval_count": len(output)},
        "identity": {
            "candidate_sha256": linked["candidate_sha256"],
            "run_sha256": linked["run_sha256"],
            "base_sha256": identity["base_sha256"],
            "adapter_sha256": digest(alias["adapter_files"]),
            "lab_source_sha256": request["lab_source_sha256"],
            "template_sha256": template_sha,
        },
        "placement": placement
        | {
            "device": "cpu",
            "precision": "float32",
            "adapter_active": status.active_adapters,
            "trainable_params": 0,
        },
        "template_sha256": template_sha,
        "environment": environment,
        "peak_rss_bytes": psutil.Process().memory_info().peak_wset,
        "settings_sha256": digest(PROFILE),
    }


def main() -> None:
    job = regular(Path(sys.argv[1]))
    deadline = time.monotonic() + 5
    while not (job / "owner-ready").is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Parent did not establish owned child lifetime; no model loaded")
        time.sleep(0.01)
    request = read(job / "request.json")
    outcome: dict[str, Any] = {"request_sha256": digest(request)}
    try:
        if request["runner_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError("Development runner source changed")
        outcome["response"] = generate(request)
    except Exception as exc:
        # Private failure only; the parent records a bounded generic reason/link.
        outcome["error"] = type(exc).__name__ + ": " + str(exc)[:700]
    with (job / "response.json").open("x", encoding="utf-8") as out:
        out.write(json.dumps(outcome, allow_nan=False))
        out.flush()
        os.fsync(out.fileno())


if __name__ == "__main__":
    main()
