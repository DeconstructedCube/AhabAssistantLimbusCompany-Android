"""Android-native OCR backend (MaaFramework C++ JOCR + pure ONNX PP-OCRv4 fallback)."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from cv2 import createCLAHE
from PIL import Image


@dataclass
class AndroidOCROutput:
    img: Any = None
    boxes: list = field(default_factory=list)
    txts: tuple | list = field(default_factory=tuple)
    scores: tuple | list = field(default_factory=tuple)
    word_results: tuple = field(default_factory=tuple)
    elapse_list: list = field(default_factory=list)
    elapse: float = 0.0
    lang_rec: str | None = None


class PureOnnxPPOCRv4:
    """Native OpenCV + ONNX Runtime PP-OCRv4 engine without shapely/pyclipper dependencies."""

    def __init__(self, det_path: str, rec_path: str, keys_path: str, num_threads: int = 4):
        import onnxruntime as ort

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = num_threads
        sess_opts.inter_op_num_threads = 2
        sess_opts.enable_cpu_mem_arena = False
        avail = ort.get_available_providers()
        providers: list[Any] = []
        if "XnnpackExecutionProvider" in avail:
            providers.append(("XnnpackExecutionProvider", {"intra_op_num_threads": str(num_threads)}))
        providers.append("CPUExecutionProvider")

        self.det_sess = ort.InferenceSession(det_path, sess_options=sess_opts, providers=providers)
        self.rec_sess = ort.InferenceSession(rec_path, sess_options=sess_opts, providers=providers)
        self.det_in = self.det_sess.get_inputs()[0].name
        self.rec_in = self.rec_sess.get_inputs()[0].name

        with open(keys_path, "r", encoding="utf-8") as f:
            raw_keys = [line.strip("\r\n") for line in f]
        self.char_dict = ["blank"] + raw_keys + [" "]

        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)

    def _preprocess_det(self, img_bgr: np.ndarray, limit_side_len: int = 736):
        h, w = img_bgr.shape[:2]
        min_side = min(h, w)
        if min_side < 64:
            ratio = max(1.0, 64.0 / max(min_side, 1))
        elif min_side > limit_side_len:
            ratio = float(limit_side_len) / min_side
        else:
            ratio = 1.0
        resize_h = max(32, int(round(h * ratio / 32) * 32))
        resize_w = max(32, int(round(w * ratio / 32) * 32))
        resized = cv2.resize(img_bgr, (resize_w, resize_h))
        norm = (resized.astype(np.float32) / 255.0 - self.mean) / self.std
        tensor = norm.transpose(2, 0, 1)[None, ...]
        return tensor, (h / float(resize_h), w / float(resize_w))

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        x_sorted = pts[np.argsort(pts[:, 0]), :]
        left_most = x_sorted[:2, :]
        right_most = x_sorted[2:, :]
        left_most = left_most[np.argsort(left_most[:, 1]), :]
        (tl, bl) = left_most
        right_most = right_most[np.argsort(right_most[:, 1]), :]
        (tr, br) = right_most
        return np.array([tl, tr, br, bl], dtype=np.float32)

    @staticmethod
    def _box_score_fast(bitmap: np.ndarray, box: np.ndarray) -> float:
        h, w = bitmap.shape[:2]
        box_copy = box.copy()
        xmin = int(np.clip(np.floor(box_copy[:, 0].min()), 0, w - 1))
        xmax = int(np.clip(np.ceil(box_copy[:, 0].max()), 0, w - 1))
        ymin = int(np.clip(np.floor(box_copy[:, 1].min()), 0, h - 1))
        ymax = int(np.clip(np.ceil(box_copy[:, 1].max()), 0, h - 1))
        mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
        box_copy[:, 0] -= xmin
        box_copy[:, 1] -= ymin
        cv2.fillPoly(mask, box_copy.reshape(1, -1, 2).astype(np.int32), 1)
        return float(cv2.mean(bitmap[ymin : ymax + 1, xmin : xmax + 1], mask)[0])

    @staticmethod
    def _get_rotate_crop_image(img: np.ndarray, points: np.ndarray) -> np.ndarray:
        crop_w = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
        crop_h = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
        crop_w = max(crop_w, 1)
        crop_h = max(crop_h, 1)
        pts_std = np.array([[0, 0], [crop_w, 0], [crop_w, crop_h], [0, crop_h]], dtype=np.float32)
        M = cv2.getPerspectiveTransform(points, pts_std)
        dst = cv2.warpPerspective(img, M, (crop_w, crop_h), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
        if dst.shape[0] * 1.0 / dst.shape[1] >= 1.5:
            dst = np.rot90(dst)
        return dst

    def _recognize_crops(self, crops: list[np.ndarray]) -> tuple[list[str], list[float]]:
        if not crops:
            return [], []
        txts = []
        scores = []
        for crop in crops:
            h, w = crop.shape[:2]
            ratio = w / float(max(h, 1))
            resized_w = max(16, int(np.ceil(48 * ratio)))
            resized = cv2.resize(crop, (resized_w, 48))
            norm = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
            pad_w = max(320, resized_w)
            padded = np.zeros((48, pad_w, 3), dtype=np.float32)
            padded[:, :resized_w, :] = norm
            inp = padded.transpose(2, 0, 1)[None, ...]
            preds = self.rec_sess.run(None, {self.rec_in: inp})[0][0]
            pred_idxs = preds.argmax(axis=-1)
            pred_probs = preds.max(axis=-1)
            chars = []
            char_probs = []
            prev = 0
            for idx, prob in zip(pred_idxs, pred_probs):
                if idx != 0 and idx != prev and idx < len(self.char_dict):
                    chars.append(self.char_dict[idx])
                    char_probs.append(float(prob))
                prev = idx
            txt = "".join(chars)
            score = float(np.mean(char_probs)) if char_probs else 0.0
            txts.append(txt)
            scores.append(score)
        return txts, scores

    def __call__(
        self,
        img: np.ndarray,
        thresh: float = 0.3,
        box_thresh: float = 0.5,
        unclip_ratio: float = 1.6,
    ) -> AndroidOCROutput:
        img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img[:, :, :3]
        orig_h, orig_w = img_bgr.shape[:2]
        tensor, (scale_h, scale_w) = self._preprocess_det(img_bgr)
        pred = self.det_sess.run(None, {self.det_in: tensor})[0][0, 0]
        segmentation = (pred > thresh).astype(np.uint8)
        contours, _ = cv2.findContours(segmentation, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        boxes = []
        for cnt in contours[:1000]:
            if len(cnt) < 4:
                continue
            rect = cv2.minAreaRect(cnt)
            (cx, cy), (rw, rh), angle = rect
            if min(rw, rh) < 3:
                continue
            pts = self._order_points(cv2.boxPoints(rect))
            if self._box_score_fast(pred, pts) < box_thresh:
                continue
            area = rw * rh
            length = 2.0 * (rw + rh)
            d = area * unclip_ratio / length
            unclip_rect = ((cx, cy), (rw + 2.0 * d, rh + 2.0 * d), angle)
            unclip_pts = self._order_points(cv2.boxPoints(unclip_rect))
            unclip_pts[:, 0] = np.clip(np.round(unclip_pts[:, 0] * scale_w), 0, orig_w)
            unclip_pts[:, 1] = np.clip(np.round(unclip_pts[:, 1] * scale_h), 0, orig_h)
            w_final = int(np.linalg.norm(unclip_pts[0] - unclip_pts[1]))
            h_final = int(np.linalg.norm(unclip_pts[0] - unclip_pts[3]))
            if w_final <= 3 or h_final <= 3:
                continue
            boxes.append(unclip_pts)

        if not boxes:
            if orig_h <= 150 and orig_w <= 450:
                txts, scores = self._recognize_crops([img_bgr])
                if txts and txts[0] and scores[0] >= 0.45:
                    full_box = [[0.0, 0.0], [float(orig_w), 0.0], [float(orig_w), float(orig_h)], [0.0, float(orig_h)]]
                    return AndroidOCROutput(boxes=[full_box], txts=tuple(txts), scores=tuple(scores))
            return AndroidOCROutput()

        boxes = sorted(boxes, key=lambda x: (x[0][1], x[0][0]))
        for i in range(len(boxes) - 1):
            for j in range(i, -1, -1):
                if abs(boxes[j + 1][0][1] - boxes[j][0][1]) < 10 and (boxes[j + 1][0][0] < boxes[j][0][0]):
                    boxes[j], boxes[j + 1] = boxes[j + 1], boxes[j]
                else:
                    break

        crops = [self._get_rotate_crop_image(img_bgr, b) for b in boxes]
        txts, scores = self._recognize_crops(crops)

        final_boxes, final_txts, final_scores = [], [], []
        for b, t, s in zip(boxes, txts, scores):
            if t and s >= 0.5:
                final_boxes.append(b.tolist())
                final_txts.append(t)
                final_scores.append(s)
        return AndroidOCROutput(boxes=final_boxes, txts=tuple(final_txts), scores=tuple(final_scores))


class AndroidOCRAdapter:
    """Replaces OCR.run when running inside Android APK / Termux without desktop RapidOCR."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._pure_onnx_engine: PureOnnxPPOCRv4 | None = None
        self._initialized = False

    def _ensure_local_engine(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        for d in (Path("resource/base/model/ocr"), Path("model/ocr"), Path("assets/model/ocr")):
            det_p, rec_p, keys_p = d / "det.onnx", d / "rec.onnx", d / "keys.txt"
            if det_p.exists() and rec_p.exists() and keys_p.exists():
                try:
                    self._pure_onnx_engine = PureOnnxPPOCRv4(str(det_p), str(rec_p), str(keys_p))
                    self.logger.debug(f"已加载原生 ONNX PP-OCRv4 引擎: {d}")
                    return
                except Exception as e:
                    self.logger.warning(f"加载原生 ONNX PP-OCRv4 引擎失败 ({d}): {e}")

    def _run_via_maa_context(self, processed_gray: np.ndarray) -> AndroidOCROutput | None:
        from module.automation.input_handlers.maa_control import MaaControl

        dev = MaaControl.connection_device
        if dev is None or dev.maa_context is None:
            return None
        try:
            bgr_img = cv2.cvtColor(processed_gray, cv2.COLOR_GRAY2BGR)
            items = dev.run_ocr_direct(bgr_img, only_rec=False)
            boxes, txts, scores = [], [], []
            if items:
                for txt, score, rect in items:
                    if txt and rect is not None:
                        x, y, w, h = float(rect.x), float(rect.y), float(rect.w), float(rect.h)
                        boxes.append([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
                        txts.append(txt)
                        scores.append(float(score))
            elif processed_gray.shape[0] <= 150 and processed_gray.shape[1] <= 450:
                items_rec = dev.run_ocr_direct(bgr_img, only_rec=True)
                if items_rec:
                    oh, ow = float(processed_gray.shape[0]), float(processed_gray.shape[1])
                    for txt, score, _ in items_rec:
                        if txt:
                            boxes.append([[0.0, 0.0], [ow, 0.0], [ow, oh], [0.0, oh]])
                            txts.append(txt)
                            scores.append(float(score))
            return AndroidOCROutput(boxes=boxes, txts=tuple(txts), scores=tuple(scores))
        except Exception as e:
            self.logger.debug(f"MaaFramework C++ OCR 调用回退本地 ONNX OCR: {e}")
            return None

    def run(self, image: Image.Image | np.ndarray | str) -> AndroidOCROutput:
        try:
            if isinstance(image, str):
                with Image.open(image) as image_file:
                    image_array = np.array(image_file)
            elif isinstance(image, Image.Image):
                image_array = np.array(image)
            elif isinstance(image, np.ndarray):
                image_array = image
            else:
                image_array = np.array(image)

            if image_array.ndim == 2:
                img_cv_gray = image_array
            elif image_array.ndim == 3:
                c = image_array.shape[2]
                if c == 1:
                    img_cv_gray = image_array[:, :, 0]
                elif c == 3:
                    img_cv_gray = cv2.cvtColor(cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2GRAY)
                elif c == 4:
                    img_cv_gray = cv2.cvtColor(cv2.cvtColor(image_array, cv2.COLOR_RGBA2BGR), cv2.COLOR_BGR2GRAY)
                else:
                    raise ValueError(f"不支持的图像通道数: {c}")
            else:
                raise ValueError(f"不支持的图像维度: {image_array.ndim}")

            clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            processed = clahe.apply(img_cv_gray)

            maa_res = self._run_via_maa_context(processed)
            if maa_res is not None and maa_res.txts:
                self.logger.debug(f"OCR识别结果：{maa_res.txts}")
                return maa_res

            self._ensure_local_engine()
            if self._pure_onnx_engine is not None:
                res = self._pure_onnx_engine(processed)
                self.logger.debug(f"OCR识别结果：{res.txts}")
                return res
            return AndroidOCROutput()
        except Exception as e:
            self.logger.error(e)
            return AndroidOCROutput()


def install_android_ocr() -> None:
    """Attach AndroidOCRAdapter onto module.ocr.ocr singleton when RapidOCR is unavailable or on Android."""
    from module.ocr import ocr

    adapter = AndroidOCRAdapter(ocr.logger)
    ocr.run = adapter.run
