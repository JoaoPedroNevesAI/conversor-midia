from PIL import Image

def convert(input_path: str, output_path: str):
    img = Image.open(input_path)
    if img.mode in ("RGBA", "P") and output_path.lower().endswith((".jpg", ".jpeg")):
        img = img.convert("RGB")
    img.save(output_path)