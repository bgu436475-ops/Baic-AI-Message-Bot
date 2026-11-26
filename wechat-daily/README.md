# 微信群日报

在常开的电脑上用本机 Ollama 概括群消息，再由飞书自定义机器人推送日报。默认每天北京时间 00:10 开始处理前一自然日的内容。支持普通微信群的本机屏幕 OCR、手动提交文字和原有的实时采集模式。

## 企微 AI Bot · 长连接测试

在企微创建专用测试机器人，选择 API 模式和长连接，并把测试成员加到机器人的可使用范围。在项目的 wechat-daily 目录运行以下命令。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install wecom-aibot-python-sdk
.venv/bin/python wecom_smoke.py
```

按终端提示输入 Bot ID 和 Secret。认证通过后，在企微单聊里把终端给出的随机测试文字发给这个机器人。终端打印「收到单聊测试消息」表示收消息链路正常。要测内部群聊，给运行命令加上 --chat group，在测试群里 @ 机器人，再发随机测试文字。

已接入其他运行中服务的机器人，直接使用现有服务的日志做同样的收消息测试。

## 普通微信群 · 单窗口屏幕 OCR

需要 macOS 14 或更新版本、Swift 命令行工具和 Python 3.9 或更新版本。先用一个有明确授权、群名唯一的测试群。打开官方 Mac 微信，关闭多余的微信聊天窗口，并让测试群停在最新消息位置。下面的编译和权限命令在项目的 wechat-daily 目录执行。

```sh
swiftc -parse-as-library screen/ScreenReader.swift -o screen/wechat-screen
test -f config.json || install -m 600 config.example.json config.json
./screen/wechat-screen authorize
```

屏幕录制权限由本人确认。若系统要求，在「系统设置 → 隐私与安全性 → 屏幕与系统音频录制」为启动采集的终端授权，再重开终端。应用只处理官方微信窗口，图片仅用于内存里的 OCR。

在本机 config.json 的 group 填入目标群的准确名称。打开目标群后，先检查匹配状态：

```sh
python3 daily.py --source screen screen-probe
python3 daily.py --source screen capture
```

screen-probe 只显示群名是否匹配和识别到的行数。capture 将新文字保存在本机，按 Ctrl+C 可以结束。开始时先把屏幕上已有文字作为对照。试跑时在测试群产生几条新消息，等下一次取样，再用下面的 preview 检查日报。preview 需要启动本机 Ollama 并准备配置中指定的模型。

如果有多个符合条件的微信窗口，运行 ./screen/wechat-screen list-windows 查看窗口编号和尺寸，再填入 screen.window_id。窗口编号会随窗口重开变化。裁剪区域以所选窗口左上角为原点，格式为 [左, 上, 宽, 高]，各项取 0 到 1。默认区域要按实际微信窗口排版校准。群名区域应只覆盖顶部标题，消息区域应只覆盖聊天内容。默认每 5 秒取样，实际间隔包含识别耗时。

```sh
python3 daily.py --source screen preview
python3 daily.py --source screen serve
```

serve 在完成飞书机器人配置后开启定时发送。capture 和 serve 共用 state/screen，结束试跑进程后再启动定时服务。采集器根据相邻画面的文字重叠判断新增。群名不匹配、窗口不可用或 OCR 出错时暂停并记录间隙。画面没有可靠重叠时跳过该帧中的未知内容，以当前画面重新开始。日报日期按文字首次在屏幕上被捕捉的北京时间计算。快速刷屏、向上滚动、休眠和窗口布局变化都可能造成漏收或重复，建议用实际测试群逐条核对。

## 普通微信群 · 手动提交

需要 Python 3.9 或更新版本和本机 Ollama。在仓库根目录运行一次：

```sh
cd wechat-daily
test -f config.json || install -m 600 config.example.json config.json
ollama pull qwen3:8b
```

在本机的 `config.json` 中填写群名。预览可以先把飞书配置留空，定时发送需要填写飞书自定义机器人的 Webhook 和签名密钥。每天在官方微信客户端复制需要汇总的文字，在 Mac 终端中提交：

```sh
pbpaste | python3 daily.py --source manual import-text
python3 daily.py --source manual preview
```

也可以用 `import-text --file /path/to/messages.txt` 提交 UTF-8 文本文件。导入和预览默认使用北京时间当天，补录昨天等其他日期时，可以加上 `--date YYYY-MM-DD`。日报只覆盖提交的文字，批次间完全相同的内容只存一次。

飞书配置完成后，常驻运行以下命令：

```sh
python3 daily.py --source manual serve
```

服务到点后检查前一天的素材。如果暂时没有素材，就等待当天补录。已成功发送的日期只发送一次。该模式不启动微信采集器。

## 实时采集 · 第三方接入

支持 macOS / Linux。需要 Python 3.9 或更新版本、Go 1.20 或更新版本，以及运行在本机的 Ollama。以下命令在仓库根目录执行。

```sh
cd wechat-daily
(cd collector && go build -o wechat-collector .)
install -m 600 config.example.json config.json
ollama pull qwen3:8b
```

如果飞书或目标群尚未配置，可以先在本机终端完成微信扫码并保存会话。打开终端打印的二维码链接，用手机微信扫码确认。

```sh
./collector/wechat-collector --login-only --session ./state/wechat-session.json
```

在飞书要接收日报的群里添加自定义机器人，开启签名校验。在本机的 `config.json` 里填入目标微信群名、Webhook 地址和签名密钥。群名需要唯一，并且该群要出现在用于采集的微信会话群列表里。可以用 `report_time` 设置北京时间的推送时刻，用 `ollama_model` 换成本机已有的模型。

在一个已告知成员的测试群先运行。第一次启动允许在本机显示二维码，需要账号使用者扫码。进程保持运行即可接收消息并在次日推送。

```sh
python3 daily.py serve --login
```

后续可以从本机保存的会话启动。微信拒绝登录或同步断开时，采集停止，日报进程仍会尝试发送断档提醒。需要先停止当前进程，再检查账号状态并手动启动。

```sh
python3 daily.py serve
python3 daily.py preview --date 2026-11-19
```

`preview` 用本机已有记录生成并打印报告，可以在服务运行时同时执行。常开机按需用自身的进程管理器运行 `serve`，保持同一工作目录。手动扫码时用交互终端，避免把二维码写到后台日志。换群时使用全新的数据目录，例如 `python3 daily.py --state ./state/other serve --login`。

## 数据与故障处理

- 只处理匹配到的一个群的文字。以微信消息 ID 去重，以消息时间划分北京时间的日期。语音、图片、文件、撤回及历史消息不进入日报。
- 消息、会话和发送账本存放于本机 `state/`，每日清理 7 天以前的聊天和心跳。聊天由回环地址上的 Ollama 处理，飞书收到的是日报和告警。配置和运行数据由本目录的 `.gitignore` 排除。
- 日报根据成功同步的心跳估算采集缺口。停机期间的消息无法主动补采，心跳也无法证明每条消息都收到。如果电脑晚于设定时间启动，当天会补发前一天的日报。
- 飞书明确拒绝或本机模型生成失败时，服务等待 15 分钟再尝试。超时、未知回执或发送期间异常退出时，发送账本会阻止自动重发。处理前请先在目标群核对对应日期的消息。排查可用 `sqlite3 state/daily.sqlite3 'SELECT key, state FROM delivery ORDER BY at DESC;'`。
- 采集端沿用 [dcnews](https://github.com/121812/dcnews) 使用的 [openwechat](https://github.com/eatmoreapple/openwechat) 依赖。它依赖个人微信的第三方接入，存在登录受限或同步中断的可能，现有实现不会在微信内发送消息，也不会在后台反复尝试扫码。

## 本地验证

```sh
python3 -m unittest -v
(cd collector && go test ./...)
```

Python 检查使用临时数据库和模拟的 Ollama / 飞书回执。真实登录和飞书送达需要在自己的测试群验证。
