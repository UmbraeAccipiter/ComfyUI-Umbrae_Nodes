import os

class PickFilenameByIndex:
    """
    Select one filename by loop index.
    Inputs:
      - filenames: STRING newline list (from ListFolderImages)
      - folder_path: STRING absolute folder
      - index: INT

    Outputs:
      - image_filename: "foo.jpg"
      - image_fullpath: "C:\\...\\foo.jpg"
      - image_stem:     "foo"
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "filenames": ("STRING", {"multiline": True}),
                "folder_path": ("STRING", {"multiline": False}),
                "index": ("INT", {"default": 0, "min": 0, "max": 10_000_000}),
            }
        }

    RETURN_TYPES = ("STRING","STRING","STRING")
    RETURN_NAMES = ("image_filename","image_fullpath","image_stem")
    FUNCTION = "pick"
    CATEGORY = "umbrae/files"

    def pick(self, filenames, folder_path, index):
        items = [ln.strip() for ln in (filenames or "").splitlines() if ln.strip()]
        n = len(items)
        if n == 0:
            return ("", "", "")
        idx = max(0, min(int(index), n-1))
        name = items[idx]
        path = os.path.join(folder_path or "", name)
        stem = os.path.splitext(os.path.basename(name))[0]
        return (name, path, stem)
