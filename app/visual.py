from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

import torch
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from qwen_vl_utils import process_vision_info
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

from app.config import Settings
from app.schemas import ClassificationResult, RunCreateRequest, RunImage, VisualReport

logger = logging.getLogger(__name__)

VISUAL_SYSTEM_PROMPT = """
You analyze user-uploaded images for a yes-or-no decision assistant.
Return a compact structured summary in Simplified Chinese.
Only extract visible facts that matter for the decision.
Do not guess hidden details.
If key details are missing, blurry, cropped, or unreadable, list them in uncertainties.
""".strip()

LOCAL_VISUAL_JSON_PROMPT = """
请把图片当作“是否要做/买/去”的证据来读。
只提取图里能直接看到、并且会影响判断的事实。
如果图片模糊、裁切、不完整，或者关键细节看不清，请写进 uncertainties。

请只输出一个 JSON 对象，不要输出 Markdown，不要补充解释。
JSON schema:
{
  "summary": "一句简洁总结",
  "extracted_facts": ["事实1", "事实2"],
  "uncertainties": ["不确定点1"],
  "image_count": 1
}
""".strip()


class VisualAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._dashscope_model: ChatOpenAI | None = None
        self._local_processor: AutoProcessor | None = None
        self._local_model: Qwen2_5_VLForConditionalGeneration | None = None
        self._local_lock = Lock()

    def analyze(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        images: list[RunImage],
    ) -> VisualReport:
        if not images:
            return VisualReport(summary="未收到图片证据。", image_count=0)

        config_issue = self.settings.visual_config_issue
        if config_issue is not None:
            return VisualReport(
                summary="已收到图片，但当前视觉模型配置不可用，我先不把图里的内容当作硬证据。",
                uncertainties=[config_issue],
                image_count=len(images),
            )

        if self.settings.vision_backend == "dashscope":
            return self._analyze_with_dashscope(payload, classification, images)
        return self._analyze_with_local_hf(payload, classification, images)

    def _analyze_with_dashscope(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        images: list[RunImage],
    ) -> VisualReport:
        model = self._require_dashscope_model()
        if model is None:
            return VisualReport(
                summary="已收到图片，但当前没有可用的视觉模型，这轮先把它们当作未解析附件处理。",
                uncertainties=["视觉模型未启用，图片内容尚未被解析。"],
                image_count=len(images),
            )

        try:
            prompt_blocks: list[dict[str, object]] = [
                {
                    "type": "text",
                    "text": (
                        "请先识别每张图片的大致类型，再抽取和当前决策最相关的事实。"
                        "输出要简洁，面向“这件事要不要做/买/去”。\n"
                        f"问题：{payload.question}\n"
                        f"分类：{classification.category}\n"
                        f"补充说明：{payload.notes or '无'}\n"
                        f"图片数量：{len(images)}"
                    ),
                }
            ]
            for image in images:
                prompt_blocks.append({"type": "text", "text": f"图片文件名：{image.file_name}"})
                prompt_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": encode_image_as_data_url(Path(image.local_path), image.mime_type)},
                    }
                )

            structured_model = model.with_structured_output(VisualReport)
            report = structured_model.invoke(
                [
                    SystemMessage(content=VISUAL_SYSTEM_PROMPT),
                    HumanMessage(content=prompt_blocks),
                ]
            )
            if report.image_count == 0:
                report.image_count = len(images)
            return report
        except Exception as exc:
            return VisualReport(
                summary="已收到图片，但这轮视觉分析没有稳定跑通，我先不把图里的内容当作硬证据。",
                uncertainties=[f"视觉分析失败：{exc}"],
                image_count=len(images),
            )

    def _analyze_with_local_hf(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        images: list[RunImage],
    ) -> VisualReport:
        components = self._require_local_components()
        if components is None:
            return VisualReport(
                summary="已收到图片，但本地视觉模型暂时不可用，我先不把图里的内容当作硬证据。",
                uncertainties=["本地视觉模型尚未就绪。"],
                image_count=len(images),
            )

        model, processor = components
        messages = self._build_local_messages(payload, classification, images)

        try:
            prompt_text = processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            image_inputs, video_inputs = process_vision_info(messages)
            model_inputs = processor(
                text=[prompt_text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
            model_inputs = self._move_inputs_to_model_device(model_inputs, model)

            with torch.inference_mode():
                generated_ids = model.generate(
                    **model_inputs,
                    max_new_tokens=self.settings.local_vision_max_new_tokens,
                    do_sample=False,
                )

            trimmed_ids = [
                output_ids[len(input_ids) :]
                for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids, strict=False)
            ]
            output_text = processor.batch_decode(
                trimmed_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
            return self._parse_local_response(output_text, len(images))
        except Exception as exc:
            logger.exception("Local vision inference failed", extra={"status": "error"})
            return VisualReport(
                summary="已收到图片，但本地视觉分析这轮没有稳定跑通，我先不把图里的内容当作硬证据。",
                uncertainties=[f"本地视觉分析失败：{exc}"],
                image_count=len(images),
            )

    def _require_dashscope_model(self) -> ChatOpenAI | None:
        if self._dashscope_model is not None:
            return self._dashscope_model
        if not self.settings.has_usable_dashscope_api_key:
            return None

        model_name = self.settings.vision_model_name or self.settings.model_name
        self._dashscope_model = ChatOpenAI(
            api_key=SecretStr(self.settings.dashscope_api_key),
            base_url=self.settings.dashscope_base_url,
            model=model_name,
            temperature=0.1,
            timeout=self.settings.model_timeout_seconds,
            max_retries=0,
        )
        return self._dashscope_model

    def _require_local_components(
        self,
    ) -> tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor] | None:
        if self._local_model is not None and self._local_processor is not None:
            return self._local_model, self._local_processor

        with self._local_lock:
            if self._local_model is not None and self._local_processor is not None:
                return self._local_model, self._local_processor

            model_dir = self.settings.local_vision_model_dir
            processor_kwargs: dict[str, Any] = {}
            if self.settings.local_vision_max_image_pixels > 0:
                processor_kwargs["max_pixels"] = self.settings.local_vision_max_image_pixels

            processor = AutoProcessor.from_pretrained(model_dir, **processor_kwargs)

            model_kwargs: dict[str, Any] = {
                "device_map": self._resolve_device_map(),
                "low_cpu_mem_usage": True,
                "attn_implementation": "sdpa",
            }

            use_4bit = self.settings.local_vision_load_in_4bit and torch.cuda.is_available()
            if use_4bit:
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=self._resolve_torch_dtype(),
                    bnb_4bit_use_double_quant=True,
                )
            else:
                model_kwargs["torch_dtype"] = self._resolve_torch_dtype()

            try:
                model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model_dir,
                    **model_kwargs,
                )
            except Exception:
                if not use_4bit:
                    raise
                logger.warning(
                    "4bit local vision load failed, retrying without quantization",
                    extra={"status": "retry"},
                    exc_info=True,
                )
                model_kwargs.pop("quantization_config", None)
                model_kwargs["torch_dtype"] = self._resolve_torch_dtype()
                model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model_dir,
                    **model_kwargs,
                )
            model.eval()

            self._local_model = model
            self._local_processor = processor
            return model, processor

    def _resolve_torch_dtype(self) -> torch.dtype:
        dtype_name = self.settings.local_vision_dtype.lower().strip()
        if dtype_name == "bfloat16":
            return torch.bfloat16
        if dtype_name == "float32":
            return torch.float32
        return torch.float16

    def _resolve_device_map(self) -> Any:
        device = self.settings.local_vision_device.strip().lower()
        if not device or device == "auto":
            return "auto"
        if device == "cpu":
            return "cpu"
        if device == "cuda":
            return {"": "cuda:0"}
        if device.startswith("cuda:"):
            return {"": device}
        return "auto"

    def _build_local_messages(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        images: list[RunImage],
    ) -> list[dict[str, Any]]:
        image_blocks: list[dict[str, Any]] = []
        for image in images:
            image_blocks.append(
                {
                    "type": "image",
                    "image": Path(image.local_path).resolve().as_posix(),
                    "max_pixels": self.settings.local_vision_max_image_pixels,
                }
            )

        question_block = {
            "type": "text",
            "text": (
                f"{LOCAL_VISUAL_JSON_PROMPT}\n\n"
                f"问题：{payload.question}\n"
                f"分类：{classification.category}\n"
                f"补充说明：{payload.notes or '无'}\n"
                f"图片文件：{', '.join(image.file_name for image in images)}\n"
                f"图片数量：{len(images)}"
            ),
        }
        return [
            {"role": "system", "content": [{"type": "text", "text": VISUAL_SYSTEM_PROMPT}]},
            {"role": "user", "content": [*image_blocks, question_block]},
        ]

    def _move_inputs_to_model_device(
        self,
        model_inputs: Any,
        model: Qwen2_5_VLForConditionalGeneration,
    ) -> Any:
        target_device = getattr(model, "device", None)
        if target_device is None or str(target_device) == "meta":
            target_device = next(model.parameters()).device
        return model_inputs.to(target_device)

    def _parse_local_response(self, text: str, image_count: int) -> VisualReport:
        payload = _extract_json_payload(text)
        if payload is None:
            summary = _shorten_text(text.strip() or "图片已分析，但模型没有返回可解析的结构化结果。", 220)
            return VisualReport(
                summary=summary,
                uncertainties=["本地视觉模型输出未能解析成 JSON。"],
                image_count=image_count,
            )

        if "image_count" not in payload:
            payload["image_count"] = image_count
        try:
            report = VisualReport.model_validate(payload)
        except Exception as exc:
            return VisualReport(
                summary="图片已分析，但结构化结果字段不完整，我先按弱证据处理。",
                uncertainties=[f"本地视觉结果校验失败：{exc}"],
                image_count=image_count,
            )
        if report.image_count == 0:
            report.image_count = image_count
        return report


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "").strip()

    for candidate in (cleaned, _extract_first_json_object(cleaned)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _shorten_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(limit - 15, 0)]}...[truncated]"


def visual_report_status(report: VisualReport) -> str:
    if report.uncertainties and not report.extracted_facts:
        return "degraded"
    return "ok"


def encode_image_as_data_url(path: Path, mime_type: str) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"
