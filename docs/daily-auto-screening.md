# 每日自动追加分析候选

每日 Actions 先准备股票池，再执行原有分析与推送。固定 `STOCK_LIST` 保留，`STOCK_LIST_EXTRA` 可追加固定股票（例如用户指定的代码）；自动候选仅修改本次进程环境，不写回 GitHub Secret/Variable。不要将昨日候选写入固定配置。

## Actions Repository variables

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| STOCK_LIST_EXTRA | 空 | 逗号分隔固定追加股票 |
| AUTO_SCREEN_ENABLED | false | true 启用自动筛选 |
| AUTO_SCREEN_MARKETS | cn,hk,us | 三市场按顺序轮流分配候选名额 |
| AUTO_SCREEN_MAX_ADDITIONS | 5 | 全部市场合计每日追加上限，最大 20 |
| AUTO_SCREEN_MARKET_TIMEOUT | 90 | 每市场最多运行秒数，失败保留固定自选 |
| AUTO_SCREEN_UNIVERSE_LIMIT | 50 | 港美股候选 universe 数量限制 |
| AUTO_SCREEN_US_UNIVERSE | default | 内置美股大型股 universe；可改 env 或 sp500 |
| SCREENING_US_TICKERS | 空 | universe=env 时读取的美股代码 |

放量突破、价值质量、趋势质量三种风格独立运行后取并集，复用内置 hard filters、日 K 特征与 factor scores。规则配置为 `config/auto-screening.yaml`；A 股使用内置策略原规则，港美股显式覆写本币成交额、市值门槛与价格限制，不把人民币绝对价格条件直接搬到其他市场。价格/成交额是当地货币单位，各市场内部排名后轮流取票，不将跨市场分数当成可比收益。

A 股从现有全市场快照源筛选。港股以 AkShare 港股快照成交额最高的前 50 只为 universe，再使用现有 yfinance adapter 获取指标；美股默认内置大型股 universe（最多 50 只），并非整个美股市场扫描。范围和阈值可以修改，增加范围会增加请求数及耗时。未取到估值或日 K 等必需字段的股票不视为匹配；某策略或市场失败会记录警告，不伪造候选或不足数量补票。需要日 K 的策略默认最多深查 5 只快照初筛股票，纯快照策略使用整个初筛池，避免全市场日 K 扫描。

`reports/daily_stock_pool.json` 记录最终追加股票、命中策略、分数及错误摘要；`reports/daily_stock_pool.txt` 为本次完整股票列表，随原报告产物上传。非交易日手动运行使用最近可取得行情，不代表当日新行情。筛选负责发现候选，后续原有 LLM 分析负责生成报告。

本地可运行：`AUTO_SCREEN_ENABLED=true STOCK_LIST=600519 python scripts/prepare_daily_stock_pool.py --output reports/daily_stock_pool.txt`。脚本不会修改本地 `.env`；本地定时服务、Web 及选股 API 行为不变，这次仅接入每日 Actions。停用时设 `AUTO_SCREEN_ENABLED=false`，仍保留固定追加列表；整体回滚 revert 对应提交，无数据迁移。本专题没有英文对应文件，双语首页未变更。

仅大盘复盘模式跳过选股。快照策略先完成并保存中间结果，日 K 策略超时仍保留已完成候选；追加数量格式错误时回退默认 5。A 股沿用现有快照缓存路径、TTL 和最大回退时效。

美股份额候选按内部格式规范化（例如 Yahoo `BRK-B` 转为 `BRK.B`），避免被国内行情适配器处理；调用 Yahoo 历史及实时接口时再转回连字符。候选代码必须通过现有美股识别规则，指数或无法识别的符号不加入股票池。
