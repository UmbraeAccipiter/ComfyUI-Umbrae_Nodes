# __init__.py — umbrae_nodes v0.9.5
# registers all umbrae custom nodes
#
# Layout: all code is in modules/ (modules/clause/ = wildcard clause expander,
# modules/expander/ = wildcard expander);
# web/ = front-end, wildcards/ + wildcard_examples/ = wildcard roots,
# dev/ = browser harness for the UI lab, umbrae_wildcard_syntax.* = cheat sheets.

from .modules.integer_stepper import IntegerStepper
from .modules.list_folder_images import ListFolderImages
from .modules.load_images_uniform_batch import LoadImagesUniformBatch
from .modules.constant_image import ConstantImage1x1
from .modules.save_image_smart import SaveImageSmart
from .modules.save_image_with_name import SaveImageWithName
from .modules.select_image_and_name import SelectImageAndName
from .modules.save_training_pair import SaveTrainingPair
from .modules.crop_image_region import CropImageRegion
from .modules.simple_crop import UmbraeSimpleCrop
from .modules.training_prep import UmbraeTrainingPrep
from .modules.number_tools import MathTranslation
from .modules.pick_filename_by_index import PickFilenameByIndex
from .modules.batch_mask_ldsv_node import SaveMaskBatch, LoadMaskBatch, MaskBatchOverlay, CombineMaskBatch
from .modules.break_inserter_node import BreakInserter
from .modules.safe_string_node import SafeString
from .modules.latent_auto_encode_node import LatentAutoEncode
from .modules.frame_toggle_node import UmbraeFrameMarker, UmbraeFrameToggleController
from .modules.run_timer_node import UmbraeRunTimer  # v0.9.2 - frontend-only stopwatch + run history
from .modules.load_image_rgba import UmbraeLoadImageRGBA
from .modules.rgba_inpaint_nodes import UmbraeInpaintCropRGBA, UmbraeInpaintStitchRGBA
from .modules.umbrae_wildcard_nodes import UmbraeWildcardProcessor
from .modules import umbrae_wildcard_server  # noqa: F401  (loads wildcards, registers routes + populate hook)
from .modules.clause import (   # v0.8.8 - wildcard clause expander on the umbrae engine (routes + hook)
    NODE_CLASS_MAPPINGS as _CLAUSE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _CLAUSE_DISPLAY_MAPPINGS,
)
from .modules.expander import (  # v0.9.0 - wildcard expander: batch + per-draw pins (routes)
    NODE_CLASS_MAPPINGS as _EXPANDER_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _EXPANDER_DISPLAY_MAPPINGS,
)
from .modules.external_loaders import (
    NODE_CLASS_MAPPINGS as _EXT_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _EXT_DISPLAY_MAPPINGS,
)
from .modules.vlm import (  # v0.9.1 - HF VLM/LLM loader + generate under ComfyUI model management
    NODE_CLASS_MAPPINGS as _VLM_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _VLM_DISPLAY_MAPPINGS,
)
from .modules.lora_loader import (  # v0.9.3 - LoRA stack + Civitai / HF search, download, gallery info panel
    NODE_CLASS_MAPPINGS as _LORA_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _LORA_DISPLAY_MAPPINGS,
)

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "IntegerStepper": IntegerStepper,
    "ListFolderImages": ListFolderImages,
    "LoadImagesUniformBatch": LoadImagesUniformBatch,
    "ConstantImage": ConstantImage1x1,
    "SaveImageSmart": SaveImageSmart,
    "SaveImageWithName": SaveImageWithName,
    "SelectImageAndName": SelectImageAndName,
    "SaveTrainingPair": SaveTrainingPair,
    "CropImageRegion": CropImageRegion,
    "UmbraeSimpleCrop": UmbraeSimpleCrop,
    "UmbraeTrainingPrep": UmbraeTrainingPrep,
    "MathTranslation": MathTranslation,
    "PickFilenameByIndex": PickFilenameByIndex,
    "SaveMaskBatch": SaveMaskBatch,
    "LoadMaskBatch": LoadMaskBatch,
    "MaskBatchOverlay": MaskBatchOverlay,
    "CombineMaskBatch": CombineMaskBatch,
    "BreakInserter": BreakInserter,
    "SafeString": SafeString,
    "LatentAutoEncode": LatentAutoEncode,
    "UmbraeFrameMarker": UmbraeFrameMarker,
    "UmbraeFrameToggleController": UmbraeFrameToggleController,
    "UmbraeRunTimer": UmbraeRunTimer,
    # v0.8.1 - RGBA load / inpaint crop / inpaint stitch
    "UmbraeLoadImageRGBA": UmbraeLoadImageRGBA,
    "UmbraeInpaintCropRGBA": UmbraeInpaintCropRGBA,
    "UmbraeInpaintStitchRGBA": UmbraeInpaintStitchRGBA,
    # v0.8.2 - wildcard processor (port of Impact Pack's, GPL-3.0)
    "UmbraeWildcardProcessor": UmbraeWildcardProcessor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IntegerStepper": "integer stepper [umbrae]",
    "ListFolderImages": "list folder images [umbrae]",
    "LoadImagesUniformBatch": "load images uniform batch [umbrae]",
    "ConstantImage": "constant image 1x1 [umbrae]",
    "SaveImageSmart": "save image smart [umbrae]",
    "SaveImageWithName": "save image with name [umbrae]",
    "SelectImageAndName": "select image and name [umbrae]",
    "SaveTrainingPair": "save training pair [umbrae]",
    "CropImageRegion": "crop image region [umbrae]",
    "UmbraeSimpleCrop": "crop image [umbrae]",
    "UmbraeTrainingPrep": "training prep [umbrae]",
    "MathTranslation": "math translation [umbrae]",
    "PickFilenameByIndex": "pick filename by index [umbrae]",
    "SaveMaskBatch": "save mask batch [umbrae]",
    "LoadMaskBatch": "load mask batch [umbrae]",
    "MaskBatchOverlay": "mask batch overlay [umbrae]",
    "CombineMaskBatch": "combine mask batch [umbrae]",
    "BreakInserter": "break inserter [umbrae]",
    "SafeString": "safe string [umbrae]",
    "LatentAutoEncode": "latent auto encode [umbrae]",
    "UmbraeFrameMarker": "frame marker [umbrae]",
    "UmbraeFrameToggleController": "frame toggle controller [umbrae]",
    "UmbraeRunTimer": "run timer [umbrae]",
    "UmbraeLoadImageRGBA": "load image rgba [umbrae]",
    "UmbraeInpaintCropRGBA": "inpaint crop rgba [umbrae]",
    "UmbraeInpaintStitchRGBA": "inpaint stitch rgba [umbrae]",
    "UmbraeWildcardProcessor": "wildcard processor [umbrae]",
}

# ── Wildcard clause expander (v0.8.8, port of ComfyUI-WildcardClause) ────────
NODE_CLASS_MAPPINGS.update(_CLAUSE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_CLAUSE_DISPLAY_MAPPINGS)

# ── Wildcard expander (v0.9.0: N prompts over a seed plan, pin / skip / replace any draw) ──
NODE_CLASS_MAPPINGS.update(_EXPANDER_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_EXPANDER_DISPLAY_MAPPINGS)

# ── External loaders (integrated v57) ─────────────────────────────────────────
NODE_CLASS_MAPPINGS.update(_EXT_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_EXT_DISPLAY_MAPPINGS)

# ── VLM / LLM (v0.9.1: HF models owned by ComfyUI's memory manager; see modules/vlm/README.md) ──
NODE_CLASS_MAPPINGS.update(_VLM_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_VLM_DISPLAY_MAPPINGS)

# ── LoRA loader (v0.9.3: stack + triggers output, Civitai / Hugging Face search + download; see modules/lora_loader/README.md) ──
NODE_CLASS_MAPPINGS.update(_LORA_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_LORA_DISPLAY_MAPPINGS)

# ── UI lab (DEV ONLY: do-nothing nodes for comparing panel styles; see modules/ui_lab_node.py) ──
from .modules.ui_lab_node import (
    NODE_CLASS_MAPPINGS as _LAB_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _LAB_DISPLAY_MAPPINGS,
)
NODE_CLASS_MAPPINGS.update(_LAB_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_LAB_DISPLAY_MAPPINGS)
