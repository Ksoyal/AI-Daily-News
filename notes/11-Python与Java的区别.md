# 11 · Python 与 Java 的区别 —— 写给有 Java 基础的人

> 如果你写过 Java，学 Python 最大的障碍不是"新概念"，而是"旧习惯"。  
> 这篇笔记列出最重要的差异，用本项目的真实代码对比说明。

---

## 1. 变量为什么不用声明类型？

### Java 写法

```java
String name = "36氪";          // 必须写类型
int count = 0;                 // 必须写类型
List<Map<String, Object>> sources = new ArrayList<>();  // 必须写完整的泛型
```

### Python 写法

```python
name = "36氪"           # 类型自动推断
count = 0               # 没有 int 关键字
sources = []            # 没有泛型，没有 new
```

**原因**：Python 是**动态类型语言**。变量只是一个标签，贴到哪个数据上就是什么类型，运行时才确定。

```python
x = 100        # x 现在指向一个 int 对象
x = "hello"    # x 现在指向一个 str 对象 — Java 里这不可能编译通过
```

**Java 类比**：相当于所有变量都自动用 `var` 声明（Java 10+ 的局部变量类型推断），但 Python 把它做到了极致——连 `var` 都不用写。

---

## 2. list 为什么不需要 new 也不需要指定长度？

### Java 写法

```java
// 方式 A: 固定长度数组
String[] urls = new String[3];      // 必须指定长度 3
urls[0] = "https://...";

// 方式 B: ArrayList（可变）
List<String> urls = new ArrayList<>();  // 需要 import java.util.List
urls.add("https://...");
```

### Python 写法

```python
urls = []                         # 这行就够了
urls.append("https://...")        # 自动变长
urls.append("https://...")        # 想加多少加多少

# 或者直接初始化:
urls = ["url1", "url2", "url3"]   # 和数组字面量一样简洁
```

**原因**：Python 的 `list` 底层是一个动态数组，自动管理扩容。不需要 `new` 因为 Python 没有 `new` 关键字——所有对象创建都隐式完成。

---

## 3. 字典（dict）就是 Java 的 Map

```java
// Java: HashMap
Map<String, Object> src = new HashMap<>();
src.put("name", "36氪");
src.put("urls", Arrays.asList("url1", "url2"));
```

```python
# Python: dict
src = {
    "name": "36氪",
    "urls": ["url1", "url2"]
}
```

Python 的 `{}` 字面量语法比 Java 的 `new HashMap<>()` + `put()` 简洁得多。而且 Python dict 的键可以是任何不可变类型（字符串、数字、元组），Java Map 需要泛型。

---

## 4. for 循环的"变量"从哪来的？

### Java 写法（三种循环）

```java
// 方式 A: 传统 for
for (int i = 0; i < list.size(); i++) {
    String item = list.get(i);    // 先声明 item, 再赋值
}

// 方式 B: 增强 for
for (String item : list) {        // item 在前面声明类型
    System.out.println(item);
}

// 方式 C: Stream
list.stream().forEach(item -> System.out.println(item));
```

### Python 写法（只有一种）

```python
for item in list:
    print(item)
```

**`item` 是自动创建的**，不需要提前声明。每次循环迭代时，Python 自动把 list 的下一个元素赋给 `item`。

```python
# 本项目的实际代码:
for src in RSS_SOURCES:          # src 没在任何地方声明过！
    for url in src["urls"]:      # url 也没声明过！循环体里凭空出现
        try:
            resp = requests.get(url, ...)
```

**Java 思维**: "`src` 是什么类型？我在哪声明它？"
**Python 思维**: "`src` 就是 `RSS_SOURCES` 里的元素，管它什么类型。"

---

## 5. 条件表达式可以直接"凭空"用变量

```python
# 本项目 fetcher.py 的代码:
if feed is None:              # feed 在 20 行前的 for 循环里首次赋值
    logger.warning(...)        # Python: 完全合法！
    continue
```

Java 要求变量在它所在的**作用域**（最近的一对 `{}`）内声明。Python 的作用域规则不同：

```java
// Java: 编译错误！
for (String url : urls) {
    int statusCode = get(url);
}
System.out.println(statusCode);  // ❌ statusCode 在 for 的 {} 外不可见
```

```python
# Python: 完全合法
for url in urls:
    status_code = get(url)
print(status_code)                # ✅ 可见！for 循环不创建新作用域
```

**Python 中只有函数和类会创建新作用域**。`if`、`for`、`while`、`try` 块内的变量在块外照样可见。

---

## 6. 没有 `public` / `private` / `protected`

```java
// Java
public class Fetcher {
    private int maxEntries = 100;       // 只有本类能访问
    public List<News> fetchNews() { ... }  // 谁都能调用
}
```

```python
# Python
MAX_ENTRIES = 100              # 模块级变量，谁都能访问

def fetch_news():              # 模块级函数，谁都能调用
    ...
```

Python 的约定：`_single_underscore` 前缀表示"请勿直接使用"（靠自觉，没有编译器强制）。本项目 `_parse_published()` 和 `_build_news_text()` 都用了这个约定。

---

## 7. 没有 `void` 返回类型

```java
// Java
public void doSomething() {   // void 表示不返回值
    System.out.println("done");
}
```

```python
# Python
def do_something():           # 没写返回类型 → 隐式返回 None
    print("done")
    # return None   ← 这行是隐式的
```

**每个 Python 函数都返回值**。如果不写 `return`，自动返回 `None`（类似 Java 的 `null`）。

---

## 8. `self` = `this`，但必须显式写

```python
# Python
class Student:
    def __init__(self, name):    # 构造函数，self 必须显式写
        self.name = name         # self.name = this.name
    
    def greet(self):             # self 必须作为第一个参数
        print(f"Hi, I'm {self.name}")
```

```java
// Java
class Student {
    private String name;
    
    public Student(String name) {  // 没有 this 参数
        this.name = name;
    }
    
    public void greet() {          // 没有 this 参数
        System.out.println("Hi, I'm " + this.name);
    }
}
```

> 本项目没有自己定义类，用的是函数 + 模块的组织方式。这是 Python 的风格——不是所有代码都需要面向对象。

---

## 9. "导入"的含义完全不同

### Java

```java
import java.util.List;    // 这只是编译时的"快捷方式"
                          // 类在 JVM 启动时已经全部加载
```

### Python

```python
from config import RSS_SOURCES   # 这行真的会执行 config.py
                                 # 创建一个变量 RSS_SOURCES 指向配置
```

**Python 的 import 是运行时行为**：导入时真的**执行**那个文件，把结果缓存起来。这也解释了为什么 `config.py` 里的 `load_dotenv()` 只在第一次 import 时执行一次。

---

## 10. 本项目对照表

| Java 概念 | Python 等价 | 在哪里用到 |
|-----------|------------|-----------|
| `String[]` / `ArrayList` | `list` = `[...]` | `RSS_SOURCES` |
| `HashMap` | `dict` = `{...}` | `{"name": "36氪", "urls": [...]}` |
| `for (T x : list)` | `for x in list:` | fetcher.py 逐源遍历 |
| `try { ... } catch (E e)` | `try: ... except E:` | fetcher.py 异常隔离 |
| `new Type()` | `Type()`（没有 new） | `datetime.now(timezone.utc)` |
| `null` | `None` | `if x is None: raise ...` |
| `public/private` | `_prefix` 命名约定 | `_parse_published()` |
| `import java.util.*` | `from config import *`（不推荐） | `from config import AI_MODEL` |
| `void method()` | `def method():` 隐式返回 None | `fetch_news()` |
| `static` 方法 | 模块级函数 | 项目所有函数都是模块级的 |
| `System.out.println` | `print()` / `logger.info()` | 到处 |

---

→ 返回: [[00-目录]]  
→ 继续: [[10-Python语言基础]]（如果还没看过）
