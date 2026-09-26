# 个人 macOS 自动更新

此 fork 的 arm64 构建使用自己的 Sparkle 更新源：

`https://github.com/RTLiang/helium-macos/releases/download/personal-updates/appcast-arm64.xml`

## 发布流程

`Sync and release personal Helium for macOS` 每天同步上游，也可手动运行。
保留个人补丁的源码编译完成后，Actions 会：

1. 签名和打包 DMG。
2. 检查应用内的个人公钥、Sparkle.framework 和个人构建号。
3. 使用 `PERSONAL_SPARKLE_PRIVATE_KEY` 签名 DMG，校验签名与公钥匹配。
4. 发布独立的个人版本 Release，并下载核对上传的 DMG。
5. 更新 `personal-updates` Release 中的 `appcast-arm64.xml`。

更新源不引用官方发布的二进制。浏览器下载安装的完整更新也包含个人补丁。
不生成差分更新，避免依赖官方历史版本或另一种 CPU 架构。

## 一次性安装

首次需要手动安装包含 Sparkle 和个人公钥的新 DMG，并将应用放到可写位置，
例如 `/Applications`。旧的、未启用 Sparkle 的本地构建无法自行获得更新功能。
在 Helium 服务设置中允许自动浏览器更新，之后会检查个人更新源并下载更新。
需要重启时使用浏览器提供的重新启动按钮完成安装。

## 密钥

- 公钥在 `resources/personal_updates.json`，可以公开。
- 私钥放在本仓库的 Actions Secret `PERSONAL_SPARKLE_PRIVATE_KEY`。
- 如果设置了 `PROD_MACOS_SPARKLE_ED_PUB_KEY`，它必须与配置中的公钥一致。
- 保存私钥的离线备份。不要把私钥提交到 Git 或粘贴到日志中。
- Sparkle 的更新签名与 Apple Developer ID、公证不同；当前个人构建仍使用临时签名。

## 版本号和恢复构建

`CFBundleVersion` 在 Helium 版本号后附加 `GITHUB_RUN_ID.GITHUB_RUN_ATTEMPT`。
同一浏览器版本的新构建也可被识别为更新。跨机器续编使用存档内已经确定的版本号，
不会因为换 runner 而改变版本。

如果只重跑某段 job，存档里的构建尝试号可能与当前尝试号不同，签名阶段会拒绝发布。
此时应完整重跑 workflow 或新建一次手动运行，不要绕过版本检查。

发布步骤拒绝覆盖为较旧或相同版本，并且只在上传的 DMG 校验成功后更新清单。
`personal-updates` Release 的资产地址是固定更新入口，不应删除。

## 本地验证

安装 `cryptography==46.0.3`，并从官方 Sparkle 2.7.1 发布包取得 `bin/sign_update` 后运行：

```sh
SPARKLE_SIGN_TOOL=/path/to/sign_update python3 .github/tests/personal_updates.py -v
```

这些检查验证签名、构建身份和发布保护；真正的浏览器升级仍需用两个完整构建验证。
