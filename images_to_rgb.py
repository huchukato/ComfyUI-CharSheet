"""Plain ComfyUI IMAGE conversion. No downloads, paths, or optional packages."""
import torch


class ImagesToRGB:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)}, "optional": {
            "mode": (["RGB", "Keep original", "RGB with background"], {"default": "RGB"}),
            "background_colour": ("STRING", {"default": "#FFFFFF", "tooltip": "Background for RGB with background mode, as #RRGGBB."}),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "image_to_rgb"
    CATEGORY = "CharSheet/Image"
    DESCRIPTION = (
        "RGB discards alpha; Keep original preserves incoming channels and transparency; "
        "RGB with background composites transparency onto a chosen #RRGGBB colour. "
        "Preserves resolution and batch order. Does not generate transparency."
    )

    def image_to_rgb(self, images, mode="RGB", background_colour="#FFFFFF"):
        if not isinstance(images, torch.Tensor) or images.ndim != 4:
            raise ValueError("Images to RGB expects a ComfyUI IMAGE batch [batch, height, width, channels].")
        channels = images.shape[-1]
        if channels not in (1, 2, 3, 4):
            raise ValueError(f"Images to RGB expects 1, 2, 3 or 4 channels; received {channels}.")
        if mode not in ("RGB", "Keep original", "RGB with background"):
            raise ValueError("Images to RGB: choose a supported conversion mode.")
        if mode == "Keep original":
            return (images,)
        rgb = images if channels == 3 else (images[..., :3].contiguous() if channels == 4
                                            else images[..., :1].repeat(1, 1, 1, 3))
        if mode == "RGB":
            return (rgb,)
        import re
        colour = str(background_colour).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise ValueError("Images to RGB: background colour must be #RRGGBB, for example #FFFFFF for white.")
        if channels in (2, 4):
            if not images.is_floating_point():
                raise ValueError("Images to RGB: compositing expects standard floating-point ComfyUI images in the 0-1 range.")
            background = images.new_tensor([int(colour[i:i+2], 16) / 255.0 for i in (1, 3, 5)])
            alpha = images[..., -1:].clamp(0, 1)
            rgb = rgb * alpha + background * (1 - alpha)
        return (rgb,)


NODE_CLASS_MAPPINGS = {"ImagesToRGB": ImagesToRGB}
NODE_DISPLAY_NAME_MAPPINGS = {"ImagesToRGB": "Images to RGB"}
