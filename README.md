# 良禽官网公开内容 CLI

`liangqin_public_cli.py` 是只依赖 Python 标准库的只读 CLI，只发 HTTPS `GET`，不需要 WordPress 凭据。

无 `--type` 时保留旧产品目录合同：`get --code`、`search`、`list`/`public-products` 走 `/wp-json/lq/v1/products`，并继续支持 `--presentation-mode`、`--category`、`--space`。

带 `--type` 时使用统一内容接口。客户端支持的类型为 `all/product/scene/case/faq/news/location/service/review/designer/authority/factory/award/report/brand`，搜索模式为 `lexical/hybrid/semantic`。

```bash
python3 liangqin_public_cli.py describe --output json
python3 liangqin_public_cli.py schema --output json
python3 liangqin_public_cli.py capabilities --output json
python3 liangqin_public_cli.py get --code SG-01 --output json
python3 liangqin_public_cli.py search --search 书柜 --presentation-mode product_detail --output json
python3 liangqin_public_cli.py list --type product --search 书柜 --mode hybrid --per-page 20 --output json
python3 liangqin_public_cli.py get --type case --id 123 --output json
python3 liangqin_public_cli.py get --type product --code SG-01 --output json
```

统一内容集合请求为 `/wp-json/lq/v1/content?type=...&search=...&mode=...&per_page=...&page=...`；记录请求为 `/wp-json/lq/v1/content/TYPE/ID`。`capabilities` 实时 GET `/wp-json/lq/v1/capabilities`。

`describe` 和 `schema` 描述的是 CLI 客户端支持范围，不代表所有类型或模式已经部署。服务端可用性以 `capabilities` 的实时响应为准。统一内容集合应提供 `items/count/total/page/per_page/total_pages/search_mode/requested_mode/degraded/schema_version`；单记录响应会在 CLI 中统一包装到 `items[0]`。

`--per-page` 范围是 1–100；`--all-pages` 最多按服务端 `total_pages` 抓取 100 页。参数冲突会返回 `error.code=argument_error`，网络或服务端不可用返回 `public_endpoint_unavailable`。

统一内容记录会同时返回稳定的 `id` 和 WordPress `source_id`。案例、FAQ、新闻等内容的单条读取优先使用返回的 `source_id`，例如：

```bash
python3 liangqin_public_cli.py get --type case --id 22791 --output json
```

`source_id` 只有在对应记录仍通过官网公开投影并且单条接口返回 HTTP 200 时才可读取。`case` 列表是案例域的完整公开列表；`all` 是跨类型公开投影集合，可能因为记录无法投影到统一类型而少于 `case` 列表。当前线上已知有 4 条案例（`source_id`：`17688`、`22032`、`19092`、`19118`）出现在 `case` 列表、但不出现在 `all`，其单条接口返回 404；机器人遇到这类记录应保留列表记录和官网 `url`，不要把 404 推断为案例不存在。
