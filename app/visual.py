from __future__ import annotations

import base64
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config import Settings
from app.schemas import ClassificationResult, RunCreateRequest, RunImage, VisualReport

VISUAL_SYSTEM_PROMPT = """
You analyze user-uploaded images for a yes-or-no decision assistant.
Return a compact structured summary in Simplified Chinese.
Only extract visible facts that matter for the decision.
Do not guess hidden details.
If key details are missing, blurry, cropped, or unreadable, list them in uncertainties.
""".strip()


class VisualAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: ChatOpenAI | None = None

    def analyze(
        self,
        payload: RunCreateRequest,
        classification: ClassificationResult,
        images: list[RunImage],
    ) -> VisualReport:
        if not images:
            return VisualReport(summary="未收到图片证据。", image_count=0)

        config_issue = self.settings.dashscope_config_issue
        if config_issue is not None:
            return VisualReport(
                summary="已收到图片，但当前视觉模型配置不可用，我先不把图里的内容当作硬证据。",
                uncertainties=[config_issue],
                image_count=len(images),
            )

        model = self._require_model()
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

    def _require_model(self) -> ChatOpenAI | None:
        if self._model is not None:
            return self._model
        if not self.settings.has_usable_dashscope_api_key:
            return None

        model_name = self.settings.vision_model_name or self.settings.model_name
        self._model = ChatOpenAI(
            api_key=SecretStr(self.settings.dashscope_api_key),
            base_url=self.settings.dashscope_base_url,
            model=model_name,
            temperature=0.1,
            timeout=self.settings.model_timeout_seconds,
            max_retries=0,
        )
        return self._model


def visual_report_status(report: VisualReport) -> str:
    if report.uncertainties and not report.extracted_facts:
        return "degraded"
    return "ok"


def encode_image_as_data_url(path: Path, mime_type: str) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"
