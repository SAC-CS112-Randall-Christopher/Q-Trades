"""Procedural loader objects only: verify call/settings contracts without importing weights."""

import hashlib
import importlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from test_peft_development import declared as declared

from trading.peft_profile import PROFILE, digest
from trading.peft_role_runner import generate


@pytest.mark.parametrize(
    "fault",
    [None, "inactive", "gpu", "precision", "context", "template", "packages", "missing", "weights"],
)
def test_direct_loader_contract_is_frozen_cpu_active_adapter_without_training(
    declared, monkeypatch, fault
):
    model, candidate, _ = declared
    cfg, selected, profile = model.declaration()
    alias = json.loads(candidate.read_text())
    adapter = Path(alias["adapter_directory"]) / "adapter_model.safetensors"
    adapter.write_bytes(b"procedural adapter bytes, not weights")
    # Refresh fixture metadata to bind the procedural bytes that this test hashes.
    files = {adapter.name: hashlib.sha256(adapter.read_bytes()).hexdigest()}
    run_path = Path(alias["run_directory"]) / "run.json"
    run = json.loads(run_path.read_text()) | {"candidate_files": files}
    run_path.write_text(json.dumps(run))
    alias["adapter_files"] = files
    candidate.write_text(json.dumps(alias))
    selected = selected | {
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "run_sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
    }
    request = {
        "settings": PROFILE,
        "lab_source_sha256": profile["identity"]["lab_source_sha256"],
        "config": selected,
        "private_root": cfg["private_root"],
        "system": "Procedural role prompt",
        "packet_json": '{"question":"Procedural"}',
    }
    parameter = NS(
        requires_grad=False,
        device=NS(type="cuda" if fault == "gpu" else "cpu"),
        dtype="f16" if fault == "precision" else "f32",
        is_floating_point=lambda: True,
    )
    status = NS(
        enabled=fault != "inactive",
        active_adapters=["default"],
        merged_adapters=[],
        trainable_params=0,
    )
    frozen = Mock()
    frozen.parameters.return_value = [parameter]
    frozen.get_model_status.return_value = status
    frozen.generate.return_value = NS()

    class Output:
        def __getitem__(self, index):
            return [7, 2]

    frozen.generate.return_value = Output()
    loader = Mock(return_value=frozen)
    tokenizer = NS(
        chat_template="changed" if fault == "template" else "procedural-template",
        pad_token_id=0,
        eos_token_id=2,
        apply_chat_template=Mock(return_value=[1] * (9000 if fault == "context" else 3)),
        decode=Mock(return_value='{"action":"no_change"}'),
    )
    environment = PROFILE["packages"] | {"python": PROFILE["python"]}
    if fault == "packages":
        environment["peft"] = "changed"
    load_base = Mock(return_value="procedural base")

    class Tensor:
        def __init__(self, value):
            self.value = value

        def detach(self):
            return self

        def to(self, *, device, dtype):
            assert (device, dtype) == ("cpu", "f32")
            return self

    state = Mock(
        return_value={}
        if fault == "missing"
        else {"lora_A.weight": Tensor(2 if fault == "weights" else 1)}
    )
    saved_tensors = Mock(return_value={"lora_A.weight": Tensor(1)})
    torch = NS(
        float32="f32",
        set_num_threads=Mock(),
        set_num_interop_threads=Mock(),
        tensor=Mock(return_value="procedural tensor"),
        ones_like=lambda value: "mask",
        manual_seed=Mock(),
        inference_mode=nullcontext,
        equal=lambda left, right: left.value == right.value,
    )
    modules = {
        "torch": torch,
        "psutil": NS(
            virtual_memory=lambda: NS(available=64 * 1024**3),
            Process=lambda: NS(memory_info=lambda: NS(peak_wset=100)),
        ),
        "llm_lab.model": NS(
            environment=lambda: environment,
            source_identity=lambda: {"source_sha256": request["lab_source_sha256"]},
            verify_model=lambda base: {"base_sha256": alias["base_sha256"], "revision": "fixture"},
            tokenizer_at=lambda base: tokenizer,
            load_base=load_base,
        ),
        "llm_lab.config": NS(Recipe=NS(model_validate=lambda value: NS(**value))),
        "llm_lab.io": NS(sha_file=lambda path: hashlib.sha256(path.read_bytes()).hexdigest()),
        "llm_lab.masking": NS(token_ids=lambda value: value),
        "peft": NS(PeftModel=NS(from_pretrained=loader), get_peft_model_state_dict=state),
        "safetensors.torch": NS(load_file=saved_tensors),
        "transformers": NS(StoppingCriteria=object, StoppingCriteriaList=list),
    }
    alias["base_revision"] = "fixture"
    candidate.write_text(json.dumps(alias))
    selected["candidate_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    original_import = importlib.import_module
    monkeypatch.setattr(
        "trading.peft_role_runner.importlib.import_module",
        lambda name: modules[name] if name in modules else original_import(name),
    )
    placement = Mock()
    monkeypatch.setattr("trading.peft_role_runner.constrain_child", placement)
    monkeypatch.setattr("trading.peft_role_runner.windows_profile", lambda: True)
    monkeypatch.setattr(
        "trading.peft_role_runner.own_limits",
        lambda: {"processors_allowed": 2, "priority_class": 64},
    )
    if fault:
        with pytest.raises(ValueError):
            generate(request)
        frozen.generate.assert_not_called()
        return
    response = generate(request)
    placement.assert_called_once_with(os.getpid(), distinct_cores=True)
    assert response["raw_answer"] == '{"action":"no_change"}' and response["complete"]
    assert response["identity"]["adapter_sha256"] == digest(files)
    assert response["placement"]["adapter_weights_verified"] is True
    assert response["placement"]["adapter_tensor_count"] == 1
    state.assert_called_once_with(frozen, adapter_name="default", save_embedding_layers="auto")
    saved_tensors.assert_called_once_with(str(adapter), device="cpu")
    recipe = load_base.call_args.args[1]
    assert (recipe.device, recipe.precision, recipe.quantization) == ("cpu", "float32", "none")
    assert loader.call_args.kwargs == {"is_trainable": False, "local_files_only": True}
    frozen.set_adapter.assert_called_once_with("default")
    frozen.requires_grad_.assert_called_once_with(False)
    assert frozen.generate.call_args.kwargs["do_sample"] is False
    assert tokenizer.apply_chat_template.call_args.kwargs["enable_thinking"] is False
