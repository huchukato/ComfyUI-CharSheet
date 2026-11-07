# Character Sheet Compositor
#
# Takes 5 individual frames (Close-up, Front, Left Profile, Right Profile,
# Back — each already pulled out via its own ImageFromBatch node upstream)
# and lays them out side by side on one sheet.
#
# close_up is shown in full, uncropped, at its real width. The other four
# get a centered width crop (body_width_pct of their natural, height-scaled
# width) so they read as the "thinner panels" next to the uncropped
# close-up. target_aspect_ratio solves that crop automatically so the final
# canvas lands on the requested ratio.

import numpy as np
import torch
from PIL import Image

CATEGORY = "CharSheet"

_BG_COLORS = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "mid gray": (128, 128, 128),
}

_ASPECT_RATIOS = {
    "off (use body_width_pct manually)": None,
    "16:9": 16 / 9,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "3:2": 3 / 2,
    "21:9": 21 / 9,
}


def _tensor_to_pil(image_tensor, background_rgb=(255, 255, 255)):
    # ComfyUI IMAGE tensors are (batch, H, W, C) float 0-1 — take the first
    # frame of whatever batch arrives (a single extracted frame is batch=1).
    if (image_tensor.ndim != 4 or image_tensor.shape[0] < 1
            or image_tensor.shape[1] < 1 or image_tensor.shape[2] < 1
            or image_tensor.shape[-1] not in (3, 4)):
        raise ValueError("Compositor input must be a nonempty RGB/RGBA IMAGE batch.")
    frame = image_tensor[0].detach().clamp(0.0, 1.0).mul(255.0).round().to(torch.uint8).cpu().numpy()
    image = Image.fromarray(frame)
    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, tuple(background_rgb) + (255,))
        image = Image.alpha_composite(background, image)
    return image.convert("RGB")


def _pil_to_tensor(image):
    arr = np.array(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def _scale_to_height(image, panel_h, width_pct=100.0):
    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGB", (1, panel_h), (255, 255, 255))
    scale = panel_h / src_h
    new_w = max(1, round(src_w * scale))
    resized = image.resize((new_w, panel_h), Image.LANCZOS)
    if width_pct >= 100.0:
        return resized
    # Centered horizontal crop — trims equally off both sides, keeping the
    # subject (who's centered in these turnaround frames) centered too.
    crop_w = max(1, round(new_w * width_pct / 100.0))
    left = (new_w - crop_w) // 2
    return resized.crop((left, 0, left + crop_w, panel_h))


class CharacterSheetCompositor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "close_up": ("IMAGE",),
                "front": ("IMAGE",),
                "left_profile": ("IMAGE",),
                "right_profile": ("IMAGE",),
                "back": ("IMAGE",),
                "panel_height": ("INT", {"default": 1080, "min": 320, "max": 4096, "step": 8, "tooltip":
                    "Every panel is scaled to exactly this height. close_up is then shown at its full, "
                    "uncropped width; the other four get body_width_pct applied."}),
                "body_width_pct": ("INT", {"default": 60, "min": 20, "max": 100, "step": 1, "tooltip":
                    "Centered horizontal crop applied to front/left_profile/right_profile/back only "
                    "(as a % of their natural width at panel_height) so they read as thinner panels "
                    "next to the uncropped close_up. 100 = no crop, same width as close_up."}),
                "gap": ("INT", {"default": 12, "min": 0, "max": 200, "step": 2, "tooltip":
                    "Pixel spacing between panels, and around the outer edge."}),
                "background_color": (list(_BG_COLORS.keys()), {"default": "white", "tooltip":
                    "Fills the gaps and outer edge around the panels."}),
                "target_aspect_ratio": (list(_ASPECT_RATIOS.keys()), {"default": "off (use body_width_pct manually)", "tooltip":
                    "When set, ignores body_width_pct and instead solves for the crop percentage on "
                    "front/left_profile/right_profile/back that makes the final canvas land exactly on "
                    "this ratio. close_up is never cropped either way — only the other 4 panels' width "
                    "changes. If the target can't be reached within the 20-100% crop range at this "
                    "panel_height/gap, it clamps to the closest possible and logs a warning."}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("character_sheet",)
    FUNCTION = "execute"
    CATEGORY = CATEGORY

    def execute(self, close_up, front, left_profile, right_profile, back,
                panel_height, body_width_pct, gap, background_color,
                target_aspect_ratio="off (use body_width_pct manually)"):
        panel_h = max(1, int(panel_height))
        bg_rgb = _BG_COLORS.get(background_color, (255, 255, 255))

        close_up_panel = _scale_to_height(_tensor_to_pil(close_up, bg_rgb), panel_h, 100.0)

        target_ratio = _ASPECT_RATIOS.get(target_aspect_ratio)
        if target_ratio is not None:
            canvas_h = panel_h + gap * 2
            # canvas_w = close_up_w * (1 + 4*bp/100) + 6*gap — solve for bp.
            needed_multiplier = (target_ratio * canvas_h - gap * 6) / close_up_panel.width
            solved_bp = (needed_multiplier - 1) * 25
            clamped_bp = max(20.0, min(100.0, solved_bp))
            if abs(clamped_bp - solved_bp) > 0.5:
                print(f"[CharacterSheetCompositor] target_aspect_ratio {target_aspect_ratio} would need "
                      f"body_width_pct={solved_bp:.1f}%, outside the 20-100% range — clamped to "
                      f"{clamped_bp:.1f}%. Result won't hit the exact target ratio; try a different "
                      f"panel_height/gap, or a less extreme target.")
            body_width_pct = clamped_bp

        panels = [close_up_panel] + [
            _scale_to_height(_tensor_to_pil(img, bg_rgb), panel_h, float(body_width_pct))
            for img in (front, left_profile, right_profile, back)
        ]

        content_w = sum(p.width for p in panels) + gap * 4
        canvas_w = content_w + gap * 2
        canvas_h = panel_h + gap * 2

        sheet = Image.new("RGB", (canvas_w, canvas_h), bg_rgb)
        x = gap
        for panel in panels:
            sheet.paste(panel, (x, gap))
            x += panel.width + gap

        return (_pil_to_tensor(sheet),)


NODE_CLASS_MAPPINGS = {"CharacterSheetCompositor": CharacterSheetCompositor}
NODE_DISPLAY_NAME_MAPPINGS = {"CharacterSheetCompositor": "Character Sheet Compositor"}
