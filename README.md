# xiaogpt

让小爱同学使用ChatGpt来回答

![image](https://user-images.githubusercontent.com/15976103/220028375-c193a859-48a1-4270-95b6-ef540e54a621.png)

## 前言
由于我的设备是L05C，使用
[原项目](https://github.com/yihong0618/xiaogpt)
大佬的版本会出现些许问题，想说自己简化一下。目前只引入了GPT3.5

## 原理 —— 大佬的灵光乍现

[不用 root 使用小爱同学和 ChatGPT 交互折腾记](https://github.com/yihong0618/gitblog/issues/258)

## 准备

1. ChatGPT id
2. 小爱音响（需开启蓝牙）
3. 能正常联网的环境或 proxy
4. python3.8+

## 使用

1. pip install -r requirements.txt
2. 在项目根目录创建一个config.json文件配置参数 (目前已知 LX04 和 L05B L05C 可能需要将 use_command 为 true才能正常播放)

```json
{
  "hardware": "", // 设备型号（在音响底部）
  "account": "", // 你的小米账号
  "password": "", // 你的小米密码
  "openai_key": "", // OPENAI的密钥
  "openai_baseurl": "https://openapi.ssiic.com", // OPENAI API 根地址
  "mute_xiaoai": false,  // 禁用掉小爱本身的回答
  "use_command": false, // 使用命令行调用语音回答
  "keyword": "帮我", // 可以设置唤醒词或者设为空字符串
  "end_prompt": "请在50字以内回答" // 限制回答字数
}
```
3.运行
```shell
python xiaogpt.py
```


# 感谢

- [yihong0618](https://github.com/yihong0618/)
- [xiaomi](https://www.mi.com/)
- @[Yonsm](https://github.com/Yonsm) 的 [MiService](https://github.com/Yonsm/MiService) 