"""
Khớp SẢN PHẨM bằng ẢNH theo NGỮ NGHĨA hình ảnh (CLIP) — bản nâng cấp của pHash.

Khác pHash: pHash chỉ báo "trùng" khi advertiser dùng lại ĐÚNG tấm ảnh (gần như từng pixel).
CLIP nhúng ảnh vào không gian ngữ nghĩa nên bắt được "CÙNG sản phẩm dù khác góc chụp / nền /
người mẫu" — đúng nhu cầu "tìm video quảng cáo về sản phẩm này". Đánh đổi: cần model (nặng hơn).

Không thêm dependency pip: chạy CLIP image-encoder (ViT-B/32) qua onnxruntime + numpy + Pillow
(đều đã có). CHỈ cần encoder ẢNH (so ảnh↔ảnh) nên không đụng tới text encoder/tokenizer.

Model: `backend/models/clip-vision.onnx` (Qdrant/clip-ViT-B-32-vision, ~350MB, tải runtime, không
commit — xem .gitignore). Thiếu file này thì `clip_available()` trả False và route rơi về pHash.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
from PIL import Image
import io

from .imagematch import _poster_of, fetch_image_bytes
from .types import Ad

#: Ngưỡng cosine tối thiểu để coi là "liên quan sản phẩm". Đo thực tế trên ảnh sàn: đồ KHÁC HẲN
#: (áo khoác vs đèn LED) ~0.34-0.41; đồ CÙNG NHÓM khác mẫu ~0.62-0.77; cùng sản phẩm khác ảnh
#: thường ≥0.8. 0.65 để video CÙNG NHÓM HÀNG (video áo khoác cho sản phẩm áo khoác) nổi lên làm
#: tham khảo, mà vẫn loại sạch đồ khác hẳn. Người dùng thấy điểm + poster nên tự phán. Muốn chỉ
#: lấy đúng-cùng-sản-phẩm thì nâng `minSim` lên ~0.8.
DEFAULT_MIN_SIM = 0.65

_MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "clip-vision.onnx"

#: Tiền xử lý chuẩn của CLIP (đúng preprocessor của Qdrant/clip-ViT-B-32-vision).
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_SIZE = 224

_session = None
_in_name = None
_out_name = None


def clip_available() -> bool:
    return _MODEL_PATH.is_file()


def _get_session():
    """Nạp onnx session một lần (chậm ~1-2s lần đầu), tái dùng cho cả tiến trình."""
    global _session, _in_name, _out_name
    if _session is None:
        import onnxruntime as ort

        _session = ort.InferenceSession(str(_MODEL_PATH), providers=["CPUExecutionProvider"])
        _in_name = _session.get_inputs()[0].name
        _out_name = _session.get_outputs()[0].name
    return _session


def _preprocess(image_bytes: bytes) -> np.ndarray | None:
    """Ảnh (bytes) → tensor (3,224,224) float32 theo chuẩn CLIP, hoặc None nếu hỏng."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    # Resize cạnh ngắn về 224 (bicubic) rồi center-crop 224 — đúng quy trình CLIP.
    w, h = img.size
    scale = _SIZE / min(w, h)
    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BICUBIC)
    w, h = img.size
    left, top = (w - _SIZE) // 2, (h - _SIZE) // 2
    img = img.crop((left, top, left + _SIZE, top + _SIZE))
    arr = (np.asarray(img, dtype=np.float32) / 255.0 - _MEAN) / _STD
    return arr.transpose(2, 0, 1)  # HWC → CHW


def _embed(batch: np.ndarray) -> np.ndarray:
    """(N,3,224,224) → (N,512) đã chuẩn hoá L2 để dot product = cosine."""
    session = _get_session()
    vecs = session.run([_out_name], {_in_name: batch})[0]
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-8, None)


async def match_ads_by_image_clip(
    source_image: str, ads: list[Ad], min_sim: float = DEFAULT_MIN_SIM
) -> tuple[list[Ad], str | None]:
    """
    Giữ lại quảng cáo có poster CÙNG sản phẩm với ảnh nguồn (cosine ≥ `min_sim`), xếp giảm dần.

    Mỗi ad gắn `match_score` 0-100 = cosine×100. Trả (ads, notice) — notice mô tả khi không
    đọc được ảnh nguồn, để giao diện không im lặng. Toàn bộ tải ảnh chạy song song; phần
    encode CLIP (nặng CPU) gộp một mẻ và đẩy sang thread để không chẹn event loop.
    """
    src_bytes = await fetch_image_bytes(source_image)
    if src_bytes is None:
        return [], "Không tải được ảnh sản phẩm để so khớp — thử sản phẩm khác."

    posters = [_poster_of(ad) for ad in ads]
    datas = await asyncio.gather(*(fetch_image_bytes(p) if p else _none() for p in posters))

    def work() -> tuple[bool, list[tuple[int, float]]]:
        src = _preprocess(src_bytes)
        if src is None:
            return False, []
        batch = [src]
        idx: list[int] = []
        for i, data in enumerate(datas):
            if not data:
                continue
            arr = _preprocess(data)
            if arr is None:
                continue
            batch.append(arr)
            idx.append(i)
        if not idx:
            return True, []
        embeds = _embed(np.stack(batch, axis=0))
        src_vec = embeds[0]
        return True, [(idx[k], float(np.dot(src_vec, embeds[k + 1]))) for k in range(len(idx))]

    ok, sims = await asyncio.to_thread(work)
    if not ok:
        return [], "Không giải mã được ảnh sản phẩm để so khớp — thử sản phẩm khác."

    matched = [
        ads[i].model_copy(update={"match_score": round(sim * 100)})
        for i, sim in sims
        if sim >= min_sim
    ]
    matched.sort(key=lambda ad: ad.match_score or 0, reverse=True)
    return matched, None


async def _none() -> None:
    """gather() cần awaitable cho ô poster rỗng — trả None gọn gàng."""
    return None
