class OCREngine:
    def __init__(self):
        self._engine = None

    def _load(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as e:
                raise RuntimeError("RapidOCR is unavailable. Install requirements.txt or use the GitHub build.") from e
            self._engine = RapidOCR()

    def read(self, image):
        self._load()
        result, _ = self._engine(image)
        if not result:
            return "", []
        lines, structured = [], []
        for item in result:
            box, text, score = item
            text = str(text).strip()
            if text:
                lines.append(text)
                structured.append((box, text, float(score)))
        return "\n".join(lines), structured

    def read_many(self, rois):
        out = {}
        for name, image in rois.items():
            try:
                text, items = self.read(image)
            except Exception:
                text, items = "", []
            out[name] = (text, items)
        return out
