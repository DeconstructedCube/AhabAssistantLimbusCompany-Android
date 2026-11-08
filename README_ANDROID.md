# AhabAssistantLimbusCompany-Android (AALC 安卓版)

基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 与 [MaaFwApp](https://github.com/Aliothmoon/MaaFwApp) 构建的《边狱公司》安卓端自动化工具。无需电脑，在手机上原生运行，支持 1080P 后台虚拟副屏挂机。

---

## 使用指南

### 1. 准备工作
- 手机安装并激活 **[Shizuku](https://shizuku.rikka.app/)**（无需 Root，通过无线调试即可激活；已 Root 设备亦可直接授权）。
- 安装本项目的 Release APK。

### 2. 操作步骤
1. 打开 App，在主界面或侧边栏点击授权 **Shizuku**（或 Root）。
2. 在任务列表勾选要跑的内容（如「一键长草」），展开卡片可修改刷本/镜牢次数或队伍。
3. 点击右下角「开始」。
4. 游戏默认在后台 1080P 独立虚拟副屏运行，不遮挡前台操作；可通过悬浮窗查看实时画面或进行手动操作。

---

## 包含功能

- **日常采光**：经验本与纽本自动进入并战斗，支持连续战斗设置与按星期轮换编队。
- **脑啡肽换体**：自动合成模块，支持设定狂气买体次数及卡点买体。
- **领奖**：自动领取通行证任务经验与邮箱附件。
- **全自动镜牢**：
  - 10 大体系选择、初始饰品与观测饰品选择；
  - 楼层主题包候选卡包 OCR 识别与自定义权重选择；
  - 基于 YOLOv8 模型的地图节点识别与最优路径寻路；
  - 商店四级优先激进合成、指定体系购买、饰品升级与技能替换；
  - 自动拼刀、胜率P键、全员守备、困难周常自动切换与单次加成消耗。
- **独立工具**：
  - **自动战斗代打**：接管战斗连线与判定事件处理；
  - **定时换饼**：监控体力回复时间，自动合成模块。

---

## 架构说明

- **GUI 外壳**：基于 MaaFwApp (Jetpack Compose) 构建的 Android 应用，负责权限申请、任务配置与虚拟副屏管理。
- **底层驱动**：MaaFramework C++ 核心负责 1080P 内存帧截取与输入事件注入。
- **业务内核**：Python Agent 负责 AALC 原生业务流程调度。

---

## 获取安装包

前往本仓库的 [Releases](../../releases) 页面下载最新的 `AALC-Android-Release.apk`。
每次向 `main` 分支推送或发布 tag 时，GitHub Actions 会自动编译并发布已签名的安装包。

---

## 许可证

本项目遵循 **AGPL-3.0** 开源许可证。
- MaaFramework: LGPL-3.0
- MaaFwApp: AGPL-3.0
- AhabAssistantLimbusCompany: AGPL-3.0
