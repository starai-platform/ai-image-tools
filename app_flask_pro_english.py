"""
🎨 电商主图 AI 重构工具 - Flask Web API + 前端
支持：文件夹处理 + 口味识别 + 1:1 比例 + 目录结构保留 + 英文文件名输出
"""

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
import argparse
import os
import io
import threading
import uuid
import webbrowser
from pathlib import Path
from PIL import Image
import base64
import re
import time
import requests
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
from typing import Optional, Dict, Tuple
from urllib.parse import urlsplit
from werkzeug.serving import make_server

from image_presets import EditSettings, MAX_BRAND_TEXT, MAX_CUSTOM_REQUIREMENTS

# ==================== Flask 应用初始化 ====================
app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = './uploads'
app.config['OUTPUT_FOLDER'] = './output_main_webp'
app.config['SKIP_HUMAN_FOLDER'] = './skipped_human'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
os.makedirs(app.config['SKIP_HUMAN_FOLDER'], exist_ok=True)

# 存储任务状态
tasks = {}
tasks_lock = threading.Lock()
folder_dialog_lock = threading.Lock()

# ==================== 口味库定义（用于识别和提示词，不影响文件名） ====================
FLAVOR_DATABASE = {
    "strawberry_ice": {
        "keywords": ["strawberry", "strawberry-ice", "strawberry_ice", "berry_ice"],
        "style": "Fresh, cool aesthetic with icy crystalline effects. Showcase fresh strawberries with ice crystals, frozen water droplets, and frosty effects. Color palette: pink, cool white, light blue. Temperature: extremely cold.",
        "elements": "Fresh strawberries, transparent ice crystals, frost effects, water vapor"
    },
    "blueberry_mint": {
        "keywords": ["blueberry", "mint", "blueberry_mint", "blueberry-mint"],
        "style": "Cool, refreshing aesthetic with herbal freshness. Display blueberries combined with mint leaves, ice crystal textures, and morning dew. Color palette: deep blue, mint green, sky blue. Temperature: cold and refreshing.",
        "elements": "Blueberries, mint leaves, ice textures, morning dew, fresh vapor"
    },
    "grape_ice": {
        "keywords": ["grape", "grape-ice", "grape_ice"],
        "style": "Elegant, cool aesthetic with luxurious feeling. Show crystalline grape berries with ice effects, light reflections, and cold mist. Color palette: deep purple, light purple, sky blue. Temperature: extremely cold.",
        "elements": "Lustrous grapes, ice crystals, light reflections, cold vapor"
    },
    "mint": {
        "keywords": ["mint", "menthol", "cool"],
        "style": "Fresh, invigorating aesthetic. Focus on mint leaves with vein textures, morning dew, and green freshness. Color palette: mint green, grass green, white. Temperature: cool.",
        "elements": "Mint leaves, leaf veins, morning dew, fresh green vegetation"
    },
    "watermelon": {
        "keywords": ["watermelon", "watermelon_slice"],
        "style": "Juicy, summery aesthetic. Display watermelon slices with fresh moisture, watermelon seeds, and sunlight effects. Color palette: bright red, green, golden. Temperature: cool and refreshing.",
        "elements": "Watermelon slices, seeds, fresh moisture, sunlight effects"
    },
    "lemon": {
        "keywords": ["lemon"],
        "style": "Fresh, citrus aesthetic with sunny feeling. Show lemon slices, bright yellow color, fresh feeling, and sunlight reflections. Color palette: bright yellow, gold, green. Temperature: moderate.",
        "elements": "Lemon slices, fresh citrus, sunlight reflections, vibrant energy"
    },
    "mango": {
        "keywords": ["mango"],
        "style": "Sweet, tropical aesthetic. Display mango shape with golden color, glossy finish, and tropical feeling. Color palette: orange, golden, warm tones. Temperature: warm.",
        "elements": "Mango form, golden luster, glossy finish, tropical vibes"
    },
}

UNIFIED_STYLE = (
    "Center the product cleanly with balanced white-space margins on a sleek, "
    "minimalist matte light-gray architectural stone podium against a soft neutral "
    "light-gray studio gradient background. Apply fresh, diffused studio lighting from "
    "the upper left with a subtle, realistic contact shadow at the base. "
    "Photorealistic commercial e-commerce main product photo, crisp focus, no extra text, no props."
)


# ==================== 核心函数 ====================

def extract_flavor_from_filename(filename: str) -> Optional[Tuple[str, Dict]]:
    """识别文件名中的口味（用于生成对应的视觉提示词，不影响文件名）"""
    filename_lower = filename.lower().replace(' ', '_').replace('-', '_')

    for flavor_key, flavor_info in FLAVOR_DATABASE.items():
        for keyword in flavor_info["keywords"]:
            if keyword.lower() in filename_lower:
                return (flavor_key, flavor_info)

    return None


def generate_flavor_aware_prompt(category: str, flavor_info: Optional[Dict] = None) -> str:
    """根据分类和口味生成提示词"""
    base_prompts = {
        "single_product": f"Edit this image into a clean commercial e-commerce main product photo (1:1 square format). {UNIFIED_STYLE}",
        "poster_spec": f"Edit this promotional poster into a clean commercial e-commerce main product photo (1:1 square format). {UNIFIED_STYLE}",
        "human_model": f"Extract ONLY the vape device from this lifestyle photo and turn it into a clean e-commerce main product photo (1:1 square format). {UNIFIED_STYLE}",
        "universal": f"Edit this image into a clean commercial e-commerce main product photo (1:1 square format). {UNIFIED_STYLE}",
    }

    base = base_prompts.get(category, base_prompts["universal"])

    if flavor_info:
        return base + f"\n\nFLAVOR-AWARE: {flavor_info['style']}"

    return base


def clean_filename(name: str) -> str:
    """
    规范化文件名 - 输出始终为纯英文格式（无中文）

    示例：
    "strawberry_ice_01.png" → "strawberry-ice-01.webp"
    "IGET_BAR_PRO_blueberry_mint.jpg" → "iget-bar-pro-blueberry-mint.webp"
    "image (copy) 250x250.png" → "image-copy.webp"
    """
    stem = os.path.splitext(name)[0]

    # 去掉 WordPress 缩略图尺寸后缀
    stem = re.sub(r'-\d+x\d+.*', '', stem)

    # 转换为小写
    stem = stem.lower()

    # 规范化特殊字符和空格 → 横杠
    stem = re.sub(r'[\s()（）【】\[\]_]+', '-', stem)

    # 移除 Windows 不允许的字符
    stem = re.sub(r'[<>:"/\\|?*]', '', stem)

    # ✅ 移除所有非 ASCII 字符（包括中文）
    stem = stem.encode('ascii', 'ignore').decode('ascii')

    # 合并多个连续的横杠
    stem = re.sub(r'-+', '-', stem)
    stem = stem.strip('-')

    if not stem:
        stem = 'product'

    return f"{stem}.webp"


def classify_image(client, in_path: str, model: str = "gpt-4o-mini") -> str:
    """分类图片"""
    try:
        with Image.open(in_path) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=75)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=15,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this product image into exactly ONE label:\n- human_model: contains a person, face, mouth, or hand holding the product\n- poster_spec: contains specification icons, feature text lists, or product+box promotional layout\n- single_product: a single product shot (plain, or with fruits/ice/splashes/graphics)\nReply with ONLY the label name."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
        )
        label = resp.choices[0].message.content.strip().lower()
        for key in ("human_model", "poster_spec", "single_product"):
            if key in label:
                return key
    except:
        pass
    return "universal"


def process_image_task(client, in_path, output_dir, skip_human_dir, config, settings, rel_path_in):
    """处理单张图片"""
    file_name = os.path.basename(in_path)
    new_name = clean_filename(file_name)
    rel_dir = os.path.dirname(rel_path_in)
    out_path = os.path.join(output_dir, rel_dir, new_name)
    rel_out = os.path.relpath(out_path, output_dir).replace(os.sep, "/")

    if os.path.isfile(out_path):
        return {"status": "SKIPPED", "message": f"已有结果：{rel_path_in}", "output": rel_out}

    skip_human = config.get("skip_human", True) and skip_human_dir
    category = "universal"
    if settings.preset == "standard" or skip_human:
        category = classify_image(client, in_path, config.get("vision_model") or "gpt-4o-mini")

    # 隔离真人模特图
    if category == "human_model" and skip_human:
        skip_path_dir = os.path.join(skip_human_dir, rel_dir)
        os.makedirs(skip_path_dir, exist_ok=True)
        shutil.copy2(in_path, os.path.join(skip_path_dir, file_name))
        return {"status": "SKIPPED", "message": f"已隔离真人模特图：{rel_path_in}"}

    flavor = extract_flavor_from_filename(file_name) if settings.preset == "standard" else None
    prompt = settings.prompt(generate_flavor_aware_prompt(category, flavor[1] if flavor else None))

    # AI 重绘（3 次重试）
    for attempt in range(3):
        try:
            with open(in_path, "rb") as img_file:
                resp = client.images.edit(
                    model=config.get("image_model") or "gpt-image-2.5-sunburst",
                    image=img_file,
                    prompt=prompt,
                    size="1024x1024",  # ✅ 固定 1:1 正方形
                    quality="high",
                    extra_body={"moderation": "low"},
                )

            item = resp.data[0]
            if getattr(item, "b64_json", None):
                img_bytes = base64.b64decode(item.b64_json)
            elif getattr(item, "url", None):
                img_bytes = requests.get(item.url, timeout=60).content
            else:
                raise ValueError("No b64_json or url returned")

            # 保存输出
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

            # 确保 1:1 正方形
            if img.size != (1024, 1024):
                img = img.resize((1024, 1024), Image.Resampling.LANCZOS)

            img.save(out_path, format="WEBP", quality=85, method=6)

            return {"status": "SUCCESS", "message": f"{rel_path_in} → {rel_out}", "output": rel_out}

        except Exception as e:
            err = str(e)
            if "safety" in err.lower() or "moderation" in err.lower():
                return {"status": "BLOCKED", "message": f"API 内容审核拦截：{rel_path_in}"}
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                return {"status": "FAILED", "message": f"{rel_path_in}: {err[:60]}"}


def collect_images_from_folder(folder_path: str):
    """递归收集文件夹中的所有图片"""
    exts = (".jpg", ".jpeg", ".png", ".webp")
    result = []

    for dirpath, _, filenames in os.walk(folder_path):
        for fn in sorted(filenames):
            if fn.lower().endswith(exts):
                full_path = os.path.join(dirpath, fn)
                rel_path = os.path.relpath(full_path, folder_path)
                result.append({
                    "full_path": full_path,
                    "rel_path": rel_path,
                    "name": fn
                })

    return result


def normalize_folder_path(path: str) -> str:
    path = path.strip()
    if len(path) >= 2 and path[0] == path[-1] == '"':
        path = path[1:-1]
    if os.name == 'nt' and re.fullmatch(r'[A-Za-z]:', path):
        path += os.sep
    return path


def choose_local_folder(initial_dir: str) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        if os.name == 'nt':
            # A mapped foreground owner keeps the native dialog accessible from the desktop.
            root.title('源文件夹选择器')
            root.geometry('1x1')
            root.attributes('-topmost', True)
            root.update()
            root.lift()
            root.focus_force()
        else:
            root.withdraw()
        return filedialog.askdirectory(
            parent=root, initialdir=initial_dir, title='选择源文件夹', mustexist=True
        )
    finally:
        root.destroy()


# ==================== Flask 路由 ====================

@app.route('/', methods=['GET'])
def index():
    """前端主页"""
    return render_template('index_pro.html', max_brand_text=MAX_BRAND_TEXT,
                           max_custom_requirements=MAX_CUSTOM_REQUIREMENTS)


@app.route('/api/pick_source_folder', methods=['POST'])
def pick_source_folder():
    local_hosts = {'127.0.0.1', 'localhost', '::1'}
    origin = request.host_url.rstrip('/')
    if (request.remote_addr not in {'127.0.0.1', '::1'}
            or urlsplit(origin).hostname not in local_hosts
            or request.headers.get('Origin') != origin):
        return jsonify(message='请在运行工具的电脑上打开页面，或手动输入目录。'), 403

    data = request.get_json(silent=True)
    folder_path = data.get('folder_path', '') if isinstance(data, dict) else ''
    initial_dir = normalize_folder_path(folder_path) if isinstance(folder_path, str) else ''
    if not os.path.isdir(initial_dir):
        initial_dir = os.getcwd()

    if not folder_dialog_lock.acquire(blocking=False):
        return jsonify(message='目录选择窗口已打开。'), 409
    try:
        selected_path = choose_local_folder(os.path.abspath(initial_dir))
    except Exception:
        app.logger.exception('Unable to open the local folder dialog')
        return jsonify(message='无法打开目录选择窗口，请手动输入路径。'), 503
    finally:
        folder_dialog_lock.release()
    return jsonify(folder_path=os.path.normpath(selected_path) if selected_path else None)


@app.route('/api/scan_folder', methods=['POST'])
def scan_folder():
    """扫描文件夹"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "请填写源文件夹路径。"}), 400
    folder_path = data.get('folder_path', './raw_images')

    if not isinstance(folder_path, str):
        return jsonify({"status": "error", "message": "请填写源文件夹路径。"}), 400
    folder_path = normalize_folder_path(folder_path)
    if not os.path.isdir(folder_path):
        return jsonify({"status": "error", "message": "找不到源文件夹。"}), 400

    images = collect_images_from_folder(folder_path)
    folder_tree = {}
    for item in images:
        folder = os.path.dirname(item['rel_path']) or '.'
        folder_tree.setdefault(folder, []).append(item['name'])

    return jsonify({
        "status": "success",
        "count": len(images),
        "images": images,
        "folder_path": folder_path,
        "folder_tree": folder_tree,
    })


@app.route('/api/process_folder', methods=['POST'], defaults={'task_id': None})
@app.route('/api/process_folder/<task_id>', methods=['POST'])
def process_folder(task_id):
    """提交后台任务，立即返回供页面轮询。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('config', {}), dict):
        return jsonify({"status": "error", "message": "无效的任务配置。"}), 400

    config = data.get('config', {})
    images = data.get('images', [])
    source_dir = data.get('source_dir', '')
    output_root = data.get('output_dir', app.config['OUTPUT_FOLDER'])
    skip_human_dir = data.get('skip_human_dir', app.config['SKIP_HUMAN_FOLDER'])
    try:
        settings = EditSettings(
            preset=config.get('preset', 'standard'),
            custom_requirements=config.get('custom_requirements', ''),
            brand_text=config.get('brand_text', ''),
        )
        if not isinstance(images, list) or not images:
            raise ValueError("请先扫描并选择有图片的源文件夹。")
        for item in images:
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ('full_path', 'rel_path')):
                raise ValueError("图片路径无效，请重新扫描。")
            relative = Path(item['rel_path'])
            if relative.anchor or '..' in relative.parts or relative.name != Path(item['full_path']).name:
                raise ValueError("图片路径无效，请重新扫描。")
        if not isinstance(output_root, str) or not output_root.strip() or not isinstance(skip_human_dir, str):
            raise ValueError("请填写有效的输出目录和隔离目录。")
        if not isinstance(source_dir, str):
            raise ValueError("源文件夹路径无效，请重新扫描。")
        workers = config.get('max_workers', 3)
        if type(workers) is not int or not 1 <= workers <= 10:
            raise ValueError("并发线程数须为 1 至 10 之间的整数。")
        client = OpenAI(base_url=config.get('base_url'), api_key=config.get('api_key'), timeout=60)
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)[:200]}), 400

    task_id = task_id or uuid.uuid4().hex
    output_dir = os.path.abspath(settings.output_directory(output_root, source_dir))
    task = {
        "status": "processing",
        "stats": {"SUCCESS": 0, "FAILED": 0, "SKIPPED": 0, "BLOCKED": 0},
        "total": len(images),
        "logs": [],
        "output_dir": output_dir,
        "files": set(),
    }
    with tasks_lock:
        if task_id in tasks:
            client.close()
            return jsonify({"status": "error", "message": "该任务已提交。"}), 409
        tasks[task_id] = task

    threading.Thread(
        target=run_folder_task,
        args=(task, client, workers, images, skip_human_dir, config, settings),
        daemon=True,
    ).start()
    return jsonify({"status": "ok", "task_id": task_id, "output_dir": output_dir})


def run_folder_task(task, client, workers, images, skip_human_dir, config, settings):
    try:
        with client, ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_image_task,
                    client,
                    item['full_path'],
                    task['output_dir'],
                    skip_human_dir,
                    config,
                    settings,
                    item['rel_path'],
                ): item['rel_path'] for item in images
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "FAILED", "message": f"{futures[future]}: {str(exc)[:120]}"}
                with tasks_lock:
                    task['stats'][result['status']] += 1
                    task['logs'].append({"status": result['status'], "message": result['message']})
                    if 'output' in result:
                        task['files'].add(result['output'])
        with tasks_lock:
            task['status'] = 'completed'
    except Exception as exc:
        with tasks_lock:
            task['status'] = 'failed'
            task['error'] = str(exc)[:200]


@app.route('/api/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
        if task is None:
            return jsonify({"status": "error", "message": "找不到该任务。"}), 404
        return jsonify({
            "status": task['status'],
            "stats": task['stats'],
            "logs": task['logs'][-50:],
            "total": task['total'],
            "error": task.get('error'),
        })


@app.route('/api/outputs/<task_id>')
def list_task_outputs(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
        if task is None:
            abort(404)
        return jsonify(files=sorted(task['files']))


@app.route('/api/preview/<task_id>/<path:filename>')
def preview_task_output(task_id, filename):
    with tasks_lock:
        task = tasks.get(task_id)
        if task is None or filename not in task['files']:
            abort(404)
        output_dir = task['output_dir']
    response = send_from_directory(output_dir, filename)
    response.cache_control.no_store = True
    return response


@app.route('/api/verify', methods=['POST'])
def verify_api():
    """验证 API 连接"""
    data = request.json or {}
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', '')

    if not api_key or not base_url:
        return jsonify({"status": "error", "message": "api_key and base_url are required"}), 400

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=10)
        client.models.list()
        return jsonify({"status": "success", "message": "Connection OK"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:200]}), 400


@app.route('/api/models', methods=['POST'])
def list_models():
    """获取上游渠道的模型列表，按类型分组返回"""
    data = request.json or {}
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', '')

    if not api_key or not base_url:
        return jsonify({"status": "error", "message": "api_key and base_url are required"}), 400

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=15)
        models_resp = client.models.list()
        all_ids = sorted([m.id for m in models_resp.data])

        # 按关键词简单分组，方便前端展示
        image_models = [m for m in all_ids if any(k in m.lower() for k in
                        ['image', 'dall-e', 'gpt-image', 'flux', 'sd', 'midjourney', 'ideogram'])]
        vision_models = [m for m in all_ids if any(k in m.lower() for k in
                         ['gpt-4', 'gpt-4o', 'claude', 'gemini', 'vision'])]
        other_models = [m for m in all_ids if m not in image_models and m not in vision_models]

        return jsonify({
            "status": "success",
            "all": all_ids,
            "image_models": image_models,
            "vision_models": vision_models,
            "other_models": other_models,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:200]}), 400


@app.route('/api/config', methods=['GET', 'POST'])
def config():
    """配置管理"""
    if request.method == 'POST':
        # 保存配置
        return jsonify({"status": "ok"})
    else:
        # 获取默认配置
        return jsonify({
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("IMG2IMG_BASE_URL", ""),
            "vision_model": "gpt-4o-mini",
            "image_model": "gpt-image-2.5-sunburst",
            "max_workers": 3,
            "skip_human": True
        })


def launch_web_ui():
    """Bind a local port before opening this instance in the browser."""
    with make_server('127.0.0.1', 0, app, threaded=True) as server:
        url = f'http://127.0.0.1:{server.server_port}/'
        print(f'  Open browser: {url}', flush=True)
        threading.Thread(target=webbrowser.open_new_tab, args=(url,), daemon=True).start()
        server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--open-browser', action='store_true',
                        help='Open the local interface on an available port.')
    if parser.parse_args().open_browser:
        launch_web_ui()
    else:
        app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
