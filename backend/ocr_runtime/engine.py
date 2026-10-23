"""Offline model admission, actual ORT sessions and bounded image computation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import time
from pathlib import Path

from ocr_runtime.image_input import inference_image, source_coordinate_blocks
from ocr_runtime.native_runtime import WORKER_MEMORY_BYTES, configure_native_runtime
from ocr_runtime.protocol import OcrRuntimeError


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _model_file(root: Path, entry: dict) -> Path:
    path = root / entry["file"]
    if path.parent.resolve() != root.resolve() or not path.is_file():
        raise OcrRuntimeError("ocr_model_missing")
    if _digest(path) != entry["sha256"]:
        raise OcrRuntimeError("ocr_model_integrity_mismatch")
    return path


def _session(model: Path, options: dict):
    import onnxruntime as ort

    settings = ort.SessionOptions()
    settings.log_severity_level = 4
    settings.intra_op_num_threads = options["intra_threads"]
    settings.inter_op_num_threads = options["inter_threads"]
    settings.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    settings.enable_cpu_mem_arena = options["cpu_mem_arena"]
    settings.enable_mem_pattern = options.get("memory_pattern", True)
    settings.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    for key in ("session.intra_op.allow_spinning", "session.inter_op.allow_spinning"):
        settings.add_session_config_entry(key, "1" if options["spinning"] else "0")
    return ort.InferenceSession(str(model), sess_options=settings, providers=["CPUExecutionProvider"])


def _session_identity(session) -> dict:
    options = session.get_session_options()
    values = {"intra_threads": options.intra_op_num_threads,
              "inter_threads": options.inter_op_num_threads,
              "cpu_mem_arena": options.enable_cpu_mem_arena,
              "memory_pattern": options.enable_mem_pattern,
              "execution_mode": options.execution_mode.name,
              "providers": session.get_providers()}
    for key in ("session.intra_op.allow_spinning", "session.inter_op.allow_spinning"):
        try:
            values[key] = options.get_session_config_entry(key)
        except RuntimeError:
            values[key] = "runtime_default"
    return values


def _typed_params(params: dict) -> dict:
    from rapidocr.utils.typings import EngineType, LangCls, LangDet, LangRec, ModelType, OCRVersion, TaskType

    enums = {"engine_type": EngineType, "model_type": ModelType, "ocr_version": OCRVersion,
             "task_type": TaskType, "Det.lang_type": LangDet, "Cls.lang_type": LangCls, "Rec.lang_type": LangRec}
    result = dict(params)
    for key, value in params.items():
        converter = enums.get(key, enums.get(key.rsplit(".", 1)[-1]))
        if converter is not None:
            result[key] = converter(value)
    return result


def _verify_sessions(identities: dict, options: dict | None) -> None:
    if any(value["providers"] != ["CPUExecutionProvider"] for value in identities.values()):
        raise OcrRuntimeError("ocr_provider_mismatch")
    if options is None:
        return
    expected = {"intra_threads": options["intra_threads"], "inter_threads": options["inter_threads"],
                "cpu_mem_arena": options["cpu_mem_arena"], "execution_mode": "ORT_SEQUENTIAL",
                "memory_pattern": options.get("memory_pattern", True),
                "session.intra_op.allow_spinning": str(int(options["spinning"])),
                "session.inter_op.allow_spinning": str(int(options["spinning"]))}
    if any(any(value[key] != required for key, required in expected.items()) for value in identities.values()):
        raise OcrRuntimeError("ocr_session_options_mismatch")


def _admit_image(path: Path, digest: str, limits: dict) -> tuple[int, int]:
    from PIL import Image, UnidentifiedImageError

    if path.stat().st_size > limits["bytes"]:
        raise OcrRuntimeError("ocr_input_limit")
    if _digest(path) != digest:
        raise OcrRuntimeError("ocr_input_changed")
    try:
        with Image.open(path) as header:
            width, height = header.size
            if width * height > limits["pixels"] or max(width, height) > limits["side"]:
                raise OcrRuntimeError("ocr_input_limit")
            if header.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise OcrRuntimeError("ocr_input_limit") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OcrRuntimeError("ocr_image_invalid") from exc
    return width, height


def _valid_box(box: list, width: int, height: int) -> bool:
    return len(box) == 4 and all(len(point) == 2 and all(math.isfinite(v) for v in point)
                                and 0 <= point[0] <= width and 0 <= point[1] <= height for point in box)


def _evidence_blocks(result, width: int, height: int) -> list[dict]:
    texts = list(result.txts) if result.txts is not None else []
    scores = list(result.scores) if result.scores is not None else []
    boxes = result.boxes.tolist() if result.boxes is not None else []
    if not len(texts) == len(scores) == len(boxes) or len(texts) > 2000:
        raise OcrRuntimeError("ocr_output_invalid")
    blocks = []
    for text, score, box in zip(texts, scores, boxes, strict=True):
        score = float(score)
        if (not isinstance(text, str) or not math.isfinite(score) or not 0 <= score <= 1
                or len(text) > 8192 or not _valid_box(box, width, height)):
            raise OcrRuntimeError("ocr_output_invalid")
        blocks.append({"text": text, "confidence": score, "box": box})
    return blocks


class RapidEngine:
    def __init__(self, recipe_path: Path, model_root: Path, *, region_mode: bool = False) -> None:
        started = time.perf_counter()
        self.recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        if self.recipe.get("schema") != 1:
            raise OcrRuntimeError("ocr_recipe_invalid")
        if self.recipe.get("worker_limits", {}).get("memory_bytes", WORKER_MEMORY_BYTES) != WORKER_MEMORY_BYTES:
            raise OcrRuntimeError("ocr_recipe_invalid")
        for name, version in self.recipe["dependencies"].items():
            if importlib.metadata.version(name) != version:
                raise OcrRuntimeError("ocr_runtime_version_mismatch")
        if region_mode:
            from ocr_runtime.region import region_recipe

            self.recipe = region_recipe(self.recipe)
        models = {role: _model_file(model_root, entry) for role, entry in self.recipe["models"].items()}
        dictionary = _model_file(model_root, self.recipe["dictionary"])
        native = configure_native_runtime(self.recipe["native_runtime"]) if "native_runtime" in self.recipe else None
        from rapidocr import RapidOCR

        options = self.recipe.get("session_options")
        sessions = {role: _session(model, options) for role, model in models.items()} if options else {}

        class ExplicitSessions(RapidOCR):
            def _load_config(self, config_path, params):
                cfg = super()._load_config(config_path, params)
                # RapidOCR supports Det/Cls/Rec.session; OmegaConf must admit
                # the actual InferenceSession objects instead of YAML strings.
                cfg._set_flag("allow_objects", True)
                for role, session in sessions.items():
                    cfg[role].session = session
                return cfg

        params = _typed_params(self.recipe["params"])
        params.update({f"{role}.model_path": str(model) for role, model in models.items()})
        params.update({"Global.model_root_dir": str(model_root), "Rec.rec_keys_path": str(dictionary)})
        self.engine = ExplicitSessions(params=params)
        # 3.10 defers these wrappers until first use. Load through the wrapper's
        # own methods so session and dictionary admission still precedes input.
        for role in models:
            if getattr(self.engine, f"text_{role.lower()}") is None:
                getattr(self.engine, f"_load_{role.lower()}_model")()
        actual = {role: getattr(self.engine, f"text_{role.lower()}").session.session for role in models}
        identities = {role: _session_identity(session) for role, session in actual.items()}
        _verify_sessions(identities, options)
        characters = self.engine.text_rec.postprocess_op.character
        self.identity = {"recipe_sha256": _digest(recipe_path), "recipe_name": self.recipe["name"],
                         "models": self.recipe["models"], "dictionary": self.recipe["dictionary"],
                         "effective_dictionary_sha256": hashlib.sha256(
                             json.dumps(characters, ensure_ascii=False).encode("utf-8")).hexdigest(),
                         "dependencies": self.recipe["dependencies"], "sessions": identities,
                         "native_runtime": native,
                         "load_ms": (time.perf_counter() - started) * 1000}

    def recognize(self, path: Path, digest: str) -> dict:
        started = time.perf_counter()
        width, height = _admit_image(path, digest, self.recipe["input_limits"])
        admitted = time.perf_counter()
        with inference_image(path, self.recipe.get("decode_limits")) as (input_image, decoding):
            decoded = time.perf_counter()
            result = self.engine(input_image)
        inferred = time.perf_counter()
        decoded_width, decoded_height = decoding.get("width", width), decoding.get("height", height)
        if result.img is not None:
            # RapidOCR reports boxes against the decoded, EXIF-transposed image.
            # Use that actual surface instead of the encoded JPEG dimensions.
            decoded_height, decoded_width = map(int, result.img.shape[:2])
        blocks = _evidence_blocks(result, decoded_width, decoded_height)
        source_coordinate_blocks(blocks, source=(width, height), decoded=(decoded_width, decoded_height))
        stages = [float(v or 0) * 1000 for v in result.elapse_list]
        if any(not math.isfinite(value) or value < 0 for value in stages):
            raise OcrRuntimeError("ocr_output_invalid")
        return {"schema": self.recipe["output_schema"], "blocks": blocks, "width": width, "height": height,
                "coordinate_space": "exif-transposed-pixels",
                "decoding": decoding,
                "input_sha256": digest, "identity": self.identity,
                "timings_ms": {"admission": (admitted - started) * 1000,
                               "inference": (time.perf_counter() - admitted) * 1000,
                               "decode": (decoded - admitted) * 1000,
                               "engine": (inferred - decoded) * 1000,
                               "postprocess": (time.perf_counter() - inferred) * 1000,
                               "stages": stages}}

    def recognize_region(self, path: Path, digest: str, region: list[int]) -> dict:
        from ocr_runtime.region import region_blocks, region_image, validate_region

        started = time.perf_counter()
        width, height = _admit_image(path, digest, self.recipe["input_limits"])
        box = validate_region(region, width, height)
        with region_image(path, box, (width, height), self.recipe.get("decode_limits")) as (crop, decoding):
            result = self.engine(crop, use_det=False, use_cls=False, use_rec=True)
        return {"schema": self.recipe["output_schema"], "blocks": region_blocks(result, box),
                "width": width, "height": height, "region": list(box),
                "coordinate_space": "exif-transposed-pixels", "decoding": decoding,
                "input_sha256": digest, "identity": self.identity,
                "timings_ms": {"inference": (time.perf_counter() - started) * 1000}}
