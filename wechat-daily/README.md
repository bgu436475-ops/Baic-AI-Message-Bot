# 微信群日报

在一台常开的电脑上收取一个指定微信群的实时文字消息，使用本机 Ollama 生成日报，再由飞书自定义机器人推送。默认每天北京时间 00:10 开始生成前一自然日的日报。支持在终端预览指定日期的日报。

## 本机运行

支持 macOS / Linux。需要 Python 3.9 或更新版本、Go 1.20 或更新版本，以及运行在本机的 Ollama。以下命令在仓库根目录执行。

```sh
cd wechat-daily
(cd collector && go build -o wechat-collector .)
install -m 600 config.example.json config.json
ollama pull qwen3:8b
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
