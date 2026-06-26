# CablediOS.app 包体积优化记录

记录将 `packaging/build_macos_app.sh` 产出的 macOS app 从 **305MB 压缩到 200MB
(-105MB，-34%)** 的分析过程与方案。所有改动均已落地到构建脚本，且经真机验证
（启动正常、两台 iOS 设备成功配对、功能可用）。

## 结果总览

| 阶段 | App 体积 | 主二进制 | 增量 |
|---|---|---|---|
| 原始 | 305MB | 160MB | — |
| + 剔除 jedi/parso + strip + Qt 裁剪 | 239MB | 131MB | -66MB |
| + 交互式 shell 依赖 stub | **200MB** | **100MB** | -39MB |

## 一、体积分析方法

非 onefile 的 `.app` 直接 `du` 不够直观（含符号链接、压缩前后差异），用以下手段定位：

```bash
# 1) 解开产物 zip，按未压缩大小列出最大的文件
unzip -l build/nuitka/CablediOS.zip | sort -rn | head -45

# 2) venv 中各依赖包占用（判断源头）
du -sh .venv/lib/python3.13/site-packages/* | sort -rh | head -30

# 3) Nuitka 编译中间产物：每个模块的 .o 大小 = 该模块进二进制的体积代理
find build/nuitka/CablediOS.build -name 'module.*.o' -exec du -k {} + | sort -rn | head -30

# 4) 用 otool -L 判断某个 dylib/framework 是否被其它文件链接（决定能否删）
otool -L <file> | grep <lib>
```

**关键定位结论：**

- 305MB 中 **主二进制 `CablediOS` 占 160MB（52%）**，是绝对大头。Nuitka 把
  `pymobiledevice3` 整包及其全部依赖编译进了单一二进制。
- 代码实际只用 `QtCore / QtGui / QtWidgets` 三个 Qt 模块，但 PySide6 连带打入
  QtPdf / QtNetwork 等未用框架。
- 主二进制里塞了大量**交互式 CLI / shell 组件**（jedi、xonsh、pygments、IPython、
  prompt_toolkit、traitlets、blessed），全部由 `--include-package=pymobiledevice3`
  连带拉入，而本 app 只用 pymobiledevice3 的 library service API，从不开 shell。

## 二、优化方案（按落地顺序）

### 1. 剔除 jedi + parso（约 -28MB）

`jedi`（静态分析补全引擎，源码 30MB）+ 其解析器 `parso` 被编译进二进制。

- **安全依据**：jedi 只是 IPython 补全器的**可选惰性**依赖，
  `IPython/core/completer.py` 用 `try: import jedi ... except: JEDI_INSTALLED = False`
  保护；本 app 从不开 IPython shell。`parso` 仅被 jedi 引用。
- **实现**：`COMMON_FLAGS` 增加 `--nofollow-import-to=jedi,parso`。
- **收益**：二进制内约 14MB + 单独打包的 grammar/typeshed 数据约 14.5MB。

### 2. strip 去符号（约 -25~29MB）

Nuitka/clang 在 160MB 主二进制及各 dylib/so 中留有符号表。

- **实现**：新增 `strip_bundle()`，对主可执行文件及所有 `.dylib/.so` 执行
  `strip -x`（仅删 local 符号，保留动态链接所需的 global/external 符号，对可执行
  文件与共享库都安全）。
- **顺序要求**：必须在代码签名**之前**执行（strip 会让已有签名失效）。

### 3. 裁剪未用 Qt 模块（约 -9~11MB）

代码从不 `import` 这些 Qt 模块，用 `otool -L` 确认无其它文件链接后删除：

- **QtNetwork**：Qt 自带 HTTP/SSL 栈。app 的网络全走 pymobiledevice3 / requests，
  从不用 Qt 网络 → 删框架 + Python binding + `tls/` 后端插件。
- **QtPdf**：仅被 `imageformats/libqpdf.dylib`（PDF 转图片插件）链接；相册只看
  照片不看 PDF → 删框架 + libqpdf 插件。
- **不能删**：`QtDBus` 被 QtGui 硬链接（必需）；`QtSvg`/`QtPrintSupport` 价值低
  且有图标渲染风险。
- **实现**：新增 `prune_unused_qt()`，删除后带悬空引用守卫（若仍有文件链接被删
  框架则 `warn`，不中断）。

### 4. ⚠️ 关键修复：后处理后强制 ad-hoc 重签

**这是最重要的正确性修复。** Nuitka 在生成 bundle 时会打 ad-hoc 代码签名。上面的
`dedup_dylibs`、`prune_unused_qt`、`strip_bundle` 都会修改 bundle 内文件 →
**签名失效**。Apple Silicon（arm64）对此强制执行，失效签名的 app 启动即被内核
**SIGKILL（静默退出，无任何输出）**。

- **症状**：进程退出码 `-9`，stdout/stderr 全空。`codesign --verify` 报
  `invalid signature (code or signature have been modified)`。
- **实现**：`codesign_app()` 在未设置 `CODESIGN_IDENTITY` 时，不再"留空不签"，
  而是执行 `codesign --force --deep -s -` 进行 ad-hoc 重签。`main()` 中签名步骤
  放在所有后处理**之后**。

### 5. stub 屏蔽交互式 shell 依赖链（约 -39MB，主二进制 -31MB）

最大的剩余块：`xonsh / pygments / prompt_toolkit / traitlets / blessed / IPython /
pygnuutils`，合计约 70MB 编译产物。

**问题根因**：`pymobiledevice3` 在 app 可达的模块里**顶层硬导入**这些库，但全部只在
**GUI 永不触发的交互式 shell 代码路径**中使用：

| 模块 | 顶层导入 | 实际使用位置（GUI 不走） |
|---|---|---|
| `services/afc.py` | xonsh, pygments, pygnuutils | `AfcShell` 类、shell 方法（`AfcService` 本身干净） |
| `services/crash_reports.py` | xonsh | shell 方法（`CrashReportsManager` 干净） |
| `service_connection.py` | pygments | `ServiceConnection.shell()` |
| `remote/remotexpc.py` | pygments | `.shell()` |
| `utils.py` | IPython, traitlets | `start_ipython_shell()` |

因为是顶层导入，直接 `--nofollow-import-to` 会让 `AfcService` 等导入即崩
（afc.py 还在导入期用 `class AfcLsStub(LsStub)` 和注解里的 `Arg(...)`）。改
pymobiledevice3 源码则破坏可升级性。

**方案**：在 `packaging/stubs/` 提供同名的**极小占位包**，构建时把该目录前置到
`PYTHONPATH`，Nuitka 即编译这些占位模块而非真包，并不再深入真包的依赖链。磁盘上的
pymobiledevice3 完全不动；`python CablediOS.py` 开发运行仍用 venv 里的真包（该目录
不在开发 `sys.path` 上）。

stub 只暴露被导入的符号（详见 `packaging/stubs/README.md`），例如
`xonsh.built_ins.XSH`、`xonsh.cli_utils.{Annotated,Arg,ArgParserAlias}`、
`pygments.highlight`（原样返回文本）、`pygnuutils.ls.LsStub`（空基类）、
`IPython.start_ipython`（抛错）、`traitlets.config.Config`。

- **实现**：
  - `STUBS_DIR="$SCRIPT_DIR/stubs"`，`main()` 在 preflight 之后
    `export PYTHONPATH="$STUBS_DIR:$PYTHONPATH"`。
  - `verify_bundle()` 增加泄漏自检：若产物里出现 `xonsh/parsers`、`prompt_toolkit`、
    `pygments/lexers` 等真包目录，则 `warn`。
- **验证**：先用 venv 解释器加 stub 到 PYTHONPATH，逐个 `import` 上述
  pymobiledevice3 模块 + 实例化 `AfcService/CrashReportsManager/ServiceConnection`，
  确认导入成功且无真包泄漏（秒级，省去 16 分钟构建试错）。

## 三、已确认无法安全移除的部分

- **libx265（8MB）**：HEVC 编码器，但 `libheif` 在**链接期硬依赖**它（非 dlopen），
  删除会导致 dyld 加载 libheif 失败 → 破坏全部 HEIC 相册解码。
- **xonsh/pygments 等被 stub 后剩余的真实必需依赖**：cryptography、qh3、pydantic、
  construct、pykdebugparser、fastapi、anyio 等均为运行期实际使用。
- 主二进制剩余约 100MB 为 pymobiledevice3 核心 + 上述必需依赖的编译产物，已是干净极限。

## 四、维护注意

1. **album（相册）是 AfcService 的主要消费方**，冒烟测试只覆盖了启动+设备配对，
   未实际拉取照片。功能上安全（相册路径不碰 stub 符号），但升级或改动后建议手动
   点一下相册做最终确认。
2. **pymobiledevice3 升级后**：若构建日志出现 `Shell-dep stubbing leaked` 告警，
   或启动 smoke test 报 `ImportError`，说明该版本导入了新的 shell 符号，按
   `packaging/stubs/README.md` 的符号表补齐对应 stub 即可。
3. **strip / prune / stub 任何修改 bundle 的步骤之后，签名步骤必须最后执行**，
   否则 arm64 启动即被 SIGKILL。

## 五、验证手段速查

```bash
# 体积
du -sh build/nuitka/CablediOS.app

# 签名有效性（必须 VALID，否则 arm64 启动被杀）
codesign --verify --strict build/nuitka/CablediOS.app && echo VALID

# stub 是否生效（应无真包目录）
ls build/nuitka/CablediOS.app/Contents/MacOS/{xonsh,prompt_toolkit,pygments/lexers} 2>/dev/null

# 启动冒烟（macOS 无 timeout，用 python 看门狗，6s 后杀）
.venv/bin/python - build/nuitka/CablediOS.app/Contents/MacOS/CablediOS <<'PY'
import subprocess, sys, time
p = subprocess.Popen([sys.argv[1]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(6); alive = p.poll() is None
p.terminate()
print("ALIVE:", alive, "| RC:", p.returncode)
print((p.stdout.read() or "")[-1500:])
PY
```
