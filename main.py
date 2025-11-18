from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import shutil, os, uuid, zipfile, requests, threading
from psd_tools import PSDImage
from PIL import Image

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

tasks = {}  # Store task_id → status/result


# ---------------------------------------------------
# PSD EXPORTING
# ---------------------------------------------------
def export_layers(psd_path, output_dir):
    psd = PSDImage.open(psd_path)
    canvas = (psd.width, psd.height)

    for i, layer in enumerate(psd):
        img = layer.composite()

        if img:
            # cut
            bbox = img.getbbox()
            if bbox:
                img.crop(bbox).save(f"{output_dir}/layer_{i}_cut.png")

            # full
            full = Image.new("RGBA", canvas, (0, 0, 0, 0))
            full.paste(img, layer.offset)
            full.save(f"{output_dir}/layer_{i}_full.png")


# ---------------------------------------------------
# BACKGROUND WORKER
# ---------------------------------------------------
def process_zip_worker(task_id, zip_path):
    try:
        tasks[task_id]["status"] = "processing"

        extract_dir = f"work/{task_id}/extracted"
        out_dir = f"work/{task_id}/output"
        os.makedirs(extract_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)

        # Extract ZIP
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        # Process all PSD files
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f.lower().endswith(".psd"):
                    psd_path = os.path.join(root, f)
                    name = os.path.splitext(f)[0]

                    psd_out = os.path.join(out_dir, name)
                    os.makedirs(psd_out, exist_ok=True)

                    export_layers(psd_path, psd_out)

        final_zip = f"outputs/{task_id}.zip"
        shutil.make_archive(final_zip.replace(".zip", ""), "zip", out_dir)

        tasks[task_id]["status"] = "done"
        tasks[task_id]["result"] = final_zip

    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)


# ---------------------------------------------------
# MODELS
# ---------------------------------------------------
class UrlInput(BaseModel):
    url: str


# ---------------------------------------------------
# ROUTES
# ---------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/process_url")
async def process_url(data: UrlInput):
    url = data.url
    task_id = uuid.uuid4().hex

    os.makedirs("downloads", exist_ok=True)
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("work", exist_ok=True)

    zip_path = f"downloads/{task_id}.zip"

    # Download ZIP
    r = requests.get(url, stream=True)
    if r.status_code != 200:
        return {"error": "Failed to download file. Check your link."}

    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            f.write(chunk)

    # Start background processing
    tasks[task_id] = {"status": "queued"}
    threading.Thread(target=process_zip_worker, args=(task_id, zip_path)).start()

    return {"task_id": task_id}


@app.get("/status/{task_id}")
def check_status(task_id: str):
    return tasks.get(task_id, {"status": "not_found"})


@app.get("/download/{task_id}")
def download(task_id: str):
    t = tasks.get(task_id)
    if not t or "result" not in t:
        return {"error": "Not ready"}

    return FileResponse(t["result"], filename=f"{task_id}.zip")
