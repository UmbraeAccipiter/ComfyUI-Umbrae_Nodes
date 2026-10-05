import os

class ListFolderImages:
    """
    List image files in a folder (no tensors).
    Outputs:
      - filenames: STRING (newline-separated, sorted case-insensitively)
      - folder_path: STRING (absolute)
      - count: INT (number of files)
      - last_index: INT (count-1, or 0 if empty)

    Inputs:
      - selected_folder: dropdown under ComfyUI/output (for convenience)
      - custom_folder_path: optional absolute/relative path; overrides dropdown if non-empty
      - extensions: filter list (csv), default common images
      - include_subfolders: if True, list images recursively
    """
    @classmethod
    def INPUT_TYPES(cls):
        # Build dropdown from ComfyUI/output
        script_dir = os.path.dirname(os.path.abspath(__file__))
        comfyui_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
        output_dir = os.path.join(comfyui_root, 'output')

        def has_images(path, exts):
            for f in os.listdir(path):
                if f.lower().endswith(exts):
                    return True
            return False

        folders = []
        for root, dirs, files in os.walk(output_dir):
            rel = os.path.relpath(root, output_dir)
            if rel == '.':
                continue
            if has_images(root, ('.png','.jpg','.jpeg','.gif','.bmp','.webp')):
                count = sum(1 for f in os.listdir(root)
                            if f.lower().endswith(('.png','.jpg','.jpeg','.gif','.bmp','.webp')))
                folders.append((f"{rel} ({count} images)", rel))
        folders.sort(key=lambda x: x[0].lower())

        return {
            "required": {
                "selected_folder": ([name for name,_ in folders],),
            },
            "optional": {
                "custom_folder_path": ("STRING", {"default": "", "multiline": False}),
                "extensions": ("STRING", {"default": ".png,.jpg,.jpeg,.gif,.bmp,.webp", "multiline": False}),
                "include_subfolders": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING","STRING","INT","INT")
    RETURN_NAMES = ("filenames","folder_path","count","last_index")
    FUNCTION = "list"
    CATEGORY = "umbrae/files"

    def list(self, selected_folder, custom_folder_path="", extensions=".png,.jpg,.jpeg,.gif,.bmp,.webp", include_subfolders=False):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        comfyui_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
        output_dir = os.path.join(comfyui_root, 'output')

        # Resolve folder
        if custom_folder_path.strip():
            base = os.path.abspath(custom_folder_path.strip())
        else:
            base_rel = selected_folder.split(" (")[0]
            base = os.path.join(output_dir, base_rel)

        exts = tuple([e.strip().lower() for e in extensions.split(",") if e.strip()])
        files = []
        if include_subfolders:
            for root, dirs, fs in os.walk(base):
                for f in fs:
                    if f.lower().endswith(exts):
                        files.append(os.path.relpath(os.path.join(root, f), base))
        else:
            for f in os.listdir(base):
                if f.lower().endswith(exts):
                    files.append(f)

        files.sort(key=lambda x: x.lower())
        count = len(files)
        last_index = max(0, count-1)
        return ("\n".join(files), os.path.abspath(base), count, last_index)
