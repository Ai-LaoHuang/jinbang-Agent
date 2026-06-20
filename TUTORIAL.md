# 零基础安装使用教程

> 不需要懂编程，跟着步骤走，10 分钟搞定。

---

## 第一步：安装 Python

你的电脑需要 Python 3.10 或更高版本。

### 检查是否已安装

按 `Win + R`，输入 `cmd`，回车。在黑色窗口里输入：

```
python --version
```

如果显示 `Python 3.10.x` 或 `Python 3.11.x` 等 → **已安装，跳到第二步**。

如果显示"不是内部命令"→ 继续往下看。

### 下载安装

1. 打开 https://www.python.org/downloads/
2. 点击黄色大按钮 **Download Python**
3. 双击下载的文件
4. ⚠️ **重要**：勾选底部的 **"Add Python to PATH"**
5. 点击 **Install Now**
6. 等安装完成，关闭窗口

---

## 第二步：获取项目

### 方式A：GitHub 下载（推荐）

1. 打开项目 GitHub 页面
2. 点击绿色 **Code** 按钮 → **Download ZIP**
3. 解压到你喜欢的目录（比如桌面）

### 方式B：git clone

```bash
git clone https://github.com/你的用户名/xuefeng-agent.git
cd xuefeng-agent
```

---

## 第三步：安装依赖

打开项目文件夹，在地址栏输入 `cmd` 回车。

![在文件夹地址栏输入cmd](https://i.imgur.com/placeholder.png)

在黑色窗口里输入：

```bash
pip install openai pywin32
```

等待安装完成（1-2分钟）。

---

## 第四步：获取 API Key

Agent 需要一个 AI 模型来运行。推荐用 DeepSeek（便宜、效果好）。

### 获取 DeepSeek API Key（推荐）

1. 打开 https://platform.deepseek.com/
2. 注册/登录
3. 点击左侧 **API Keys**
4. 点击 **创建 API Key**，复制保存

DeepSeek 价格很低，聊几百次也就几毛钱。

### 其他模型

| 模型 | 注册地址 | 费用 |
|------|---------|------|
| 通义千问 | https://dashscope.aliyun.com/ | 有免费额度 |
| 智谱 GLM | https://open.bigmodel.cn/ | 有免费额度 |
| OpenAI GPT | https://platform.openai.com/ | 较贵 |

---

## 第五步：配置

在项目文件夹里：

1. 找到 `.env.example` 文件
2. 复制一份，重命名为 `.env`（把 `.example` 删掉）
3. 用记事本打开 `.env`
4. 填入你的 API Key：

```
LLM_API_KEY=sk-你的真实key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

保存，关闭。

### 快捷切换（可选）

如果你用别的模型，不想记 base_url 和 model 名，可以用 `LLM_PROVIDER`：

```
# 用通义千问
LLM_PROVIDER=qwen
LLM_API_KEY=sk-你的key

# 用智谱
LLM_PROVIDER=glm
LLM_API_KEY=你的key
```

支持的 `LLM_PROVIDER` 值：`deepseek` `qwen` `glm` `moonshot` `openai` `ollama`

---

## 第六步：启动

### Windows

双击项目文件夹里的 **`启动.bat`**。

### 其他系统

```bash
python agent.py
```

看到"✅ 连接成功"就说明一切就绪。

---

## 第七步：开始使用

直接打字描述你的情况，比如：

```
湖北物理类580分，位次28000，普通家庭，想去武汉学计算机
```

Agent 会先确认你的信息，然后给出冲稳保推荐。

### 粘贴长文本

如果你有一段很长的个人情况介绍：

1. 先 Ctrl+C 复制
2. 在 Agent 里输入 `/paste` 回车

### 查看信息状态

```
/slots
```

### 重新开始

```
/reset
```

---

## 常见问题

### Q: 提示"API 连接失败"怎么办？

1. 检查 `.env` 里的 API Key 是否正确
2. 检查 API Key 是否还有余额
3. 尝试在 `.env` 中把 `LLM_BASE_URL` 末尾加上 `/v1`（有些 API 需要）

### Q: 提示"未找到 Python"怎么办？

说明 Python 没装好或没加到 PATH。重新安装 Python，**一定要勾选 "Add Python to PATH"**。

### Q: 能否离线使用？

可以，用 Ollama 本地部署模型。安装 Ollama 后设置：

```
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
```

完全免费、完全离线。

### Q: Agent 的回复靠谱吗？

Agent 基于大量公开数据整理的知识库给出建议，但它是 AI，**可能出错**。录取分数线每年都在变，请务必到目标学校官网和各省教育考试院官网核实。

### Q: 会不会泄露我的个人信息？

不会。所有对话都在你的电脑本地运行，不经过任何第三方服务器（除了你选择的 AI 模型 API）。API 调用只会发送你的当前问题文本。
