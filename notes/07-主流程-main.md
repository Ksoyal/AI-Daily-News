# 07 · 主流程 main.py

> 这是项目的**指挥中心**。不包含复杂的业务逻辑，只做一件事：按顺序调用前三个模块。

## 整体流程

```
Python 进程启动
    │
    ├── logging.basicConfig()     ← 全局日志格式
    ├── load_dotenv()             ← 加载 .env
    ├── import 三个模块
    │
    └── main():                   ← 入口函数
        ├── [1/3] fetch_news()    → news (100 条)
        ├── [2/3] generate_report(news) → report dict
        ├── [3/3] push_to_notion(report) → Notion 页面
        └── notify("✅ 成功")
        
        except:
        └── notify("❌ 失败")
```

## 逐段讲解

### 日志配置（必须在 import 之前）

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
```

**为什么在 import 之前？** 因为 import 语句会执行被导入模块的顶层代码（包括 `logger = logging.getLogger(__name__)`）。如果此时还没配置好 logging，那些 logger 就无法使用正确的格式。

输出效果:
```
2026-06-04 08:00:01 [INFO] __main__: [1/3] Fetching news...
2026-06-04 08:00:03 [INFO] fetcher: 36氪: 29 entries accepted
```

### 主函数

```python
def main():
    logger.info(f"=== AI-Daily-News {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    try:
        # ── 第一步：抓取 ──
        logger.info("[1/3] Fetching news...")
        news = fetch_news()
        logger.info(f"Got {len(news)} entries")
        
        # ── 第二步：总结 ──
        logger.info("[2/3] Generating report...")
        report = generate_report(news)
        logger.info(f"Report: headline='{report['headline']}', "
                    f"tags={report['tags']}, body={len(report['content'])} chars")
        
        # ── 第三步：发布 ──
        logger.info("[3/3] Pushing to Notion...")
        push_to_notion(report)
        logger.info("Published successfully")
        
        # ── 推送成功通知 ──
        notify(f"✅ {report['headline']}",
               f"共 {len(news)} 条 | {'/'.join(report['tags'])}")
        logger.info("=== All done ===")
    
    except Exception as e:
        # ── 任何步骤失败都会到这里 ──
        err_msg = f"{type(e).__name__}: {e}\n\n```\n{traceback.format_exc()}\n```"
        logger.error(f"Pipeline failed: {err_msg}")
        notify("❌ AI晨报运行失败", err_msg)
        sys.exit(1)  # 非零退出码 → GitHub Actions 标记为失败
```

### 手机推送

```python
PUSH_KEY = os.getenv("PUSH_KEY")
SC_URL = f"https://sctapi.ftqq.com/{PUSH_KEY}.send" if PUSH_KEY else None

def notify(title, desp=""):
    if not SC_URL:
        return    # 没设 PUSH_KEY，静默跳过
    try:
        resp = requests.post(SC_URL, data={"title": title, "desp": desp})
        resp.raise_for_status()
    except requests.RequestException:
        pass    # 推送失败不影响主流程
```

**新知**: 条件赋值
```python
x = value if condition else other
# 等价于:
if condition:
    x = value
else:
    x = other
```

### 程序入口

```python
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
```

**为什么需要 `if __name__ == "__main__"`?**

```python
# 当 python main.py 直接运行时 → __name__ = "__main__" → 执行 main()
# 当 import main 被其他文件导入时 → __name__ = "main" → 不执行 main()
```

这样 `from main import notify` 不会触发主流程，只在直接运行时才执行。

`sys.stdout.reconfigure(encoding="utf-8")` — Windows 终端默认编码可能不是 UTF-8，强制设成 UTF-8 避免中文乱码。

---

## 本模块学到的 Python 知识点

| 概念 | 场景 |
|------|------|
| `logging.basicConfig()` | 全局日志配置 |
| `try/except Exception` | 捕获所有异常 |
| `sys.exit(1)` | 非零退出码 |
| `traceback.format_exc()` | 获取完整调用栈字符串 |
| `str.join()` | `'/'.join(tags)` → "标签1/标签2/标签3" |
| `f"{var}"` 格式化 | 日志信息的拼接 |
| `if __name__ == "__main__"` | 区分"导入"和"直接运行" |

---

→ 下一步: [[09-定时任务与CI]]
