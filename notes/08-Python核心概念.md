# 08 · Python 核心概念速查

> 这篇笔记梳理了本项目用到的所有 Python 核心概念，按"先会什么再看什么"的顺序排列。

---

## 数据类型基础

```python
# 字符串
"hello"           # 普通字符串
f"值={x}"         # f-string: 变量嵌入

# 数字
42                # 整数 int
0.5               # 浮点数 float

# 布尔
True / False

# 列表 (有序, 可变)
items = ["a", "b", "c"]
items.append("d")        # 追加
items[0]                 # 取第0个 → "a"
items[:5]                # 切片: 前5个
items.sort(key=..., reverse=True)

# 字典 (无序, 键值对)
d = {"key": "value", "count": 42}
d["key"]                 # 取值
d.get("missing", "默认")  # 安全取值
d.setdefault("new", [])  # 键不存在时新建

# 元组 (有序, 不可变)
t = (1, 2, 3)
# 常用于: 坐标、函数返回多个值

# None
x = None  # 表示"没有值"
if x is None: ...  # 判断是否为 None (不要用 ==)
```

---

## 控制流

```python
# 条件
if condition:
    do_something()
elif other:
    do_other()
else:
    fallback()

# 循环
for item in list:        # 遍历
    ...

while True:              # 无限循环 + break
    ...
    if done:
        break

# continue: 跳过本轮循环剩余代码
for x in items:
    if x == "跳过":
        continue
    process(x)

# try/except: 异常处理
try:
    risky_operation()
except SomeError:
    handle_error()
else:
    success_action()      # 没异常时执行
```

---

## 函数

```python
def 函数名(参数1, 参数2="默认值"):
    """文档字符串: 这函数做什么"""
    结果 = 参数1 + 参数2
    return 结果     # 返回给调用方

# 无返回值 → 隐式 return None
```

---

## import 系统

```python
# 导入模块
import os                        # 标准库
from datetime import datetime    # 标准库的某个名字
from config import AI_MODEL      # 项目内模块的某个名字
```

**运行机制**:
1. Python 遇到 `import xxx` → 搜索 `sys.path` 中的目录
2. 找到 `xxx.py` → **执行整个文件**（定义函数和变量）
3. 把执行后的结果缓存到 `sys.modules`
4. 第二次 `import xxx` → 直接拿缓存，不重新执行

**这意味着**:
- `config.py` 只在第一次 import 时执行，`load_dotenv()` 也只调用一次
- 如果模块里有 `print()`，只在第一次 import 时输出

---

## 推导式

```python
# 列表推导式
tags = [t.strip() for t in "标签1, 标签2".split(",")]
# → ["标签1", "标签2"]

# 字典推导式
indices = {s: 0 for s in ["36氪", "BBC"]}
# → {"36氪": 0, "BBC": 0}

# 等价于:
indices = {}
for s in ["36氪", "BBC"]:
    indices[s] = 0
```

---

## 正则表达式

```python
import re

# match: 字符串开头匹配
re.match(r"^HEADLINE:", text)

# search: 任意位置匹配
m = re.search(r"HEADLINE:\s*(.+)", text)
m.group(0)  # 完整匹配
m.group(1)  # 第一个括号捕获的内容

# flags
re.MULTILINE  # ^ $ 匹配每行
re.DOTALL     # . 也匹配换行符
```

---

## 文件操作

```python
# 读整个文件
from pathlib import Path
text = Path("file.txt").read_text(encoding="utf-8")

# 写文件
Path("output.txt").write_text("content", encoding="utf-8")

# 拼接路径
Path("dir") / "subdir" / "file.txt"
# → dir/subdir/file.txt (跨平台)
```

---

## 环境变量

```python
import os

key = os.getenv("MY_KEY")            # 不存在 → None
key = os.getenv("MY_KEY", "默认值")  # 不存在 → "默认值"

# .env 文件加载
from dotenv import load_dotenv
load_dotenv()  # 读取 .env → 写入 os.environ
```

---

## 日志

```python
import logging

# 一次性的全局配置（在程序入口处配置一次）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# 在每个模块中创建自己的 logger
logger = logging.getLogger(__name__)

# 使用
logger.info("正常信息")
logger.warning("警告但能继续")
logger.error("出错但不崩溃")
```

---

## 下一级概念（进阶）

| 概念 | 在本项目哪里 | 什么时候学 |
|------|-------------|-----------|
| `**kwargs` | publisher.py `_retry_request()` | 理解了 dict 之后 |
| `lambda` | fetcher.py `sort(key=lambda...)` | 理解了函数之后 |
| `*struct[:6]` 解包 | fetcher.py | 理解了列表/元组之后 |
| `or` 链短路 | config.py 密钥回退 | 理解了布尔值之后 |
| `setdefault` | summarizer.py 分组 | 理解了 dict 之后 |

---

→ 返回: [[00-目录]]
