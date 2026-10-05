# __init__.py — umbrae_nodes v0.8.6
# registers all umbrae custom nodes

from .integer_stepper import IntegerStepper
from .list_folder_images import ListFolderImages
from .load_images_uniform_batch import LoadImagesUniformBatch
from .constant_image import ConstantImage1x1
from .save_image_smart import SaveImageSmart
from .save_image_with_name import SaveImageWithName
from .select_image_and_name import SelectImageAndName
from .save_training_pair import SaveTrainingPair
from .crop_image_region import CropImageRegion
from .simple_crop import UmbraeSimpleCrop
from .training_prep import UmbraeTrainingPrep
from .number_tools import MathTranslation
from .pick_filename_by_index import PickFilenameByIndex
from .batch_mask_ldsv_node import SaveMaskBatch, LoadMaskBatch, MaskBatchOverlay, CombineMaskBatch
from .break_inserter_node import BreakInserter
from .safe_string_node import SafeString
from .latent_auto_encode_node import LatentAutoEncode
from .frame_toggle_node import UmbraeFrameMarker, UmbraeFrameToggleController
from .load_image_rgba import UmbraeLoadImageRGBA
from .rgba_inpaint_nodes import UmbraeInpaintCropRGBA, UmbraeInpaintStitchRGBA
from .umbrae_wildcard_nodes import UmbraeWildcardProcessor
from . import umbrae_wildcard_server  # noqa: F401  (loads wildcards, registers routes + populate hook)
from .external_loaders import (
    NODE_CLASS_MAPPINGS as _EXT_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _EXT_DISPLAY_MAPPINGS,
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
    "UmbraeLoadImageRGBA": "load image rgba [umbrae]",
    "UmbraeInpaintCropRGBA": "inpaint crop rgba [umbrae]",
    "UmbraeInpaintStitchRGBA": "inpaint stitch rgba [umbrae]",
    "UmbraeWildcardProcessor": "wildcard processor [umbrae]",
}

# ── External loaders (integrated v57) ─────────────────────────────────────────
NODE_CLASS_MAPPINGS.update(_EXT_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_EXT_DISPLAY_MAPPINGS)

# ── UI lab (DEV ONLY: do-nothing nodes for comparing panel styles; see ui_lab_node.py) ──
from .ui_lab_node import (
    NODE_CLASS_MAPPINGS as _LAB_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _LAB_DISPLAY_MAPPINGS,
)
NODE_CLASS_MAPPINGS.update(_LAB_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_LAB_DISPLAY_MAPPINGS)
