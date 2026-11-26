"""Verify authentication, receipt, and optionally replies for a WeCom test bot."""

import argparse
import asyncio
from getpass import getpass
import os
import re
import secrets
import sys
from unicodedata import normalize


class QuietLogger:
    def debug(self, message, *args):
        pass

    info = debug
    warn = debug
    error = debug


def read_credentials():
    bot_id = os.environ.get("WECHAT_BOT_ID", "").strip()
    secret = os.environ.get("WECHAT_BOT_SECRET", "").strip()
    if sys.stdin.isatty():
        if not bot_id:
            bot_id = input("Bot ID：").strip()
        if not secret:
            secret = getpass("Secret（输入时隐藏）：").strip()
    if not bot_id or not secret:
        raise ValueError("请在本机终端输入 Bot ID 和 Secret。")
    return bot_id, secret


async def receive_test_message(client, chat_type, reply=False):
    loop = asyncio.get_running_loop()
    authenticated = loop.create_future()
    received = loop.create_future()
    saw_text = False
    challenge = f"{secrets.randbelow(1_000_000):06d}"
    challenge_pattern = re.compile(rf"(?<![0-9]){challenge}(?![0-9])")

    @client.on("authenticated")
    def on_authenticated():
        if not authenticated.done():
            authenticated.set_result(True)

    @client.on("message.text")
    def on_text(frame):
        nonlocal saw_text
        body = frame.get("body", {})
        content = body.get("text", {}).get("content", "")
        if isinstance(content, str) and body.get("chattype") == chat_type:
            saw_text = True
            if not received.done() and challenge_pattern.search(normalize("NFKC", content)):
                received.set_result(frame)

    @client.on("error")
    @client.on("disconnected")
    def on_connection_closed(_):
        for result in (authenticated, received):
            if not result.done():
                result.set_result(False)

    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            connected = await asyncio.wait_for(authenticated, timeout=15)
        except (asyncio.TimeoutError, OSError):
            connected = False
        if not connected:
            print("认证未通过。检查机器人是否使用长连接，以及 Bot ID、Secret 和网络。", file=sys.stderr)
            return 1

        where = "在企微内部测试群里先 @ 机器人，再发送" if chat_type == "group" else "打开企微与机器人的单聊，发送"
        print(f"认证成功。请在 90 秒内{where}下方的 6 位数字。", flush=True)
        print(challenge, flush=True)

        try:
            frame = await asyncio.wait_for(received, timeout=90)
        except asyncio.TimeoutError:
            if saw_text:
                print("已收到文本，但没有匹配本次的 6 位数字。请重跑脚本并使用新测试码。", file=sys.stderr)
            else:
                print("认证通过，90 秒内未收到该会话类型的文本。检查可使用成员范围，群聊请从 @ 名单选中机器人。", file=sys.stderr)
            return 1
        if not frame:
            print("认证成功后连接中断。请查看机器人是否被另一进程接入。", file=sys.stderr)
            return 1

        print(f"收到{'群聊' if chat_type == 'group' else '单聊'}测试消息，长连接收消息正常。", flush=True)
        if reply:
            try:
                await asyncio.wait_for(
                    client.reply_stream(
                        frame, "stream_" + secrets.token_hex(8), "已收到测试消息，企微连通正常。",
                        finish=True,
                    ),
                    timeout=10,
                )
            except Exception as exc:
                print(f"已收到测试消息，但回复未获确认（{type(exc).__name__}）。", file=sys.stderr)
                return 1
            print("企微已确认测试回复。", flush=True)
        return 0
    finally:
        client.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat", choices=("single", "group"), default="single")
    parser.add_argument("--reply", action="store_true", help="收到匹配的测试码后，在同一会话回复一条确认。")
    args = parser.parse_args()

    try:
        from aibot import WSClient, WSClientOptions
    except ImportError:
        print("请先在测试环境安装 wecom-aibot-python-sdk。", file=sys.stderr)
        return 2
    try:
        bot_id, secret = read_credentials()
    except KeyboardInterrupt:
        return 130
    except (ValueError, EOFError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "未输入测试凭据。", file=sys.stderr)
        return 2
    try:
        client = WSClient(WSClientOptions(bot_id=bot_id, secret=secret, logger=QuietLogger(),
                                         max_reconnect_attempts=0))
        return asyncio.run(receive_test_message(client, args.chat, reply=args.reply))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"测试进程遇到错误（{type(exc).__name__}）。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
