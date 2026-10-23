# PCL 2.14.0.0 无更新修改版

> 第三方修改版，非官方发行。基于 Plain Craft Launcher 2 正式版 **2.14.0.0 (411)** 的二进制补丁，仅切除「启动器自我更新」能力。
>
> 原始程序版权归 **龙腾猫跃** 所有：<https://github.com/Meloong-Git/PCL> ｜ 赞助：<https://afdian.com/a/LTCat>



---

## 一句话说明

这个包里的 `Plain Craft Launcher 2.exe` 以官方 2.14.0.0 正式版为底，**只改了 5 个位置**，全部落在启动器的自我更新模块里。  
它不会再把自己替换成新版本，**也不会因为改过而少任何一项下载功能**。

| 项目        | 值                                                                  |
| --------- | ------------------------------------------------------------------ |
| 程序版本      | 2.14.0.0 (411)，正式版                                                 |
| 文件大小      | 5,989,376 字节（与原版完全一致）                                              |
| 原版 SHA256 | `5582952ded3b443503f66c23b810802bd20f1a3e847b54d9e09653a825859a36` |
| 本版 SHA256 | `9ad2a4d1edacd0978cb062e1680070f3153a5539aaf8ffc6671b440baf50abb1` |
| 运行时       | .NET Framework 4.8（与原版一致，未更换运行时）                                   |

---

## 一、下载功能没有被阉割

这是最容易误会的一点，所以先讲清楚。

### 改动清单（全部）

| # | 位置                                                        | 原内容                    | 现内容                 |
| - | --------------------------------------------------------- | ---------------------- | ------------------- |
| 1 | `PCL.ModSecret::UpdateStart(bool, IEnumerable<string>)`   | 下载更新包、覆盖自身             | 空方法（`ret`）          |
| 2 | `PCL.ModSecret::UpdateRestart(bool)`                      | 启动带 `--update` 参数的继任进程 | 空方法（`ret`）          |
| 3 | `PCL.ModSecret::UpdateReplace(int, string, string, bool)` | 结束旧进程并替换 exe           | 空方法（`ret`）          |
| 4 | `PCL.ModSecret::UpdateCheckByButton()`                    | 手动检查更新，比对版本后调用 1       | 只提示「本版本已移除更新功能。」    |
| 5 | `#US` 字符串 `正在检查更新，请稍候！`                                   | 11 个 UTF-16 码元         | 等长替换为 `本版本已移除更新功能。` |

除此之外，文件里没有任何一个字节被改写。

### 因此，以下能力全部保持原样

- 原版 / Forge / NeoForge / Fabric / Quilt / LiteLoader / OptiFine 的版本安装与安装器下载
- Mod、整合包、资源包、光影、世界存档的搜索与下载（CurseForge、Modrinth 双源）
- 下载源切换（官方源 / BMCLAPI 镜像）、多线程下载、限速、断点续传
- Java 自动搜索、Java 运行时下载
- 版本隔离、游戏内存与 JVM 参数、启动脚本
- 微软正版登录、离线登录、皮肤加载
- 整合包导入与导出、存档管理、页面自定义、帮助库

### 怎么自己验证

1. 打开「设置 → 启动 → 启动器」，点「检查更新」，只会弹出「本版本已移除更新功能。」，不会发起任何下载。
2. 随便进「下载」页装一个 Minecraft 版本或一个 Mod，行为与官方版一致。
3. 用 `ilspycmd`、dnSpy 反编译，搜 `UpdateStart`：方法体是空的；搜其它下载相关方法（`ModNet`、`ModDownload` 等）：一字未改。

---

## 二、官方自动更新是怎么工作的

逆向 2.14.0.0 得到的实际链路：

```
应用启动
  └─ ServerLoader（加载器名「PCL 配置更新」）
       ├─ GET https://pcl2-server-*.file.myqcloud.com/notice.cfg
       ├─ GET https://pcl2-server-*.file.myqcloud.com/ServerConfig.json
       └─ GET https://pcl2-server-*.file.myqcloud.com/notice.json
              │
              └─ 公告数组 [{ id, importantLevel, requirements, isUpdate, actions[] }]
                    │  actions 命中 "update" / "slientupdate"
                    ▼
              ModSecret.UpdateStart(Silent)
                    │  读取 ServerConfig["Update"]["Release"]["DownloadUrls" | "PatchUrls"]
                    │  下载 zip 或 MSDelta 补丁到 PCL\Plain Craft Launcher 2.exe
                    ▼
              ModSecret.UpdateRestart(true)
                    │  以 --update <pid> <old> <new> <restart> 启动自身
                    ▼
              ModSecret.UpdateReplace(...)
                    │  结束旧进程，完成文件替换，可选重启
                    ▼
                 【新版本接管】
```

手动入口只有一条：`设置 → 其他 → 启动器 → 检查更新` → `UpdateCheckByButton` → `PageSetupSystem.IsLauncherNewest` → `UpdateStart`。

**关键结论**：`UpdateStart` 是唯一真正执行"下载并覆盖自身"的方法，所有路径（静默更新、公告弹窗、手动检查）都必须经过它。把它置空，整条链路就断了。

### 为什么不用「关掉检查更新」这个设置

`PCL/Setup.ini` 里的 `SystemSystemUpdate` 不是"是否检查更新"，而是**公告忽略等级**（默认 `0`）：

```vb
' 公告命中条件
If Settings.Get(Of Integer)("SystemSystemUpdate") > importantLevel Then 跳过
```

它的问题：

- 用户能在 UI 里改回来（就是一个普通设置项）
- 服务器发一条 `importantLevel = 4` 的公告就能越过它
- 只挡公告，挡不住手动「检查更新」按钮

它适合"不想被打扰"，不适合"这个版本必须锁死"。

---

## 三、技术方案

### 3.1 目标程序特征

| 项      | 值                                                        |
| ------ | -------------------------------------------------------- |
| 格式     | PE32（`0x10B`），单文件 .NET Framework 4.8 程序集                 |
| CLR 标志 | `COMIMAGE_FLAGS_ILONLY`，**无强名称签名**，**无 Authenticode 签名** |
| 节点     | `.text` 5.78 MB / `.rsrc` 200 KB / `.reloc` 512 B        |
| 混淆     | 无。类型名、方法名、字符串全部明文（`PCL.ModSecret`、`PCL.ModMain` …）       |

没有强名称、没有数字签名、没有混淆，意味着改完不需要重签，也不会触发 CLR 的签名校验。

### 3.2 定位过程

不依赖任何 .NET 反编译器的写能力，纯字节解析：

1. 走 PE 头 → 数据目录第 15 项拿到 CLR 头 → `MetaData` RVA/Size
2. 解析元数据根，拆出 `#~`（表流）、`#Strings`、`#Blob`、`#US` 四个堆
3. 按 ECMA-335 逐表计算行宽（依赖 `HeapSizes` 与各表行数，编码索引按 tag 位宽判定 2/4 字节），累加得到 `Module` / `TypeRef` / `TypeDef` / `Field` / `MethodDef` 偏移
4. 由 `TypeDef.MethodList` 区间取出 `PCL.ModSecret` 的全部方法，按名字匹配到目标
5. 由 `MethodDef.RVA` 反查文件偏移，读出方法体头（tiny / fat）与 IL 起始位置

### 3.3 打补丁手法

**（a）三个 void 方法 → 空实现**

PCL 的这些方法都是 fat 方法头（12 字节，含异常表段）。做法是把 fat 头**整体改写为 tiny 头**：

```
原： 1B 30 09 00 67 01 00 00 DD 00 00 11 ...   (fat, code size 0x167, 带 EH)
改： 06 2A                                      (tiny, code size 1 → 单条 ret)
```

`06` = `(1 << 2) | 0x02`，即 tiny 头、代码长度 1 字节；`2A` = `ret`。  
改写后：

- 方法立即返回，任何调用路径都不会产生副作用
- fat 头里记录的异常表不再被引用（tiny 头没有 EH 段），JIT 不会去解析那一段
- 原 IL 字节留在文件里成为不可达数据，不影响任何偏移

`UpdateRestart` 的 try 块从 IL 偏移 0 开始，逐条改指令会撞上"`ret` 不允许出现在 try 内"的规则；改用 tiny 头整体替换就绕开了这个问题——方法的异常处理信息直接不存在了。

**（b）手动检查按钮 → 提示桩**

`UpdateCheckByButton` 替换成 13 字节 IL 桩：

```
IL_0000: ldstr   "本版本已移除更新功能。"      72 D2 F4 00 70
IL_0005: ldc.i4.0                              16
IL_0006: ldc.i4.1                              17
IL_0007: call    ModMain.Hint(string, HintType, bool)   28 64 02 00 06
IL_000C: ret                                   2A
```

tiny 头为 `36`（code size 13）。  
`ldstr` 与 `call` 的 token 不是手填的，而是从原方法体里同形状的调用序列中提取，保证与程序集元数据完全一致。

**（c）文案等长替换**

`#US` 堆里每个字符串项 = 压缩长度前缀 + UTF-16 数据 + 1 字节终结符。  
把 `正在检查更新，请稍候！` 换成 `本版本已移除更新功能。`，两者都是 11 个 UTF-16 码元，长度前缀 `2D`（22 字节 + 终结符 1）保持不变，堆内后续所有字符串偏移与 `ldstr` token 全部继续有效。

**（d）刻意没有做的事**

| 没做                          | 原因                                                                |
| --------------------------- | ----------------------------------------------------------------- |
| 改 PE 版本资源 / AssemblyVersion | PCL 用的是编译期常量 `VersionBaseName`，改 PE 版本只会让属性页与界面不一致；对阻断更新零收益       |
| 改 `SystemSystemUpdate` 默认值  | 软开关，可被 UI 改回；已由硬切断覆盖                                              |
| 加壳 / 混淆 / 反调试               | 与目的无关，只会让审计变难                                                     |
| 动 UI、主题色、图标                 | 保持与官方一致的界面；也符合 PCL 对二次修改的颜色要求                                     |
| 改文件大小、新增节                   | 全部补丁原地覆盖，文件长度 5,989,376 字节不变，`.rsrc`（WPF XAML/BAML）与 `.reloc` 零改动 |

### 3.4 复现

仓库内的 `tools/patch-pcl-update.py` 是完整实现，可作为审计依据：

```bash
python tools/patch-pcl-update.py "Plain Craft Launcher 2.exe" "Plain Craft Launcher 2.patched.exe"
```

脚本会：

- 校验输入文件 SHA256，非 2.14.0.0 (411) 原版直接拒绝
- 自动解析元数据、按方法名定位（不依赖硬编码 RVA）
- 校验 `ldstr` token 与目标字符串位置一致
- 断言输出文件长度与原文件相同

输出：

```
UpdateStart            @0x022d50 -> ret
UpdateRestart          @0x022ed4 -> ret
UpdateReplace          @0x023010 -> ret
UpdateCheckByButton    @0x022c7c -> Hint("本版本已移除更新功能。") + ret
字符串                 -> "本版本已移除更新功能。" (22 字节)

SHA256: 9ad2a4d1edacd0978cb062e1680070f3153a5539aaf8ffc6671b440baf50abb1
```

---

## 四、验证记录

| 验证项             | 方法                              | 结果                                                                                                        |
| --------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 方法体改写正确         | `ilspycmd -t PCL.ModSecret` 反编译 | `UpdateStart` / `UpdateRestart` / `UpdateReplace` 均为空方法体；`UpdateCheckByButton` 只剩一行 `Hint("本版本已移除更新功能。")` |
| 程序可正常启动         | 干净目录实机运行                        | 窗口正常弹出，日志三阶段加载完成，版本 `2.14.0.0 (411)`                                                                      |
| 无 IL 校验异常       | 运行期观察                           | 无 `BadImageFormatException` / `InvalidProgramException`，无未处理异常                                            |
| `--update` 参数失效 | 追踪 `ModMain.Main` 的 IL          | 分支只调 `UpdateReplace` 后 `Environment.Exit(5)`；方法已置空，不做任何文件操作                                               |
| 补丁可复现           | 用公开脚本重跑                         | 输出 SHA256 与发布文件逐字节一致                                                                                      |
| 文件完整性           | 大小/节表对比                         | 大小不变，节表未改，`.rsrc` 未改                                                                                      |

实机启动日志片段：

```
15:26:41.811 I [Application] 程序版本：正式版 2.14.0.0 (411)
15:26:41.811 I [Application] 程序路径：...\Plain Craft Launcher 2.exe
15:26:41.811 I [Application] 第一阶段加载用时：58 ms
15:26:42.077 I [FormMain]   第二阶段加载用时：257 ms
15:26:42.382 I [FormMain]   第三阶段加载用时：49 ms
```

---

## 五、使用

1. 解压到任意目录（不要放进需要管理员权限才能写的目录，例如 `C:\Program Files`）
2. 双击 `Plain Craft Launcher 2.exe`
3. 首次启动会在同目录生成 `PCL\`（配置与日志）和 `.minecraft\`（游戏目录）

**确认自己用的是补丁版**：

- 文件 SHA256 等于上表「本版 SHA256」
- 设置 → 其他 → 启动器 → 检查更新，提示「本版本已移除更新功能。」

---

## 六、已知边界

| 行为                  | 说明                                                                                                        |
| ------------------- | --------------------------------------------------------------------------------------------------------- |
| 公告系统仍会联网            | 启动时仍请求 `notice.cfg` / `notice.json` / `ServerConfig.json`，用于公告与下载源配置。它不负责替换文件，断网时静默失败，不影响使用               |
| 匿名数据上报仍在            | 与原版一致，可在「设置 → 其他 → 隐私」中关闭                                                                                 |
| 导出整合包会附带官方 PCL      | `DownloadLatestPCL` 未改动：导出整合包时仍会下载官方最新版 PCL 放进包里。这是"给别人打包"的功能，不影响本机版本锁定。若希望整合包内也带本版，导出后手动替换包内 `PCL\` 目录即可 |
| 「启动器更新」页仍存在         | 页面保留，只是按钮变成提示。删除页面需要改 WPF 资源，风险远大于收益                                                                      |
| 仅适用于 2.14.0.0 (411) | 其他版本的元数据 RVA 不同，脚本会因 SHA256 不匹配而拒绝执行                                                                      |
| 不提供跨版本升级            | 这是"锁死版本"的包，后续官方版本需要重新做补丁                                                                                  |

---

## 七、合规与免责

- PCL 的一切权利归 **龙腾猫跃（Meloong）** 所有。本项目是第三方二次修改，**与官方无关**，不代表官方立场。
- 使用与分发遵循 [《PCL 分发有限许可》](https://raw.githubusercontent.com/Meloong-Git/PCL/main/LICENCE) 与《PCL 存储库合理使用指南》：
  - 名称以 `Plain Craft Launcher (PCL)` 开头并带「无更新修改版」后缀，明示第三方修改
  - 保留原程序的「关于」页署名与赞助入口（二进制补丁未改动该页）
  - 不用于任何商业用途，不提供与赞助解锁类似的功能，页面主色相保持蓝色
  - 修改内容与实现手段在本文档与 `tools/` 中完整公开，可供任何人复核
- **建议仅用于自用或团队内部分发。** 若计划公开分发，请先自行确认许可条款（尤其《PCL 分发有限许可》对再分发的限制），必要时联系原作者取得授权。
- 本项目按「现状」提供，不附带任何明示或暗示的担保。因使用本修改版造成的任何问题由使用者自行承担。

---

## 八、附：为什么值得这么做

自动更新对普通用户是便利，对下面这些场景是风险：

- 教学机房 / 服务器整合包 / 比赛环境，需要**所有机器锁定同一版本**
- 已经验证过的 Mod 组合，不希望某天启动器自己升级后行为变化
- 内网或弱网环境，不希望启动器在后台尝试下载更新
- 需要审计"这个 exe 到底是什么"，不希望它随时变成另一个二进制

把更新能力切干净、把改动清单摊开，比反复叮嘱用户"别点更新"可靠得多。
