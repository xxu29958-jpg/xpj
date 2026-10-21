"""Bound every native CPU pool before imports allocate their thread buffers."""

import os

from ocr_runtime.protocol import OcrRuntimeError

PROCESS_ENVIRONMENT = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "OPENCV_OPENCL_RUNTIME": "disabled"}
WORKER_MEMORY_BYTES = 512 * 1024 * 1024


def configure_native_runtime(policy: dict) -> dict:
    if policy.get("opencl") is not False:
        raise OcrRuntimeError("ocr_session_options_mismatch")
    if any(os.environ.get(name) != value for name, value in PROCESS_ENVIRONMENT.items()):
        raise OcrRuntimeError("ocr_session_options_mismatch")
    import cv2
    import numpy
    from threadpoolctl import threadpool_info

    cv2.setNumThreads(policy["opencv_threads"])
    cv2.ocl.setUseOpenCL(False)
    pools = [{key: item[key] for key in ("user_api", "internal_api", "num_threads", "version")}
             for item in threadpool_info()]
    if (not pools or any(item["num_threads"] != policy["blas_threads"] for item in pools)
            or cv2.getNumThreads() != policy["opencv_threads"] or cv2.ocl.useOpenCL()):
        raise OcrRuntimeError("ocr_session_options_mismatch")
    return {"process_environment": PROCESS_ENVIRONMENT, "numpy_version": numpy.__version__,
            "opencv_threads": cv2.getNumThreads(),
            "opencv_opencl": False, "threadpools": pools}
