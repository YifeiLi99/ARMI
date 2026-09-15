# 32×32 像素头像候选

本目录为新候选，尚未替换安装图标。内置 image_gen 生成形象参考后，整理为固定网格、13 色调色板，并逐格调整紫宝石眼睛及高光。

- `avatar-32.json`：权威像素数据，`rows[y][x]` 为调色板下标，`-1` 为透明；坐标从左上角 0 开始。
- `avatar-32.png`：实际 32×32 PNG。
- `avatar-32.svg`：每个像素对应一个整数坐标的 1×1 色块。
- `avatar-preview.png`：16 倍放大的 512×512 预览，每格复制为 16×16 色块，无平滑插值。

生成参考提示：Redesign this character as an authentic tiny 32 by 32 pixel sprite head icon. The entire image is EXACTLY 32 logical columns and 32 logical rows of uniform square cells, enlarged nearest neighbor. Use only 12 flat solid colors plus transparent background. Every edge and shape must align to the SAME coarse square grid, no smaller details anywhere. Simplify radically into deliberate chunky pixel clusters, like a beautifully crafted small SNES inventory portrait. Silver-white hair with 2 lavender shadow shades, compact side ponytail on the right, a tiny teal green flower accent, purple amethyst eyes with one light pixel each, warm pale peach face with subtle blush, sweet closed smile. Head must occupy a compact centered silhouette with transparent margins. No gradients, antialiasing, texture, dithering, grid lines or letters.

生成参考并非实际 32×32 文件；本目录 PNG、JSON 与 SVG 才是落实后的网格。整数倍放大保持像素形状，非整数比例可能产生宽度不均。16×16 托盘稿需另行简化，不能假定缩小后细节不丢失。
