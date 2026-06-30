import base64
import argparse
import inspect
import json
import os
import tempfile
import time
from pathlib import Path

from PIL import Image

try:
    import runpod
except ModuleNotFoundError:
    runpod = None


def write_input_image(image_base64: str, image_filename: str | None) -> Path:
    suffix = Path(image_filename or "input.png").suffix or ".png"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.write(base64.b64decode(image_base64))
    handle.close()
    return Path(handle.name)


def write_view_images(job_input: dict) -> dict[str, Path]:
    view_images = job_input.get("view_images_base64") or {}
    view_filenames = job_input.get("view_image_filenames") or {}
    if not isinstance(view_images, dict):
        return {}

    written: dict[str, Path] = {}
    for view_name, encoded in view_images.items():
        if not encoded:
            continue
        safe_view_name = str(view_name).strip().lower()
        if not safe_view_name:
            continue
        filename = view_filenames.get(view_name) or view_filenames.get(safe_view_name) or f"{safe_view_name}.png"
        written[safe_view_name] = write_input_image(str(encoded), filename)
    return written


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


def simplify_mesh(mesh, target_polycount):
    try:
        target_faces = int(target_polycount or 0)
    except (TypeError, ValueError):
        target_faces = 0

    faces = getattr(mesh, "faces", None)
    current_faces = len(faces) if faces is not None else 0
    if target_faces <= 0 or current_faces <= target_faces:
        if current_faces:
            print(f"space3d: mesh faces={current_faces}; no simplification needed", flush=True)
        return mesh

    print(f"space3d: simplifying mesh faces {current_faces} -> {target_faces}", flush=True)
    for method_name in ("simplify_quadric_decimation", "simplify_quadratic_decimation"):
        simplify = getattr(mesh, method_name, None)
        if not simplify:
            continue
        try:
            simplified = simplify(face_count=target_faces)
        except TypeError:
            simplified = simplify(target_faces)
        simplified_faces = getattr(simplified, "faces", None)
        if simplified_faces is not None:
            print(f"space3d: simplified mesh faces={len(simplified_faces)}", flush=True)
        return simplified

    print("space3d: mesh simplification unavailable; exporting raw mesh", flush=True)
    return mesh


def load_rgba_image(image_path: Path):
    image = Image.open(image_path).convert("RGBA")
    print(f"space3d: loaded input image size={image.size} mode={image.mode}", flush=True)
    return image


def number_input(job_input: dict, keys, fallback, cast):
    if isinstance(keys, str):
        keys = [keys]
    for key in keys:
        value = job_input.get(key)
        if value is None or value == "":
            continue
        try:
            return cast(value)
        except (TypeError, ValueError):
            print(f"space3d: ignoring invalid numeric option {key}={value!r}", flush=True)
    env_key = None
    if isinstance(keys, list) and keys:
        env_key = f"HUNYUAN_{str(keys[0]).upper()}"
    if env_key:
        value = os.getenv(env_key)
        if value:
            try:
                return cast(value)
            except (TypeError, ValueError):
                print(f"space3d: ignoring invalid env option {env_key}={value!r}", flush=True)
    return fallback


def is_multiview_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return "2mv" in lowered or "-mv" in lowered or "multiview" in lowered


def build_shape_condition(input_image: Path, view_images: dict[str, Path], model_id: str, hunyuan_api: str):
    if view_images and is_multiview_model(model_id):
        views = dict(view_images)
        views.setdefault("front", input_image)
        ordered = {key: str(views[key]) for key in ("front", "left", "back") if key in views}
        for key in sorted(views):
            ordered.setdefault(key, str(views[key]))
        print(f"space3d: using multiview shape inputs={list(ordered)}", flush=True)
        return ordered

    if view_images:
        print("space3d: view images were provided but selected shape model is not multiview; using main image", flush=True)
    return load_rgba_image(input_image) if hunyuan_api == "2.0" else str(input_image)


def build_shape_kwargs(job_input: dict) -> dict:
    kwargs = {
        "num_inference_steps": number_input(job_input, ["shape_num_inference_steps", "num_inference_steps"], 50, int),
        "guidance_scale": number_input(job_input, ["shape_guidance_scale", "guidance_scale"], 5.0, float),
        "octree_resolution": number_input(job_input, "octree_resolution", 384, int),
        "num_chunks": number_input(job_input, "num_chunks", 20000, int),
    }

    seed = job_input.get("seed")
    if seed is not None and seed != "":
        try:
            import torch

            kwargs["generator"] = torch.manual_seed(int(seed))
        except Exception as exc:
            print(f"space3d: could not set seed={seed!r}: {exc}", flush=True)

    return kwargs


def supported_kwargs(callable_obj, kwargs: dict) -> dict:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return kwargs

    params = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in params}


def call_shape_pipeline(shape_pipeline, image, shape_kwargs: dict):
    kwargs = supported_kwargs(shape_pipeline.__call__, shape_kwargs)
    dropped = sorted(set(shape_kwargs) - set(kwargs))
    if dropped:
        print(f"space3d: shape pipeline does not expose options={dropped}; dropping them", flush=True)
    print(f"space3d: shape options={{{', '.join(f'{k}={v}' for k, v in kwargs.items() if k != 'generator')}}}", flush=True)
    return shape_pipeline(image=image, **kwargs)[0]


def configure_legacy_paint_pipeline(paint_pipeline, job_input: dict):
    """Tune Hunyuan3D 2.0 texture generation for small game assets."""
    config = getattr(paint_pipeline, "config", None)
    render = getattr(paint_pipeline, "render", None)
    if not config or not render:
        return paint_pipeline

    resolution = number_input(job_input, "texture_resolution", 512, int)
    num_views = number_input(job_input, "texture_num_views", 6, int)

    if resolution > 0:
        config.render_size = resolution
        config.texture_size = resolution
        try:
            paint_pipeline.render = render.__class__(
                default_resolution=config.render_size,
                texture_size=config.texture_size,
            )
            print(f"space3d: configured texture resolution={resolution}", flush=True)
        except Exception as exc:
            print(f"space3d: could not resize texture renderer: {exc}", flush=True)

    if 0 < num_views < len(config.candidate_camera_azims):
        config.candidate_camera_azims = config.candidate_camera_azims[:num_views]
        config.candidate_camera_elevs = config.candidate_camera_elevs[:num_views]
        config.candidate_view_weights = config.candidate_view_weights[:num_views]
        print(f"space3d: configured texture views={num_views}", flush=True)

    return paint_pipeline


def timed(label: str, fn):
    started = time.monotonic()
    try:
        return fn()
    finally:
        elapsed = time.monotonic() - started
        print(f"space3d: {label} seconds={elapsed:.1f}", flush=True)


def generate_with_hunyuan(input_image: Path, output_path: Path, job_input: dict, view_images: dict[str, Path] | None = None) -> Path:
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

    requested_model_id = job_input.get("model_id") or os.getenv("HUNYUAN_MODEL_ID", "")
    prefer_legacy_api = is_multiview_model(str(requested_model_id))
    hunyuan_api = "2.1"
    try:
        if prefer_legacy_api:
            raise ModuleNotFoundError("Hunyuan3D-2mv uses the hy3dgen multiview API")
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

        if prefer_legacy_api and not (hunyuan_root / "hy3dgen").exists():
            raise ModuleNotFoundError(
                "Selected a multiview Hunyuan3D model, but the worker image does not include hy3dgen. "
                "Use a Hunyuan3D-2/2mv worker image or install hy3dgen."
            )

        if (hunyuan_root / "hy3dgen").exists():
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
            from hy3dgen.texgen import Hunyuan3DPaintPipeline

            hunyuan_api = "2.0"
        else:
            from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
            from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

    view_images = view_images or {}
    default_model_id = "tencent/Hunyuan3D-2" if hunyuan_api == "2.0" else "tencent/Hunyuan3D-2.1"
    model_id = job_input.get("model_id", os.getenv("HUNYUAN_MODEL_ID", default_model_id))
    default_texture_model_id = "tencent/Hunyuan3D-2" if hunyuan_api == "2.0" else model_id
    texture_model_id = job_input.get(
        "texture_model_id",
        os.getenv("HUNYUAN_TEXTURE_MODEL_ID", default_texture_model_id),
    )
    default_shape_subfolder = "hunyuan3d-dit-v2-1" if hunyuan_api == "2.1" else None
    if is_multiview_model(model_id):
        default_shape_subfolder = "hunyuan3d-dit-v2-mv"
    shape_subfolder = job_input.get("shape_subfolder") or os.getenv("HUNYUAN_SHAPE_SUBFOLDER") or default_shape_subfolder

    print(f"space3d: loading shape pipeline api={hunyuan_api} model={model_id} subfolder={shape_subfolder}", flush=True)

    def load_shape_pipeline():
        kwargs = {"subfolder": shape_subfolder} if shape_subfolder else {}
        try:
            return Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model_id, **kwargs)
        except TypeError:
            print("space3d: shape pipeline loader rejected subfolder kwarg; retrying with model id only", flush=True)
            return Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model_id)

    if hunyuan_api == "2.0":
        shape_pipeline = timed(
            "shape pipeline load",
            load_shape_pipeline,
        )
    else:
        shape_pipeline = timed(
            "shape pipeline load",
            load_shape_pipeline,
        )

    print("space3d: running shape generation", flush=True)
    source_image = load_rgba_image(input_image)
    shape_image = build_shape_condition(input_image, view_images, model_id, hunyuan_api)
    shape_kwargs = build_shape_kwargs(job_input)
    mesh = timed("shape generation", lambda: call_shape_pipeline(shape_pipeline, shape_image, shape_kwargs))
    print("space3d: shape generation complete", flush=True)
    mesh = simplify_mesh(mesh, job_input.get("target_polycount"))

    if hunyuan_api == "2.0":
        if job_input.get("textured", True):
            print(f"space3d: loading texture pipeline model={texture_model_id}", flush=True)
            paint_pipeline = timed(
                "texture pipeline load",
                lambda: Hunyuan3DPaintPipeline.from_pretrained(texture_model_id),
            )
            paint_pipeline = configure_legacy_paint_pipeline(paint_pipeline, job_input)
            print("space3d: running texture generation", flush=True)
            mesh = timed("texture generation", lambda: paint_pipeline(mesh, image=source_image))
            print("space3d: texture generation complete", flush=True)
        print(f"space3d: exporting {output_path}", flush=True)
        mesh.export(str(output_path))
        return output_path

    untextured_path = output_path.with_suffix(".obj")
    mesh.export(str(untextured_path))
    if job_input.get("textured", True):
        print("space3d: loading texture pipeline", flush=True)
        texture_resolution = number_input(job_input, "texture_resolution", 512, int)
        texture_num_views = number_input(job_input, "texture_num_views", 6, int)
        paint_pipeline = Hunyuan3DPaintPipeline(
            Hunyuan3DPaintConfig(max_num_view=texture_num_views, resolution=texture_resolution)
        )
        print(f"space3d: configured texture resolution={texture_resolution} views={texture_num_views}", flush=True)
        print("space3d: running texture generation", flush=True)
        textured_mesh = paint_pipeline(str(untextured_path), image_path=str(input_image))
        print("space3d: texture generation complete", flush=True)
        textured_mesh.export(str(output_path))
    else:
        print(f"space3d: exporting {output_path}", flush=True)
        mesh.export(str(output_path))

    return output_path


def handler(job):
    job_input = job.get("input") or {}
    asset_name = job_input.get("asset_name", "generated_asset")
    image_base64 = job_input.get("image_base64")

    if not image_base64:
        return {"error": "Missing input.image_base64"}

    input_image = write_input_image(image_base64, job_input.get("image_filename"))
    view_images = write_view_images(job_input)
    output_dir = Path("/tmp/hunyuan_outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{asset_name}.glb"

    generated_path = generate_with_hunyuan(input_image, output_path, job_input, view_images)
    encoded = base64.b64encode(generated_path.read_bytes()).decode("utf-8")

    return {
        "asset_name": asset_name,
        "textured": bool(job_input.get("textured", True)),
        "target_polycount": job_input.get("target_polycount"),
        "model_id": job_input.get("model_id"),
        "texture_model_id": job_input.get("texture_model_id"),
        "shape_subfolder": job_input.get("shape_subfolder"),
        "shape_num_inference_steps": job_input.get("shape_num_inference_steps", job_input.get("num_inference_steps")),
        "shape_guidance_scale": job_input.get("shape_guidance_scale", job_input.get("guidance_scale")),
        "octree_resolution": job_input.get("octree_resolution"),
        "num_chunks": job_input.get("num_chunks"),
        "view_images": sorted(view_images.keys()),
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

    if runpod is None:
        raise ModuleNotFoundError("runpod is required when starting the serverless worker.")
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
