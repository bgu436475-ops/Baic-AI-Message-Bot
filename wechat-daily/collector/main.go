package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/eatmoreapple/openwechat"
)

type event struct {
	Kind string `json:"kind"`
	ID   string `json:"id,omitempty"`
	At   int64  `json:"at,omitempty"`
	From string `json:"from,omitempty"`
	Text string `json:"text,omitempty"`
}

func main() {
	groupName := flag.String("group", "", "exact target group name")
	session := flag.String("session", "", "path to the local session file")
	login := flag.Bool("login", false, "allow an interactive QR sign-in")
	loginOnly := flag.Bool("login-only", false, "save a session without starting group collection")
	flag.Parse()
	if err := run(strings.TrimSpace(*groupName), *session, *login || *loginOnly, *loginOnly); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(groupName, session string, login, loginOnly bool) error {
	if session == "" || (groupName == "" && !loginOnly) {
		return fmt.Errorf("缺少目标群或会话路径")
	}
	if err := os.MkdirAll(filepath.Dir(session), 0700); err != nil {
		return fmt.Errorf("无法准备会话目录")
	}
	if info, err := os.Lstat(session); err == nil {
		if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
			return fmt.Errorf("会话文件必须是权限为 600 的普通文件")
		}
	} else if !os.IsNotExist(err) || !login {
		return fmt.Errorf("会话不可用，请在本机手动登录")
	} else {
		file, err := os.OpenFile(session, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return fmt.Errorf("无法准备会话文件")
		}
		if err := file.Close(); err != nil {
			return fmt.Errorf("无法关闭会话文件")
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	bot := openwechat.DefaultBot(openwechat.Desktop, openwechat.WithContextOption(ctx))
	bot.UUIDCallback = func(uuid string) {
		if login {
			fmt.Fprintf(os.Stderr, "在本机打开登录二维码并用微信扫码：https://login.weixin.qq.com/qrcode/%s\n", uuid)
		}
	}
	stream := json.NewEncoder(os.Stdout)
	ready := make(chan struct{})
	var groupID string
	var lastBeat time.Time
	bot.SyncCheckCallback = func(response openwechat.SyncCheckResponse) {
		if response.Success() && time.Since(lastBeat) >= 25*time.Second {
			select {
			case <-ready:
				writeEvent(stream, event{Kind: "heartbeat"})
				lastBeat = time.Now()
			default:
			}
		}
	}
	bot.MessageHandler = func(message *openwechat.Message) {
		if loginOnly || !message.IsSendByGroup() || !message.IsText() {
			return
		}
		<-ready
		room := message.FromUserName
		if message.IsSendBySelf() {
			room = message.ToUserName
		}
		if room != groupID || message.CreateTime <= 0 {
			return
		}
		id := message.MsgId
		if id == "" && message.NewMsgId != 0 {
			id = strconv.FormatInt(message.NewMsgId, 10)
		}
		if id == "" {
			return
		}
		name := "群成员"
		if message.IsSendBySelf() {
			name = "本账号"
		} else if sender, err := message.SenderInGroup(); err == nil && sender != nil {
			if sender.DisplayName != "" {
				name = sender.DisplayName
			} else if sender.NickName != "" {
				name = sender.NickName
			}
		}
		if body := strings.TrimSpace(message.Content); body != "" {
			writeEvent(stream, event{Kind: "message", ID: id, At: message.CreateTime, From: name, Text: body})
		}
	}
	// Stop on sync errors so a rejected session cannot cause repeated sign-in attempts.
	bot.MessageErrorHandler = func(err error) error { return err }
	storage := openwechat.NewFileHotReloadStorage(session)
	defer storage.Close()
	var options []openwechat.BotLoginOption
	if login {
		options = append(options, openwechat.NewRetryLoginOption())
	}
	if err := bot.HotLogin(storage, options...); err != nil {
		var dnsError *net.DNSError
		switch {
		case errors.Is(err, openwechat.ErrForbidden):
			return fmt.Errorf("微信拒绝了本次客户端登录")
		case errors.Is(err, openwechat.ErrLoginTimeout):
			return fmt.Errorf("微信登录二维码已过期")
		case errors.As(err, &dnsError):
			return fmt.Errorf("无法解析微信登录服务的域名")
		case openwechat.IsNetworkError(err):
			return fmt.Errorf("无法连接微信登录服务，请检查本机网络")
		}
		return fmt.Errorf("微信会话登录失败，请检查账号状态或在本机手动登录")
	}
	if loginOnly {
		cancel()
		fmt.Fprintln(os.Stderr, "微信会话已保存到本机，尚未启动群消息采集。")
		return nil
	}
	self, err := bot.GetCurrentUser()
	if err != nil {
		return fmt.Errorf("无法确认微信会话")
	}
	groups, err := self.Groups()
	if err != nil {
		return fmt.Errorf("无法获取微信会话的群列表")
	}
	for _, group := range groups {
		if group.NickName == groupName {
			if groupID != "" && groupID != group.UserName {
				return fmt.Errorf("存在同名群，请为目标群使用唯一群名")
			}
			groupID = group.UserName
		}
	}
	if groupID == "" {
		return fmt.Errorf("未找到目标群，请检查精确群名和该会话可见的群列表")
	}
	close(ready)
	if err := bot.Block(); err != nil {
		return fmt.Errorf("微信消息接收已中断，请检查本机微信会话")
	}
	return nil
}

func writeEvent(stream *json.Encoder, item event) {
	// The Python supervisor owns stdout and persists events before running the report.
	if err := stream.Encode(item); err != nil {
		os.Exit(1)
	}
}
