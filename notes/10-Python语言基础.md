# 10 · Python 语言基础 —— 从零开始

> 这篇笔记用本项目 `config.py` 里的 `RSS_SOURCES` 作为教学案例，  
> 解释 Python 最基本的语言概念。适合完全没接触过编程的读者。

---

## 1. 变量：给数据贴标签

```python
MAX_ENTRIES = 100          # 给整数 100 贴上标签 "MAX_ENTRIES"
name = "36氪"               # 给字符串贴上标签 "name"
```

`=` 不是数学里的"等于"，是**赋值**：把右边的值存到左边的名字里。

---

## 2. 数据类型：数据的"种类"

Python 有 5 种基础类型：

```python
100                          # int     整数
0.5                          # float   小数
"hello"                      # str     字符串（双引号或单引号都行）
True / False                 # bool    布尔值（是/否）
None                         # NoneType 空值，"什么都没有"
```

**同一个变量可以换类型**（Python 是动态类型语言）：

```python
x = 100        # x 现在是 int
x = "hello"    # x 现在变成 str — 完全合法
```

---

## 3. 列表（list）：装着东西的盒子

```python
sources = ["纽约时报中文", "36氪", "BBC中文"]
#          [0]              [1]     [2]
```

| 操作 | 代码 | 结果 |
|------|------|------|
| 取元素 | `sources[0]` | `"纽约时报中文"` |
| 取最后一个 | `sources[-1]` | `"BBC中文"` |
| 取前N个 | `sources[:2]` | `["纽约时报中文", "36氪"]` |
| 长度 | `len(sources)` | `3` |
| 追加 | `sources.append("爱范儿")` | 列表变长了 |
| 遍历 | `for s in sources:` | 逐个取出 |

**列表里能装任何东西**：

```python
mixed = [42, "hello", True, None]     # 一个列表混合不同类型 — 可以但不常见
numbers = [1, 2, 3, 4, 5]            # 实践中通常放同类型
```

---

## 4. 字典（dict）：键值对

```python
student = {
    "name": "小明",
    "age": 20,
    "score": 95.5
}
```

`"name"`、`"age"` 叫**键（key）**，`"小明"`、`20` 叫**值（value）**。

```python
student["name"]          # → "小明"
student.get("grade", 0)  # → 0 (键不存在时返回默认值，不报错)
student["email"]         # ❌ KeyError! 键不存在会报错
```

---

## 5. RSS_SOURCES 到底是什么？

回到项目代码：

```python
RSS_SOURCES = [
    {"name": "纽约时报中文", "urls": [
        "https://cn.nytimes.com/rss/",
        "https://rsshub.app/nytimes/zh-Hans",
    ]},
    {"name": "36氪", "urls": ["https://36kr.com/feed"]},
    {"name": "BBC中文", "urls": ["https://www.bbc.com/zhongwen/simp/index.xml"]},
]
```

### 逐层拆解

```
RSS_SOURCES           ← 这是一个 list（方括号 [...]）
    │
    ├── [0] 是一个 dict（花括号 {...}）
    │       │ 键 "name"  → 值 "纽约时报中文"（str）
    │       │ 键 "urls"  → 值 [...]（又是一个 list!）
    │       │               ├── "https://cn.nytimes.com/rss/"
    │       │               └── "https://rsshub.app/nytimes/zh-Hans"
    │
    ├── [1] 是一个 dict
    │       │ 键 "name"  → 值 "36氪"（str）
    │       │ 键 "urls"  → 值 ["https://36kr.com/feed"]（list，但只有 1 个元素）
    │
    └── [2] 是一个 dict
            │ 键 "name"  → 值 "BBC中文"（str）
            │ 键 "urls"  → 值 ["https://www.bbc.com/zhongwen/simp/index.xml"]（也是 1 元素 list）
```

### 为什么每个 dict 的 url 数量可以不一样？

```python
{"urls": ["url1", "url2"]}   # ← list 里有 2 个字符串
{"urls": ["url1"]}           # ← list 里只有 1 个字符串
```

**list 的长度完全独立**，不受其他 dict 影响。Python 的 list 不需要提前声明长度，想放几个元素就放几个。

### 代码怎么访问这些数据？

```python
# 取第一个源
src = RSS_SOURCES[0]           # {"name": "纽约时报中文", "urls": [...]}

# 取它的名字
src["name"]                    # "纽约时报中文"

# 取它的 URL 列表
src["urls"]                    # ["https://cn.nytimes.com/rss/", "https://rsshub.app/..."]

# 取第一个 URL
src["urls"][0]                 # "https://cn.nytimes.com/rss/"

# 遍历所有源
for src in RSS_SOURCES:        # src 每次是一个 dict
    print(src["name"])         # 打出每个源的名字
    for url in src["urls"]:    # url 每次是一个字符串
        print(f"  {url}")      # 打出这个源的所有 URL
```

Chrome 的 F12 Console 里也可以这么写 JavaScript 对象，逻辑是一样的——**嵌套结构**。

---

## 6. import 到底做了什么？

```python
import os                     # ① 告诉 Python 我要用这个模块
from pathlib import Path      # ② 从某个模块里指名要一个东西
from config import RSS_SOURCES # ③ 从自己的文件里取值
```

### 当你写 `import os` 时发生了什么？

```
1. Python 在硬盘上找到 os.py（标准库自带的文件）
2. 执行 os.py 里的所有代码（定义函数、类、变量）
3. 把执行结果包装成一个 module 对象
4. 在当前文件里创建一个叫 os 的变量，指向这个对象
5. 之后 os.getenv(...) 就是调用这个对象里的 getenv 函数
```

### `from X import Y` vs `import X`

```python
# 方式 A
import os
os.getenv("KEY")            # 每次要用 os. 前缀

# 方式 B
from os import getenv
getenv("KEY")               # 直接用，不需要前缀
```

区别只是命名空间：A 方式保留了 `os.` 前缀，不会和当前文件的变量重名。B 方式简洁但如果当前文件也有 `getenv` 就会覆盖。

### 为什么能做到"从另一个文件取值"？

```python
# config.py 的内容:
RSS_SOURCES = [...]    # ← 这行代码在 Python 眼里是: 创建一个变量

# summarizer.py 的内容:
from config import RSS_SOURCES  # ← 这行是: 去找 config.py 里的 RSS_SOURCES 变量，拿过来用
```

这和你把两段代码写在一个文件里没有本质区别——**import 只是帮你"跨文件引用变量"**。

---

## 7. 函数调用：向一个黑盒扔数据

```python
os.getenv("MAX_ENTRIES", "100")
#  ^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^
#  函数名      参数（arguments）
```

这是 Python 中最常见的操作：**调用函数——给它输入，它给你输出**。

```python
# 内置函数示例
len([1, 2, 3])             # → 3
int("100")                 # → 100 (字符串转整数)
float("0.5")               # → 0.5 (字符串转小数)
str(100)                   # → "100" (整数转字符串)
print("hello")             # → 打印到终端，返回 None
```

---

## 8. 常见误区

### `=` vs `==`

```python
x = 5       # 赋值: 把 5 存到 x 里
x == 5      # 比较: x 等于 5 吗？ → True
```

### 字符串引号

```python
"hello"    # 双引号
'hello'    # 单引号 — 完全等价
```

如果字符串里本身有引号，可以交替使用：
```python
"他说'你好'"    # 双引号包单引号
'他说"你好"'    # 单引号包双引号
```

### 缩进（indent）

Python 用缩进表示代码块，不能用 `{}` 或 `BEGIN/END`：

```python
if True:
    print("这里缩进了 4 个空格")    # 正确
  print("这里只缩进了 2 个空格")    # 错误！要么 4 要么 Tab，必须统一
```

---

## 学习路线

```
变量和赋值 → 基本类型 → list/dict → 嵌套结构 → import → 函数调用 → 写自己的函数
```

本项目的 `config.py` 是练习读代码的绝佳起点——它只有变量定义，没有控制流。打开它，对照本笔记逐行理解。

---

→ 返回: [[00-目录]]
