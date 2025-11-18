from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import shutil, os, uuid, zipfile, requests, threading
from psd_tools import PSDImage
from PIL import Image
import io

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

tasks = {}


# ----------------------------------------
#  IMAGE COMPRESSION (<500 KB)
# ----------------------------------------
def compress_image(image: Image.Image, save_path: str, max_size_kb=500):
    """Compress PNG to stay under max_size_kb."""
    buffer = io.BytesIO()
    quality = 95

    while True:
        buffer.seek(0)
        image.save(buffer, format="PNG", optimize=True)
        size_kb = len(buffer.getvalue()) / 1024

        if size_kb <= max_size_kb or quality <= 10:
            break

        quality -= 10  # adjust quality each loop

    with open(save_path, "wb") as f:
        f.write(buffer.getvalue())


# ----------------------------------------
#  EXPORT CUT + FULL CANVAS
# ----------------------------------------
def export_layer_assets(layer, canvas_size, output_dir, index):
    if not layer.is_visible():
        return

    img = layer.composite()
    if img is None:
        return

    # -------- CUT IMAGE --------
    bbox = img.getbbox()
    if bbox:
        cut_img = img.crop(bbox)
        cut_path = os.path.join(output_dir, f"layer_{index}_cut.png")
        compress_image(cut_img, cut_path)

    # -------- FULL CANVAS --------
    full_img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    full_img.paste(img, layer.offset)
    full_path = os.path.join(output_dir, f"layer_{index}_full.png")
    compress_image(full_img, full_path)


# ----------------------------------------
#  PROCESS A SINGLE PSD
# ----------------------------------------
def process_psd(psd_path, output_dir):
    psd = PSDImage.open(psd_path)
    canvas = (psd.width, psd.height)

    for i, layer in enumerate(psd):
        export_layer_assets(layer, canvas, output_dir, i)


# ----------------------------------------
#  BACKGROUND WORKER (for URL ZIP)
# ----------------------------------------
def worker(task_id, zip_path):
    try:
        tasks[task_id]["status"] = "processing"

        extract_dir = f"work/{task_id}/input"
        out_dir = f"work/{task_id}/output"
        os.makedirs(extract_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)

        # EXTRACT ZIP
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        # PROCESS PSD FILES INSIDE ZIP
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f.lower().endswith(".psd"):
                    psd_path = os.path.join(root, f)
                    name = os.path.splitext(f)[0]
                    psd_output = os.path.join(out_dir, name)
                    os.makedirs(psd_output, exist_ok=True)

                    process_psd(psd_path, psd_output)

        # CREATE FINAL ZIP
        final_zip = f"outputs/{task_id}.zip"
        shutil.make_archive(final_zip.replace(".zip", ""), "zip", out_dir)

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = final_zip

    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)


# ----------------------------------------
#  API MODELS
# ----------------------------------------
class UrlInput(BaseModel):
    url: str


# ----------------------------------------
#  ROUTES
# ----------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
   
    return templates.TemplateResponse("home.html", {"request": request})



@app.post("/process_url")
async def process_url(data: UrlInput):
    task_id = uuid.uuid4().hex

    # -------------------------------
    # SMART GOOGLE DRIVE LINK SUPPORT
    # -------------------------------
    url = data.url.strip()

    if "drive.google.com" in url:
        try:
            # Case 1: https://drive.google.com/file/d/FILE_ID/view
            if "/d/" in url:
                file_id = url.split("/d/")[1].split("/")[0]

            # Case 2: https://drive.google.com/open?id=FILE_ID
            elif "id=" in url:
                file_id = url.split("id=")[-1]

            else:
                return {"error": "Unable to extract Google Drive file ID."}

            # Convert to direct download
            url = f"https://drive.google.com/uc?export=download&id={file_id}"

        except Exception:
            return {"error": "Invalid Google Drive link format."}

    # -------------------------------------
    # DOWNLOAD THE ZIP (ANY SIZE, FASTAPI)
    # -------------------------------------
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("work", exist_ok=True)

    zip_path = f"downloads/{task_id}.zip"

    try:
        r = requests.get(url, stream=True)
        if r.status_code != 200:
            return {"error": "Download failed. The URL may not be public."}

        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):  # 1MB chunks
                f.write(chunk)

    except Exception as e:
        return {"error": f"Error while downloading: {str(e)}"}

    # -------------------------------------
    # START BACKGROUND WORKER
    # -------------------------------------
    tasks[task_id] = {"status": "queued"}
    threading.Thread(target=worker, args=(task_id, zip_path)).start()

    return {"task_id": task_id}



@app.get("/status/{task_id}")
def check_status(task_id):
    return tasks.get(task_id, {"status": "not_found"})


@app.get("/download/{task_id}")
def download(task_id):
    info = tasks.get(task_id)
    if not info or "result" not in info:
        return {"error": "Result not ready"}

    return FileResponse(info["result"], filename=f"{task_id}.zip")
