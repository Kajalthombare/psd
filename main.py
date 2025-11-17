from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os, uuid, zipfile
from psd_tools import PSDImage
from PIL import Image

# -----------------------------------------------------
#                FASTAPI INITIALIZATION
# -----------------------------------------------------
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# -----------------------------------------------------
#                   EXPORT FUNCTIONS
# -----------------------------------------------------
def export_layers_cut(layer, output_path):
    img = layer.composite()
    if img:
        bbox = img.getbbox()
        if bbox:
            cropped = img.crop(bbox)
            cropped.save(output_path)


def export_layers_full(layer, canvas_size, output_path):
    img = layer.composite()
    if img:
        full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        full_img.paste(img, layer.offset)
        full_img.save(output_path)


def process_psd(psd_path, output_path):
    psd = PSDImage.open(psd_path)
    canvas = (psd.width, psd.height)

    output_folder = output_path.replace(".zip", "")
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    for i, layer in enumerate(psd):
        layer_name = f"layer_{i}"

        # CUT EXPORT
        cut_file = os.path.join(output_folder, f"{layer_name}_cut.png")
        export_layers_cut(layer, cut_file)

        # FULL CANVAS EXPORT
        full_file = os.path.join(output_folder, f"{layer_name}_full.png")
        export_layers_full(layer, canvas, full_file)

    # ZIP OUTPUT
    shutil.make_archive(output_folder, 'zip', outp
