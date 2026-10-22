# 计算过程图解（交通进入搜索 + Voi 换电日）

| 文件 | 用途 | 怎么来的 |
|---|---|---|
| `walkthrough_zh.html` | **中文成品**，双击即可离线打开，可直接发给别人 | `build_viz` 生成，不要手改 |
| `walkthrough_en.html` | **英文成品**，同上 | `build_viz` 生成，不要手改 |
| `src/page_zh.html` | 中文页面源码：正文、样式、画图脚本 | 手工编辑 |
| `src/page_en_text.html` | 英文页面的正文和样式 | 手工编辑 |
| `src/viz_data.json` | 图表数据（在 H00、M00 两个实例上重新求解得到） | `export_viz` 生成 |

## 更新网页

在算法部分的根目录（README.md 所在的文件夹）下运行：

```bash
.venv/Scripts/python -m experiments.export_viz   # 约 5 分钟：重算 src/viz_data.json（算法改了才需要）
.venv/Scripts/python -m experiments.build_viz    # 几秒：生成两个成品（同时完成英文翻译）
```

只改了网页文字时，跳过第一条。改了 `src/page_zh.html` 里画图脚本的中文文字，`build_viz` 会报出没有英文对照的那句，到 `experiments/translate_viz.py` 的 `PAIRS` 里补一对即可。
