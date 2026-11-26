#!/usr/bin/env python3
"""
🎨 电商主图 AI 重构工具 - 命令行版本
支持：文件夹处理 + 口味识别 + 1:1 比例 + 目录结构保留 + 英文文件名输出
"""

import os
import sys
import argparse
import json
import base64
import re
import time
from pathlib import Path
from datetime import datetime
from PIL import Image
import io
from typing import Optional, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import shutil

try:
    from openai import OpenAI
except ImportError:
    print("❌ 错误: 需要安装 openai 库")
    print("   运行: pip install openai pillow --break-system-packages")
    sys.exit(1)

# ==================== 配置 ====================

FLAVOR_DATABASE = {
    "strawberry_ice": {
        "keywords": ["strawberry", "strawberry-ice", "strawberry_ice"],
        "style": "Fresh, cool aesthetic with icy crystalline effects"
    },
    "blueberry_mint": {
        "keywords": ["blueberry", "mint", "blueberry_mint", "blueberry-mint"],
        "style": "Cool, refreshing aesthetic with herbal freshness"
    },
    "grape_ice": {
        "keywords": ["grape", "grape-ice", "grape_ice"],
        "style": "Elegant, cool aesthetic with luxurious feeling"
    },
    "mint": {
        "keywords": ["mint", "menthol"],
        "style": "Fresh, invigorating aesthetic"
    },
    "watermelon": {
        "keywords": ["watermelon"],
        "style": "Juicy, summery aesthetic"
    },
    "lemon": {
        "keywords": ["lemon"],
        "style": "Fresh, citrus aesthetic with sunny feeling"
    },
    "mango": {
        "keywords": ["mango"],
        "style": "Sweet, tropical aesthetic"
    },
}

UNIFIED_STYLE = (
    "Center the product cleanly with balanced white-space margins on a sleek, "
    "minimalist matte light-gray architectural stone podium against a soft neutral "
    "light-gray studio gradient background."
)


# ==================== 核心函数 ====================

def extract_flavor(filename: str) -> Optional[Tuple[str, Dict]]:
    """识别文件名中的口味"""
    filename_lower = filename.lower().replace(' ', '_').replace('-', '_')
    for flavor_key, flavor_info in FLAVOR_DATABASE.items():
        for keyword in flavor_info["keywords"]:
            if keyword.lower() in filename_lower:
                return (flavor_key, flavor_info)
    return None


def clean_filename(name: str) -> str:
    """规范化文件名 - 输出纯英文格式"""
    stem = os.path.splitext(name)[0]
    stem = re.sub(r'-\d+x\d+.*', '', stem)
    stem = stem.lower()
    stem = re.sub(r'[\s()（）【】\[\]_]+', '-', stem)
    stem = re.sub(r'[<>:"/\\|?*]', '', stem)
    stem = stem.encode('ascii', 'ignore').decode('ascii')  # ✅ 移除中文
    stem = re.sub(r'-+', '-', stem)
    stem = stem.strip('-')
    return f"{stem or 'product'}.webp"


def classify_image(client, image_path: str) -> str:
    """分类图片"""
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=75)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=15,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this product image: human_model, poster_spec, or single_product? Reply with ONLY the label."},
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


def generate_prompt(category: str, flavor_info: Optional[Dict] = None) -> str:
    """生成提示词"""
    base = f"Edit this image into a clean commercial e-commerce main product photo (1:1 square format). {UNIFIED_STYLE}"
    if flavor_info:
        return base + f"\n\nFLAVOR-AWARE: {flavor_info['style']}"
    return base


def process_image(client, in_path: str, output_dir: str, skip_human_dir: str, config: Dict, rel_path: str = None):
    """处理单张图片"""
    file_name = os.path.basename(in_path)
    new_name = clean_filename(file_name)

    # 计算输出路径
    if rel_path:
        rel_dir = os.path.dirname(rel_path)
        out_path = os.path.join(output_dir, rel_dir, new_name)
    else:
        out_path = os.path.join(output_dir, new_name)

    if os.path.exists(out_path):
        return {"status": "SKIPPED", "file": file_name, "reason": "already_exists"}

    # 分类
    category = classify_image(client, in_path)

    # 识别口味
    flavor_result = extract_flavor(file_name)
    flavor_info = flavor_result[1] if flavor_result else None

    # 隔离真人模特图
    if category == "human_model" and config.get("skip_human", True):
        if rel_path:
            rel_dir = os.path.dirname(rel_path)
            skip_path_dir = os.path.join(skip_human_dir, rel_dir)
        else:
            skip_path_dir = skip_human_dir

        os.makedirs(skip_path_dir, exist_ok=True)
        shutil.copy2(in_path, os.path.join(skip_path_dir, file_name))
        return {"status": "SKIPPED", "file": file_name, "reason": "human_model"}

    # 生成提示词
    prompt = generate_prompt(category, flavor_info)

    # 重试 3 次
    for attempt in range(3):
        try:
            with open(in_path, "rb") as img_file:
                resp = client.images.edit(
                    model=config.get("image_model", "gpt-image-2.5-sunburst"),
                    image=img_file,
                    prompt=prompt,
                    size="1024x1024",  # ✅ 固定 1:1
                    quality="high",
                    extra_body={"moderation": "low"},
                )

            item = resp.data[0]
            if getattr(item, "b64_json", None):
                img_bytes = base64.b64decode(item.b64_json)
            elif getattr(item, "url", None):
                img_bytes = __import__('requests').get(item.url, timeout=60).content
            else:
                raise ValueError("No response")

            # 保存
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            if img.size != (1024, 1024):
                img = img.resize((1024, 1024), Image.Resampling.LANCZOS)
            img.save(out_path, format="WEBP", quality=85, method=6)

            return {
                "status": "SUCCESS",
                "file": file_name,
                "output": os.path.relpath(out_path, output_dir),
                "flavor": flavor_result[0] if flavor_result else None
            }

        except Exception as e:
            err = str(e).lower()
            if "safety" in err or "moderation" in err:
                return {"status": "BLOCKED", "file": file_name, "reason": "content_policy"}
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                return {"status": "FAILED", "file": file_name, "reason": str(e)[:60]}

    return {"status": "FAILED", "file": file_name, "reason": "max_retries"}


def collect_images(folder_path: str):
    """收集文件夹中的所有图片"""
    exts = (".jpg", ".jpeg", ".png", ".webp")
    result = []

    for dirpath, _, filenames in os.walk(folder_path):
        for fn in sorted(filenames):
            if fn.lower().endswith(exts):
                full_path = os.path.join(dirpath, fn)
                rel_path = os.path.relpath(full_path, folder_path)
                result.append({"full_path": full_path, "rel_path": rel_path, "name": fn})

    return result


# ==================== 主函数 ====================

def main():
    parser = argparse.ArgumentParser(
        description="🎨 电商主图 AI 重构工具 - 命令行版本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法：

  1. 处理单个文件夹（使用环境变量配置）：
     python batch_product_main_cli.py --input ./raw_images --output ./output_main_webp

  2. 使用 API 密钥（从命令行传入）：
     python batch_product_main_cli.py --input ./raw_images \\
       --api-key sk-xxxx --base-url https://api.example.com

  3. 自定义设置：
     python batch_product_main_cli.py --input ./raw_images \\
       --output ./output --skip-human --max-workers 5

环境变量：
  OPENAI_API_KEY     - OpenAI API 密钥
  IMG2IMG_BASE_URL   - 中转站 Base URL
        """
    )

    parser.add_argument(
        '--input', type=str, default='./raw_images',
        help='输入文件夹路径 (默认: ./raw_images)'
    )
    parser.add_argument(
        '--output', type=str, default='./output_main_webp',
        help='输出文件夹路径 (默认: ./output_main_webp)'
    )
    parser.add_argument(
        '--skip-human-dir', type=str, default='./skipped_human',
        help='隔离真人模特图的文件夹 (默认: ./skipped_human)'
    )
    parser.add_argument(
        '--api-key', type=str, default=None,
        help='OpenAI API Key (默认从 OPENAI_API_KEY 环境变量读取)'
    )
    parser.add_argument(
        '--base-url', type=str, default=None,
        help='Base URL (默认从 IMG2IMG_BASE_URL 环境变量读取)'
    )
    parser.add_argument(
        '--skip-human', action='store_true', default=True,
        help='隔离真人模特图'
    )
    parser.add_argument(
        '--max-workers', type=int, default=3,
        help='最大并发数 (默认: 3)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='仅显示将要处理的文件，不执行处理'
    )

    args = parser.parse_args()

    # 读取配置
    api_key = args.api_key or os.getenv('OPENAI_API_KEY')
    base_url = args.base_url or os.getenv('IMG2IMG_BASE_URL')

    if not api_key or not base_url:
        print("❌ 错误: 需要 API Key 和 Base URL")
        print("   设置环境变量或使用 --api-key 和 --base-url 参数")
        sys.exit(1)

    # 验证输入文件夹
    if not os.path.isdir(args.input):
        print(f"❌ 错误: 输入文件夹不存在: {args.input}")
        sys.exit(1)

    # 收集图片
    print(f"\n📂 扫描文件夹: {args.input}")
    images = collect_images(args.input)
    print(f"✅ 找到 {len(images)} 张图片")

    if not images:
        print("❌ 未找到任何图片")
        sys.exit(0)

    # 显示文件夹结构
    print("\n📋 文件夹结构：")
    folders = defaultdict(list)
    for img in images:
        rel_dir = os.path.dirname(img['rel_path']) or '(root)'
        folders[rel_dir].append(img['name'])

    for folder in sorted(folders.keys()):
        count = len(folders[folder])
        print(f"   {folder:40} ({count} 张)")

    # 口味分析
    print("\n🎯 口味分析：")
    flavor_stats = defaultdict(int)
    for img in images:
        flavor_result = extract_flavor(img['name'])
        if flavor_result:
            flavor_stats[flavor_result[0]] += 1

    if flavor_stats:
        for flavor, count in sorted(flavor_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"   {flavor:20} {count:3} 张")
    else:
        print("   (未识别到已知口味)")

    # Dry run
    if args.dry_run:
        print("\n💡 Dry Run 模式 - 仅显示将要处理的文件")
        print(f"   输出目录: {args.output}")
        print(f"   真人模特隔离: {args.skip_human_dir}")
        print(f"   最大并发: {args.max_workers}")
        return

    # 确认
    print(f"\n⚙️ 配置：")
    print(f"   输出目录: {args.output}")
    print(f"   真人模特隔离: {args.skip_human_dir}")
    print(f"   最大并发: {args.max_workers}")
    print(f"\n🚀 开始处理 {len(images)} 张图片...")

    # 创建输出目录
    os.makedirs(args.output, exist_ok=True)
    os.makedirs(args.skip_human_dir, exist_ok=True)

    # 初始化客户端
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60)

    # 处理图片
    config = {
        "skip_human": args.skip_human,
        "image_model": "gpt-image-2.5-sunburst"
    }

    stats = {"SUCCESS": 0, "FAILED": 0, "SKIPPED": 0, "BLOCKED": 0}
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                process_image,
                client,
                img['full_path'],
                args.output,
                args.skip_human_dir,
                config,
                img['rel_path']
            ): img for img in images
        }

        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            status = result['status']
            stats[status] = stats.get(status, 0) + 1

            # 显示进度
            pct = (completed / len(images)) * 100
            print(f"[{completed:3}/{len(images)}] {pct:5.1f}% | {status:8} | {result['file']}")

    elapsed = time.time() - start_time

    # 统计汇总
    print(f"\n{'='*70}")
    print(f"📊 处理完成")
    print(f"{'='*70}")
    print(f"✅ 成功:    {stats.get('SUCCESS', 0):3} 张")
    print(f"❌ 失败:    {stats.get('FAILED', 0):3} 张")
    print(f"⏭️ 跳过:    {stats.get('SKIPPED', 0):3} 张")
    print(f"🚫 拦截:    {stats.get('BLOCKED', 0):3} 张")
    print(f"─────────────────")
    print(f"📈 总计:    {len(images):3} 张")
    print(f"⏱️ 耗时:    {elapsed:.1f} 秒")
    print(f"💰 成本:    ${stats.get('SUCCESS', 0) * 1.0005:.2f}")
    print(f"\n✅ 结果保存到: {args.output}")


if __name__ == '__main__':
    main()
