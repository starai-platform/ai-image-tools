"""Shared image-edit settings for the web and command-line workflows."""

from dataclasses import dataclass
from hashlib import sha256
import json
import os


PRESETS = ("standard", "packaging", "custom")
MAX_CUSTOM_REQUIREMENTS = 2000
MAX_BRAND_TEXT = 300

PACKAGING_PROMPT = (
    "Create a new square studio image from the physical product or packaging shown in the source. "
    "Keep the product and every visible package, their proportions, angles, colors and printed artwork. "
    "Keep all visible logos, brand and model names, variant names, specifications and warning "
    "labels on the packaging legible and verbatim. Never guess unreadable print or add claims. "
    "By default use a quiet, low-saturation studio gradient, diffused side light, a natural "
    "contact shadow and ample negative space. If both a product and packaging appear, "
    "position them with clear visual spacing and unobstructed labels. "
    "Do not reuse the source poster's surrounding headlines, typography, "
    "decorative graphics, or layout. Do not remove attributions or watermarks."
)

CUSTOM_PROMPT = "Create a square product image from the supplied source and the creative requirements below."

PRODUCT_FIDELITY = (
    "Requirements that take priority over creative directions: keep the product identity and "
    "preserve visible branding, model names, variant information and warnings. Maintain factual "
    "specifications. Do not invent, rewrite, or obscure these markings or remove attributions "
    "or watermarks."
)


@dataclass(frozen=True)
class EditSettings:
    preset: str = "standard"
    custom_requirements: str = ""
    brand_text: str = ""

    def __post_init__(self):
        if self.preset not in PRESETS:
            raise ValueError("请选择有效的出图预设。")
        for field, limit, label in (
            ("custom_requirements", MAX_CUSTOM_REQUIREMENTS, "自定义要求"),
            ("brand_text", MAX_BRAND_TEXT, "品牌 / 型号文字"),
        ):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise ValueError(f"{label}必须为文字。")
            value = value.strip()
            if len(value) > limit:
                raise ValueError(f"{label}最多 {limit} 个字符。")
            object.__setattr__(self, field, value)
        if self.preset == "custom" and not self.custom_requirements:
            raise ValueError("完全自定义模式需要填写出图要求。")

    def prompt(self, standard_prompt: str) -> str:
        base_prompt = {"packaging": PACKAGING_PROMPT, "custom": CUSTOM_PROMPT}.get(self.preset, standard_prompt)
        sections = [base_prompt]
        if self.custom_requirements:
            sections.append(
                "Creative requirements for this batch (apply to composition, background and lighting):\n"
                f"{self.custom_requirements}"
            )
        if self.preset != "standard" or self.custom_requirements or self.brand_text:
            sections.append(PRODUCT_FIDELITY)
        if self.brand_text:
            sections.append(
                "Use the following exact spelling for these markings when present on the source product. "
                "Do not add them as separate headings, and keep each image's own variant and warning text.\n"
                f"{self.brand_text}"
            )
        return "\n\n".join(sections)

    def output_directory(self, root: str, source_dir: str = "") -> str:
        if self == EditSettings():
            return root
        source = os.path.normcase(os.path.realpath(source_dir)) if source_dir else ""
        settings = json.dumps([source, self.preset, self.custom_requirements, self.brand_text], ensure_ascii=False)
        suffix = sha256(settings.encode("utf-8")).hexdigest()[:12]
        return os.path.join(root, f"{self.preset}-{suffix}")
