import subprocess

def convert(input_path: str, output_path: str):
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, output_path],
        check=True, capture_output=True,
    )