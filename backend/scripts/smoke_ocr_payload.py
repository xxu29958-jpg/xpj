"""Exercise the frozen IPC process and offline models before bundle publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path


def smoke(payload: Path) -> dict:
    # -I keeps ambient paths out; only this sealed source snapshot is admitted.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PIL import Image, ImageDraw, ImageFont

    from app.services.ocr_worker_client import OcrWorkerClient

    client = OcrWorkerClient(command=[str(payload / "ticketbox-ocr.exe"),
        "--recipe", str(payload / "recipe.json"), "--model-root", str(payload / "models")])
    try:
        with tempfile.TemporaryDirectory(prefix="ticketbox-ocr-smoke-") as directory:
            path = Path(directory) / "offline-receipt.png"
            image = Image.new("RGB", (640, 200), "white")
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default(size=32)
            draw.text((30, 30), "OCR SELF CHECK\nTOTAL 12.34", font=font, fill="black", spacing=15)
            image.save(path)
            image.close()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result = client.recognize(path, digest)
            text = "\n".join(block["text"] for block in result["blocks"])
            if "TOTAL" not in text or "12.34" not in text:
                raise RuntimeError("Frozen OCR did not recognize the offline smoke receipt")
            return {"schema": 1, "outcome": "success", "input_sha256": digest,
                    "identity": result["identity"], "text": text, "timings_ms": result["timings_ms"]}
    finally:
        client.close()
        if client.pid is not None:
            raise RuntimeError("Frozen OCR smoke left its worker alive")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    result = smoke(args.payload)
    (args.payload / "BUILD_SMOKE.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
