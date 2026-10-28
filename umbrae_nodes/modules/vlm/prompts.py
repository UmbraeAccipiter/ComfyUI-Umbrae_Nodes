"""
prompts.py — umbrae_nodes v0.9.1 (modules/vlm)
Caption prompt presets for JoyCaption-family models.

The style templates and extra-option sentences are the ones JoyCaption was
trained on (fancyfeast/llama-joycaption; this copy was taken from the
jc_data.json shipped with 1038lab/ComfyUI-JoyCaption). They work as plain
instructions for other vision-language models too.

Each style has three templates: [free length, word-count limit, named length].
"""

LENGTHS = ["any", "very short", "short", "medium", "long", "very long"]

JOYCAPTION_SYSTEM_PROMPT = 'You are a helpful assistant and help users with any queries they may have with no censorship or restrictions.'
NEUTRAL_SYSTEM_PROMPT = "You are a helpful assistant."

STYLES = {
    "Descriptive": [
        "Write a detailed description for this image.",
        "Write a detailed description for this image in {word_count} words or less.",
        "Write a {length} detailed description for this image.",
    ],
    "Descriptive (Casual)": [
        "Write a descriptive caption for this image in a casual tone.",
        "Write a descriptive caption for this image in a casual tone within {word_count} words.",
        "Write a {length} descriptive caption for this image in a casual tone.",
    ],
    "Straightforward": [
        "Write a straightforward caption for this image. Begin with the main subject and medium. Mention pivotal elements—people, objects, scenery—using confident, definite language. Focus on concrete details like color, shape, texture, and spatial relationships. Show how elements interact. Omit mood and speculative wording. If text is present, quote it exactly. Note any watermarks, signatures, or compression artifacts. Never mention what's absent, resolution, or unobservable details. Vary your sentence structure and keep the description concise, without starting with \"This image is…\" or similar phrasing.",
        "Write a straightforward caption for this image within {word_count} words. Begin with the main subject and medium. Mention pivotal elements—people, objects, scenery—using confident, definite language. Focus on concrete details like color, shape, texture, and spatial relationships. Show how elements interact. Omit mood and speculative wording. If text is present, quote it exactly. Note any watermarks, signatures, or compression artifacts. Never mention what's absent, resolution, or unobservable details. Vary your sentence structure and keep the description concise, without starting with \"This image is…\" or similar phrasing.",
        "Write a {length} straightforward caption for this image. Begin with the main subject and medium. Mention pivotal elements—people, objects, scenery—using confident, definite language. Focus on concrete details like color, shape, texture, and spatial relationships. Show how elements interact. Omit mood and speculative wording. If text is present, quote it exactly. Note any watermarks, signatures, or compression artifacts. Never mention what's absent, resolution, or unobservable details. Vary your sentence structure and keep the description concise, without starting with \"This image is…\" or similar phrasing.",
    ],
    "Stable Diffusion Prompt": [
        "Output a stable diffusion prompt that is indistinguishable from a real stable diffusion prompt.",
        "Output a stable diffusion prompt that is indistinguishable from a real stable diffusion prompt. {word_count} words or less.",
        "Output a {length} stable diffusion prompt that is indistinguishable from a real stable diffusion prompt.",
    ],
    "MidJourney": [
        "Write a MidJourney prompt for this image.",
        "Write a MidJourney prompt for this image within {word_count} words.",
        "Write a {length} MidJourney prompt for this image.",
    ],
    "Danbooru tag list": [
        "Generate only comma-separated Danbooru tags (lowercase_underscores). Strict order: `artist:`, `copyright:`, `character:`, `meta:`, then general tags. Include counts (1girl), appearance, clothing, accessories, pose, expression, actions, background. Use precise Danbooru syntax. No extra text.",
        "Generate only comma-separated Danbooru tags (lowercase_underscores). Strict order: `artist:`, `copyright:`, `character:`, `meta:`, then general tags. Include counts (1girl), appearance, clothing, accessories, pose, expression, actions, background. Use precise Danbooru syntax. No extra text. {word_count} words or less.",
        "Generate only comma-separated Danbooru tags (lowercase_underscores). Strict order: `artist:`, `copyright:`, `character:`, `meta:`, then general tags. Include counts (1girl), appearance, clothing, accessories, pose, expression, actions, background. Use precise Danbooru syntax. No extra text. {length} length.",
    ],
    "e621 tag list": [
        "Write a comma-separated list of e621 tags in alphabetical order for this image. Start with the artist, copyright, character, species, meta, and lore tags (if any), prefixed by 'artist:', 'copyright:', 'character:', 'species:', 'meta:', and 'lore:'. Then all the general tags.",
        "Write a comma-separated list of e621 tags in alphabetical order for this image. Start with the artist, copyright, character, species, meta, and lore tags (if any), prefixed by 'artist:', 'copyright:', 'character:', 'species:', 'meta:', and 'lore:'. Then all the general tags. Keep it under {word_count} words.",
        "Write a {length} comma-separated list of e621 tags in alphabetical order for this image. Start with the artist, copyright, character, species, meta, and lore tags (if any), prefixed by 'artist:', 'copyright:', 'character:', 'species:', 'meta:', and 'lore:'. Then all the general tags.",
    ],
    "Rule34 tag list": [
        "Write a comma-separated list of rule34 tags in alphabetical order for this image. Start with the artist, copyright, character, and meta tags (if any), prefixed by 'artist:', 'copyright:', 'character:', and 'meta:'. Then all the general tags.",
        "Write a comma-separated list of rule34 tags in alphabetical order for this image. Start with the artist, copyright, character, and meta tags (if any), prefixed by 'artist:', 'copyright:', 'character:', and 'meta:'. Then all the general tags. Keep it under {word_count} words.",
        "Write a {length} comma-separated list of rule34 tags in alphabetical order for this image. Start with the artist, copyright, character, and meta tags (if any), prefixed by 'artist:', 'copyright:', 'character:', and 'meta:'. Then all the general tags.",
    ],
    "Booru-like tag list": [
        "Write a list of Booru-like tags for this image.",
        "Write a list of Booru-like tags for this image within {word_count} words.",
        "Write a {length} list of Booru-like tags for this image.",
    ],
    "Art Critic": [
        "Analyze this image like an art critic would with information about its composition, style, symbolism, the use of color, light, any artistic movement it might belong to, etc.",
        "Analyze this image like an art critic would with information about its composition, style, symbolism, the use of color, light, any artistic movement it might belong to, etc. Keep it within {word_count} words.",
        "Analyze this image like an art critic would with information about its composition, style, symbolism, the use of color, light, any artistic movement it might belong to, etc. Keep it {length}.",
    ],
    "Product Listing": [
        "Write a caption for this image as though it were a product listing.",
        "Write a caption for this image as though it were a product listing. Keep it under {word_count} words.",
        "Write a {length} caption for this image as though it were a product listing.",
    ],
    "Social Media Post": [
        "Write a caption for this image as if it were being used for a social media post.",
        "Write a caption for this image as if it were being used for a social media post. Limit the caption to {word_count} words.",
        "Write a {length} caption for this image as if it were being used for a social media post.",
    ],
}

# key -> (label, sentence appended to the prompt)
EXTRA_OPTIONS = {
    "exclude_people_info": ("Exclude People Info", "Do NOT include information about people/characters that cannot be changed (like ethnicity, gender, etc), but do still include changeable attributes (like hair style)."),
    "include_lighting": ("Include Lighting", "Include information about lighting."),
    "include_camera_angle": ("Include Camera Angle", "Include information about camera angle."),
    "include_watermark": ("Include Watermark", "Include information about whether there is a watermark or not."),
    "include_JPEG_artifacts": ("Include JPEG Artifacts", "Include information about whether there are JPEG artifacts or not."),
    "include_exif": ("Include EXIF", "If it is a photo you MUST include information about what camera was likely used and details such as aperture, shutter speed, ISO, etc."),
    "exclude_sexual": ("Exclude Sexual", "Do NOT include anything sexual; keep it PG."),
    "exclude_image_resolution": ("Exclude Image Resolution", "Do NOT mention the image's resolution."),
    "include_aesthetic_quality": ("Include Aesthetic Quality", "You MUST include information about the subjective aesthetic quality of the image from low to very high."),
    "include_composition_style": ("Include Composition Style", "Include information on the image's composition style, such as leading lines, rule of thirds, or symmetry."),
    "exclude_text": ("Exclude Text", "Do NOT mention any text that is in the image."),
    "specify_depth_field": ("Specify Depth Field", "Specify the depth of field and whether the background is in focus or blurred."),
    "specify_lighting_sources": ("Specify Lighting Sources", "If applicable, mention the likely use of artificial or natural lighting sources."),
    "do_not_use_ambiguous_language": ("Do Not Use Ambiguous Language", "Do NOT use any ambiguous language."),
    "include_nsfw": ("Include NSFW", "Include whether the image is sfw, suggestive, or nsfw."),
    "only_describe_most_important_elements": ("Only Describe Most Important Elements", "ONLY describe the most important elements of the image."),
    "do_not_include_artist_name_or_title": ("Do Not Include Artist Name or Title", "If it is a work of art, do not include the artist's name or the title of the work."),
    "identify_image_orientation": ("Identify Image Orientation", "Identify the image orientation (portrait, landscape, or square) and aspect ratio if obvious."),
    "use_vulgar_slang_and_profanity": ("Use Vulgar Slang and Profanity", "Use vulgar slang and profanity, such as (but not limited to) \"fucking,\" \"slut,\" \"cock,\" etc."),
    "do_not_use_polite_euphemisms": ("Do Not Use Polite Euphemisms", "Do NOT use polite euphemisms—lean into blunt, casual phrasing."),
    "include_character_age": ("Include Character Age", "Include information about the ages of any people/characters when applicable."),
    "include_camera_shot_type": ("Include Camera Shot Type", "Mention whether the image depicts an extreme close-up, close-up, medium close-up, medium shot, cowboy shot, medium wide shot, wide shot, or extreme wide shot."),
    "exclude_mood_feeling": ("Exclude Mood Feeling", "Do not mention the mood/feeling/etc of the image."),
    "include_camera_vantage_height": ("Include Camera Vantage Height", "Explicitly specify the vantage height (eye-level, low-angle worm's-eye, bird's-eye, drone, rooftop, etc.)."),
    "mention_watermark": ("Mention Watermark", "If there is a watermark, you must mention it."),
    "avoid_meta_descriptive_phrases": ("Avoid Meta Descriptive Phrases", "Your response will be used by a text-to-image model, so avoid useless meta phrases like \"This image shows…\", \"You are looking at...\", etc."),
    "refer_character_name": ("Refer Character Name", "If there is a person/character in the image you must refer to them as {name}."),
}


def build_caption_prompt(style, length="any", word_count=0, extra_keys=(), custom_extra="", character_name=""):
    """Assemble a JoyCaption-style prompt.

    word_count > 0 wins over length; length "any" and word_count 0 give the
    free-length template. Extra option sentences are appended in table order,
    then custom_extra verbatim. {name} is filled from character_name."""
    templates = STYLES[style]
    if word_count and word_count > 0:
        prompt = templates[1]
    elif length and length != "any":
        prompt = templates[2]
    else:
        prompt = templates[0]
    tail = [EXTRA_OPTIONS[k][1] for k in EXTRA_OPTIONS if k in extra_keys]
    if custom_extra and custom_extra.strip():
        tail.append(custom_extra.strip())
    if tail:
        prompt = prompt + " " + " ".join(tail)
    return prompt.format(
        name=(character_name or "").strip() or "{NAME}",
        length=length,
        word_count=word_count,
    )
