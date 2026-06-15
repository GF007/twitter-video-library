# 分镜师视觉语义打标规则

这一轮打标是给分镜师检索素材用的“视觉语义 tag”。它不替代现有主分类，也不替代 Twitter 原始 tag。

## 字段边界

- `curated.category`：继续只表示主分类，沿用 `动画分镜`、`动画片段`、`其他`；其中 `其他` 是主分类合并后的本地排除/复核桶，不进入可见资源库。公开仓库只保留规则，不保留实际素材路径、删除清单或远端路径。
- `curated.tags`：继续表示现有自动分类辅助 tag，例如 `rough-layout`、`action`、`fx`。
- `source_tags`：继续保留 Twitter/X 原始 tag，不做清洗覆盖。
- `curated.storyboard_tags`：新增字段，只放这套分镜语义 tag。
- `curated.storyboard_confidence`：新增字段，取 `high`、`medium`、`low`。
- `curated.storyboard_notes`：新增字段，只写很短的判断说明或风险。

## 单帧可判断范围

只根据当前中间帧缩略图和 contact sheet 画面判断。可以使用 manifest 里的作者、已有类别、已有 tags、推文文本作为轻量上下文，但不能用它们替代画面判断。

可以判断：

- 景别和构图：远景、中景、近景、特写、对称、中心构图、三分构图、留白、前景框景、层次。
- 机位和视角：高角度、低角度、俯视、倾斜、肩越、主观视角。
- 人物调度：双人、多人、群体、对话、对峙、追逐、战斗、明确动作线、动态姿态、肢体表演、表情表演。
- 动作和特效瞬间：运动模糊、速度线、打击瞬间、特效强调、镜头运动暗示。
- 镜头功能：建立镜头、反应镜头、插入镜头、过渡镜头。

不要判断：

- 不能从单帧确认的剧情、角色身份、镜头前后因果。
- 只在推文文本里出现、画面上看不出来的内容。
- 过细的一次性道具或角色名。

## 受控 tag 表

### 景别

- `extreme-wide-shot`：极远景，人物很小或主要展示环境。
- `wide-shot`：远景，完整展示场景和人物空间关系。
- `full-shot`：全身镜头，人物全身或接近全身是主体。
- `medium-shot`：中景，人物半身或上半身为主体。
- `close-up`：近景，脸、手、道具或局部动作占主导。
- `extreme-close-up`：极近特写，局部细节占满画面。

### 机位和视角

- `high-angle`：高机位向下看，但不是正俯视。
- `low-angle`：低机位向上看。
- `overhead-view`：俯视或接近正俯视。
- `dutch-angle`：明显倾斜构图。
- `over-shoulder`：肩越或背后前景看向另一主体。
- `pov-shot`：明显主观视角或第一人称视角。

### 构图和空间

- `strong-silhouette`：主体轮廓很清楚，便于读动作。
- `center-composition`：主体明显居中。
- `symmetry`：画面结构明显左右或轴线对称。
- `rule-of-thirds`：主体明显落在三分线/三分点附近。
- `foreground-framing`：前景遮挡或框住主体。
- `frame-within-frame`：门窗、屏幕、洞口等形成画中框。
- `depth-layers`：前中后景层次清楚。
- `negative-space`：大面积留白或空场服务情绪/调度。

### 人物调度和表演

- `two-shot`：两个主要角色同框。
- `group-staging`：三人以上有明确站位关系。
- `crowd-staging`：大量人群或队列。
- `dialogue-staging`：画面明显为对话调度。
- `confrontation`：对峙、冲突前压、敌我关系清晰。
- `chase-staging`：追逐或逃跑调度明显。
- `fight-staging`：打斗、格挡、攻击、防御姿势明显。
- `clear-line-of-action`：动作方向和力量线很清楚。
- `dynamic-pose`：姿态张力强，适合作动作参考。
- `gesture-acting`：手势或身体表演是画面重点。
- `facial-acting`：表情变化或脸部表演是画面重点。

### 动作和特效线索

- `motion-blur`：画面有明显运动模糊。
- `speed-lines`：有速度线、集中线或漫画式运动线。
- `impact-moment`：打击、碰撞、落地、爆发的关键瞬间。
- `fx-emphasis`：烟、火、光、能量、水、爆炸等特效是画面重点。
- `camera-move-cue`：单帧中可见摇移、推拉、旋转、跟拍等镜头运动暗示。

### 镜头功能

- `establishing-shot`：建立环境、地点或空间关系。
- `reaction-shot`：主体明显在回应前一动作/情绪。
- `insert-shot`：道具、手部、屏幕、局部信息是镜头重点。
- `transition-shot`：黑白场、遮挡、转场、抽象过渡帧。
- `unclear-frame`：画面黑、糊、遮挡严重或无法判断。

## 输出规则

- 每条记录输出 2-6 个 `storyboard_tags`。
- 如果画面不可读，允许只输出 `["unclear-frame"]`。
- tag 必须来自受控 tag 表，全部小写短横线格式。
- 优先选择对分镜师检索有价值的 tag，不要把所有可能沾边的 tag 都写上。
- `storyboard_notes` 最多一句话，不写剧情猜测。
- 不输出或修改 `category`、`tags`、`source_tags`。

JSONL 示例：

```json
{"key":"S001-I001","storyboard_tags":["wide-shot","depth-layers","establishing-shot"],"storyboard_confidence":"high","storyboard_notes":"环境和空间关系清楚"}
{"key":"S001-I002","storyboard_tags":["close-up","facial-acting","reaction-shot"],"storyboard_confidence":"medium","storyboard_notes":"脸部表演占主导"}
```
