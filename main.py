from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil, os, uuid, zipfile
from psd_tools import PSDImage
from PIL import Image


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# -----------------------------------------------------
# PSD EXPORT FUNCTIONS
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


def process_single_psd(psd_path, output_dir):
    """Exports layers for a single PSD file."""
    psd = PSDImage.open(psd_path)
    canvas = (psd.width, psd.height)

    for i, layer in enumerate(psd):
        layer_name = f"layer_{i}"

        cut_file = os.path.join(output_dir, f"{layer_name}_cut.png")
        export_layers_cut(layer, cut_file)

        full_file = os.path.join(output_dir, f"{layer_name}_full.png")
        export_layers_full(layer, canvas, full_file)


# -----------------------------------------------------
# ZIP PROCESSING
# -----------------------------------------------------
def process_zip(zip_path, output_zip):
    """Process a ZIP containing multiple PSD files."""

    temp_extract = f"temp_{uuid.uuid4().hex}"
    os.makedirs(temp_extract, exist_ok=True)

    # Extract ZIP
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(temp_extract)

    # Output base folder
    output_base = output_zip.replace(".zip", "")
    if os.path.exists(output_base):
        shutil.rmtree(output_base)
    os.makedirs(output_base, exist_ok=True)

    # Process each PSD inside ZIP
    for root, _, files in os.walk(temp_extract):
        for f in files:
            if f.lower().endswith(".psd"):
                psd_path = os.path.join(root, f)
                psd_name = os.path.splitext(f)[0]

                psd_output_dir = os.path.join(output_base, psd_name)
                os.makedirs(psd_output_dir, exist_ok=True)

                process_single_psd(psd_path, psd_output_dir)

    shutil.make_archive(output_base, "zip", output_base)
    shutil.rmtree(temp_extract)

    return output_base + ".zip"


# -----------------------------------------------------
# ROUTES
# -----------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    file_ext = file.filename.split(".")[-1].lower()

    task_id = uuid.uuid4().hex
    input_path = f"uploads/{task_id}_{file.filename}"
    output_zip = f"outputs/{task_id}_output.zip"

    # Save uploaded file
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # PSD file
    if file_ext == "psd":
        output_folder = output_zip.replace(".zip", "")
        os.makedirs(output_folder, exist_ok=True)
        process_single_psd(input_path, output_folder)
        shutil.make_archive(output_folder, 'zip', output_folder)
        return FileResponse(output_folder + ".zip", filename=os.path.basename(output_zip))

    # ZIP file containing PSDs
    elif file_ext == "zip":
        result_path = process_zip(input_path, output_zip)
        return FileResponse(result_path, filename=os.path.basename(result_path))

    else:
        return {"error": "Please upload PSD or ZIP containing PSD files."}
