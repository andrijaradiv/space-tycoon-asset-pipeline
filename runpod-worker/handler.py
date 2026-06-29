import base64
import argparse
import json
import os
import tempfile
from pathlib import Path

import runpod


def write_input_image(image_base64: str, image_filename: str | None) -> Path:
    suffix = Path(image_filename or "input.png").suffix or ".png"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(base64.b64decode(image_base64))
    handle.close()
    return Path(handle.name)


def find_hunyuan_root() -> Path:
    configured = os.getenv("HUNYUAN3D_ROOT")
    candidates = [
        Path(configured) if configured else None,
        Path("/Hunyuan3D-2.1"),
        Path("/Hunyuan3D-2"),
        Path("/Hunyuan3D"),
        Path("/workspace/Hunyuan3D-2.1"),
        Path("/workspace/Hunyuan3D-2"),
        Path("/workspace/Hunyuan3D"),
        Path("/workspace/hunyan3d-2"),
        Path("/workspace/hunyuan3d-2.1"),
        Path("/workspace/hunyuan3d-2"),
        Path("/app/Hunyuan3D-2.1"),
        Path("/app/Hunyuan3D-2"),
        Path("/app/Hunyuan3D"),
        Path("/root/Hunyuan3D-2.1"),
        Path("/root/Hunyuan3D-2"),
        Path("/root/Hunyuan3D"),
        Path("/root/hunyan3d-2"),
        Path("/root/hunyuan3d-2"),
    ]

    for candidate in [path for path in candidates if path]:
        if (candidate / "hy3dshape").exists() or (candidate / "hy3dgen").exists():
            return candidate

    for base in (Path("/workspace"), Path("/app"), Path("/opt"), Path("/root")):
        if not base.exists():
            continue
        for package_name in ("hy3dshape", "hy3dgen"):
            for package_dir in base.rglob(package_name):
                return package_dir.parent

    root_summaries = []
    for base in (Path("/workspace"), Path("/app"), Path("/opt"), Path("/root")):
        if base.exists():
            names = ", ".join(sorted(path.name for path in base.iterdir())[:30])
            root_summaries.append(f"{base}: {names}")

    raise FileNotFoundError(
        "Could not find a Hunyuan3D checkout. Set HUNYUAN3D_ROOT or use a base image that includes hy3dshape. "
        + " | ".join(root_summaries)
    )


def generate_with_hunyuan(input_image: Path, output_path: Path, job_input: dict) -> Path:
    """Generate a GLB with Hunyuan3D.

    This function is intentionally isolated so the cloud Docker image can evolve
    without changing the MCP contract. The real implementation should import
    Hunyuan3D-2.1, run shape generation, optionally run Hunyuan3D-Paint, and
    export a Roblox-sized GLB.
    """
    if os.getenv("HUNYUAN_STUB_MODE", "0") == "1":
        output_path.write_text(
            json.dumps(
                {
                    "stub": True,
                    "input_image": str(input_image),
                    "job_input": {k: v for k, v in job_input.items() if k != "image_base64"},
                },
                indent=2,
            )
        )
        return output_path

    # Hunyuan3D 2.1 code usage from the official repo is:
    # - Hunyuan3DDiTFlowMatchingPipeline.from_pretrained("tencent/Hunyuan3D-2.1")
    # - Hunyuan3DPaintPipeline(...) for textured output.
    #
    # The imports are delayed because they only exist inside the CUDA worker
    # image after the Hunyuan repo and compiled rasterizer are installed.
    import sys

    hunyuan_api = "2.1"
    try:
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
    except ModuleNotFoundError:
        hunyuan_root = find_hunyuan_root()
        for import_path in (
            hunyuan_root,
            hunyuan_root / "hy3dshape",
            hunyuan_root / "hy3dpaint",
            hunyuan_root / "hy3dgen",
        ):
            sys.path.insert(0, str(import_path))

        if (hunyuan_root / "hy3dgen").exists():
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
            from hy3dgen.texgen import Hunyuan3DPaintPipeline

            hunyuan_api = "2.0"
        else:
            from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
            from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

    default_model_id = "tencent/Hunyuan3D-2" if hunyuan_api == "2.0" else "tencent/Hunyuan3D-2.1"
    model_id = job_input.get("model_id", os.getenv("HUNYUAN_MODEL_ID", default_model_id))
    shape_subfolder = job_input.get(
        "shape_subfolder",
        os.getenv("HUNYUAN_SHAPE_SUBFOLDER", "hunyuan3d-dit-v2-1"),
    )

    if hunyuan_api == "2.0":
        shape_pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model_id)
    else:
        shape_pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            model_id,
            subfolder=shape_subfolder,
        )

    mesh = shape_pipeline(image=str(input_image))[0]

    if hunyuan_api == "2.0":
        if job_input.get("textured", True):
            paint_pipeline = Hunyuan3DPaintPipeline.from_pretrained(model_id)
            mesh = paint_pipeline(mesh, image=str(input_image))
        mesh.export(str(output_path))
        return output_path

    untextured_path = output_path.with_suffix(".obj")
    mesh.export(str(untextured_path))
    if job_input.get("textured", True):
        paint_pipeline = Hunyuan3DPaintPipeline(
            Hunyuan3DPaintConfig(max_num_view=6, resolution=512)
        )
        textured_mesh = paint_pipeline(str(untextured_path), image_path=str(input_image))
        textured_mesh.export(str(output_path))
    else:
        mesh.export(str(output_path))

    return output_path


def handler(job):
    job_input = job.get("input") or {}
    asset_name = job_input.get("asset_name", "generated_asset")
    image_base64 = job_input.get("image_base64")

    if not image_base64:
        return {"error": "Missing input.image_base64"}

    input_image = write_input_image(image_base64, job_input.get("image_filename"))
    output_dir = Path("/tmp/hunyuan_outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{asset_name}.glb"

    generated_path = generate_with_hunyuan(input_image, output_path, job_input)
    encoded = base64.b64encode(generated_path.read_bytes()).decode("utf-8")

    return {
        "asset_name": asset_name,
        "textured": bool(job_input.get("textured", True)),
        "target_polycount": job_input.get("target_polycount"),
        "output_format": "glb",
        "glb_base64": encoded,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_input", help="Run one local handler test with a JSON payload.")
    args = parser.parse_args()

    if args.test_input:
        os.environ.setdefault("HUNYUAN_STUB_MODE", "1")
        print(json.dumps(handler(json.loads(args.test_input)), indent=2))
        return

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
