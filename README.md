# 电商主图 AI 重构工具

批量将电商产品图通过 AI 重绘，输出去元数据的 1:1 WebP 格式，规避原始图片侵权风险。

## 目录结构

```
img2img-skill/
├── raw_images/              ← 原图放这里（支持多层子文件夹）
├── output_main_webp/        ← 生成结果（自动按原目录结构保存）
├── skipped_human/           ← 被隔离的真人模特图
├── templates/
│   └── index_pro.html       ← Flask Web UI 前端
├── app_flask_pro_english.py ← Flask Web 服务
├── batch_product_main_cli.py← 命令行批处理工具
├── .env.local.example       ← 配置模板（复制为 .env.local 填入密钥）
├── start_web.bat            ← 一键启动 Web 界面
└── start_cli.bat            ← 一键启动命令行处理
```

---

## 第一步：配置密钥

复制配置模板，填入你的 API 信息：

```
.env.local.example → .env.local
```

编辑 `.env.local`：

```
OPENAI_API_KEY=sk-你的密钥
IMG2IMG_BASE_URL=https://你的中转站域名/v1
```

---

## 第二步：安装依赖

```bash
pip install flask flask-cors pillow openai requests -q
```

---

## 第三步：使用

### 方式 A：Web 界面（推荐）

双击 `start_web.bat`，浏览器打开 `http://localhost:5000`

**操作流程：**
1. 在配置页填入 API Key 和 Base URL
2. 在主页输入原图文件夹路径，点击扫描
3. 确认文件列表后点击开始处理
4. 实时查看进度和日志

### 方式 B：命令行

双击 `start_cli.bat`，或手动运行：

```bash
# 基础用法
python batch_product_main_cli.py --input ./raw_images

# 自定义输出目录
python batch_product_main_cli.py --input ./raw_images --output ./output_main_webp

# 增加并发（3-5 推荐）
python batch_product_main_cli.py --input ./raw_images --max-workers 5

# 仅预览，不处理
python batch_product_main_cli.py --input ./raw_images --dry-run
```

---

## 核心功能

**图片分类处理**

工具会自动识别图片类型并分别处理：
- `single_product`：单品图（带水果/冰块装饰）→ 删除装饰，重建产品
- `poster_spec`：规格海报 → 删除文字信息，只保留产品
- `human_model`：真人模特图 → 隔离到 `skipped_human/`，不处理
- `universal`：混合类型 → 通用处理

**口味感知重构**

从文件名自动识别口味，生成对应视觉风格的图片：

| 文件名包含 | 识别口味 | 视觉效果 |
|-----------|---------|---------|
| strawberry / strawberry-ice | Strawberry Ice | 粉红色调 + 冰晶效果 |
| blueberry / mint / blueberry-mint | Blueberry Mint | 蓝绿色调 + 薄荷清爽 |
| grape / grape-ice | Grape Ice | 深紫色调 + 冷艳光泽 |
| watermelon | Watermelon | 红绿色调 + 多汁夏日感 |
| lemon | Lemon | 金黄色调 + 阳光感 |
| mango | Mango | 橙金色调 + 热带感 |
| mint / menthol | Mint | 青绿色调 + 提神感 |

未识别到口味时使用通用提示词处理。

**输出规格**

- 格式：WebP（彻底清除 EXIF/IPTC 元数据）
- 尺寸：1024×1024（1:1 正方形，电商主图标准）
- 质量：85（文件小、画质佳）
- 文件名：纯英文，无中文字符

**目录结构保留**

```
raw_images/IGET/BAR-PRO/strawberry-ice-01.png
        ↓
output_main_webp/IGET/BAR-PRO/strawberry-ice-01.webp
```

---

## 成本参考

每张图处理费用约 $1.0005（分类 $0.0005 + 重绘 $1.00）。

| 数量 | 预估成本 | 预估时间（3并发） |
|------|---------|----------------|
| 50 张 | ~$50 | ~20 分钟 |
| 100 张 | ~$100 | ~40 分钟 |
| 500 张 | ~$500 | ~3 小时 |

---

## 常见问题

**Q: 处理中途中断怎么办？**
重新运行即可，已生成的文件会自动跳过（断点续传）。

**Q: 某张图被风控拦截怎么办？**
日志中会标记 `BLOCKED`，该图跳过不影响其他图片。

**Q: 如何提高处理速度？**
调大 `--max-workers`（建议不超过 5，避免 API 限流）。

**Q: 真人模特图是否可以处理？**
默认隔离到 `skipped_human/`。如需处理，在命令行加 `--no-skip-human`，但成功率较低。
