# AhabAssistantLimbusCompany-Android (AALC 安卓原生版)

> **基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 与 [MaaFwApp](https://github.com/Aliothmoon/MaaFwApp) 强力驱动的《边狱公司》安卓原生自动化工具**  
> 彻底脱离 PC 电脑与安卓模拟器，真机原生运行，支持 **1920×1080 独立后台虚拟副屏** 免打扰挂机！

---

## 🌟 核心特性与移植亮点

1. **📱 纯真机原生运行（脱离电脑与模拟器）**：
   * 底层采用 **MaaFramework** 跨平台 C++ 核心与 **MaaFwApp** Jetpack Compose 原生 GUI。
   * 业务层完整保留上游 [AhabAssistantLimbusCompany](https://github.com/KIYI671/AhabAssistantLimbusCompany) 的全部高级功能与算法。
2. **🖥️ 独家 1920×1080 后台虚拟副屏（免打扰挂机）**：
   * 借助 Shizuku 或 Root 特权服务，在 Android 底层显存中开辟一块独立的 1920×1080 纯内存虚拟显示器（Headless VirtualDisplay）。
   * 《边狱公司》在后台副屏中冷启动并自动执行，**完全不占据手机前台主屏幕，不影响日常微信聊天、刷视频或打其他游戏**！
   * 彻底解决长屏（20:9 / 21:9）异形屏黑边问题，AALC 原版 16:9 高清模板与坐标 100% 像素级对齐！
3. **🎯 100% 严格还原 AALC 全量业务逻辑**：
   * ✅ **一键长草**：全流程状态机（启动 -> 安全进入标题 -> 清理弹窗 -> 采光 -> 领奖 -> 换体 -> 镜牢）。
   * ✅ **日常采光**：经验本（EXP）与纽本（Thread）采光，支持游戏内连续作战与按星期一至周日自动轮换队伍。
   * ✅ **脑啡肽合成 & 狂气换体**：自动合成模块，支持 1~3 次狂气购买与独创的“葛朗台卡点买体模式”。
   * ✅ **通行证与邮箱领奖**：一键收取每日/每周任务狂气、经验与邮箱附件。
   * ✅ **全自动镜牢 (Mirror Dungeon)**：
     - 支持 10 大体系选择（烧伤/流血/震颤/破裂/呼吸/沉沦/充能/斩击/突刺/打击）；
     - 开局星芒增益、初始自选饰品与观测 EGO 饰品精准选择；
     - 基于 **PP-OCRv4** 的楼层主题包候选卡包名称 OCR 与玩家自定义权重选择；
     - 基于 **YOLOv8 深度学习模型 (`best.onnx`)** 的镜牢地图节点全自动识别与 Dijkstra 最优路径规划；
     - 休息点与商店全自动策略：回血、四级优先激进合成、指定体系购买、饰品升级与 1→3 / 2→3 技能替换；
     - 自动拼刀、胜率优先（P键开战）、技能3规避/优先、全员守备、小指良单通献祭队友模式；
     - 困难镜牢自动周常切换（周四刷新）、单次加成消耗与奖励保存。
   * ✅ **独立小工具**：
     - **亚哈降神附身代打**：主线/高难手动进战后开启，全程自动拼刀、守备与异想体判定事件处理；
     - **T巢资本家定时换饼**：OCR 监控当前体力与回复倒计时，满 20 体力自动上线合成模块。
4. **⚡ 超低功耗与高性能推理**：
   * 支持 Google ARM64 原生汇编优化的 **`XnnpackExecutionProvider`**；
   * 模板匹配单次耗时仅 **0.6 ms**，局部 OCR 单次仅需 **65 ms**，YOLO 地图检测仅 **300 ms**，无发热无卡顿。

---

## 🏗️ 架构设计

```mermaid
flowchart TD
    User([玩家手机 / Android 13+]) --> UI[MaaFwApp Compose 原生界面]
    
    subgraph Frontend [MaaFwApp 容器]
        UI -->|ProjectInterface V2| PI[interface.json / aalc_pipeline.json]
        UI --> ShizukuSvc[Shizuku / Root 特权服务]
        ShizukuSvc --> VD[1920x1080@280dpi 后台虚拟副屏]
    end

    subgraph Native [MaaFramework C++ 核心]
        PI --> NativeCtrl[libMaaAndroidNativeControlUnit.so]
        PI --> NativeOCR[PP-OCRv4 C++ 推理引擎]
        NativeCtrl -->|SurfaceControl 内存截屏| VD
        NativeCtrl -->|注入触摸/按键| VD
    end

    subgraph Agent [AALC Python 业务内核]
        NativeCtrl <-->|MaaControl 适配器| AALC_Core[AALC 业务逻辑层]
        AALC_Core --> Tasks[tasks/ (镜牢 / 采光 / 换体 / 战斗)]
        AALC_Core --> CV[OpenCV 模板匹配 + YOLOv8 best.onnx]
        AALC_Core --> OCR[module/ocr/ (MaaFramework / Pure ONNX)]
    end

    VD --> Game[《边狱公司》 com.ProjectMoon.LimbusCompany]
```

---

## 🚀 安装与使用

### 方式 1：直接安装 GitHub Actions 构建的 Release APK（推荐）
1. 前往本仓库的 [Releases](../../releases) 页面，下载最新的 `AALC-Android-Release.apk`。
2. 安装后打开 App，授权 **Shizuku**（或 Root 权限）。
3. 勾选想要执行的任务（一键长草、镜牢等），点击**开始**。
4. 《边狱公司》会在后台虚拟副屏静默运行，主屏浮窗可实时预览画面或最小化挂机！

### 方式 2：在 Termux 终端中直接独立运行 (极客模式)
本项目针对 Termux 做了完整免编译适配，无需构建 APK 也可在纯终端下直接跑：
```bash
# 1. 运行后台长草全流程
python3 agent/main.py --cli --task full_script

# 2. 仅运行全自动镜牢
python3 agent/main.py --cli --task mirror_dungeon

# 3. 运行亚哈战斗代打
python3 agent/main.py --cli --task infinite_battle_tool
```

---

## 🛠️ 云端 GitHub Actions 自动构建

本项目已配置完整的自动化构建工作流 [`.github/workflows/build-apk.yml`](.github/workflows/build-apk.yml)：
- 当向 `main` 分支推送代码或创建 Release Tag 时，GitHub 自动启动 Ubuntu 云端构建机；
- 自动完成 NDK C++ 预编译、Android CPython 3.13 运行时构建、Gradle 打包并生成已签名的 APK 安装包；
- 无需本地搭建庞大的 Android SDK/NDK 环境！

---

## 📄 开源许可证
本项目遵循 **AGPL-3.0** 开源许可证。
各依赖核心框架分别遵循相应开源协议：
- MaaFramework: LGPL-3.0
- MaaFwApp: AGPL-3.0
- AhabAssistantLimbusCompany: AGPL-3.0
