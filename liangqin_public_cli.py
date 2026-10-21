#!/usr/bin/env python3
"""Portable, read-only CLI for Liangqin public content APIs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import typing as t
import urllib.error
import urllib.parse
import urllib.request

CLI_VERSION = "1.1.1"
DEFAULT_SITE_URL = "https://www.liangqinjiamu.com"
PRODUCTS_PATH = "/wp-json/lq/v1/products"
CONTENT_PATH = "/wp-json/lq/v1/content"
CAPABILITIES_PATH = "/wp-json/lq/v1/capabilities"
MAX_PER_PAGE = 100
DETAIL_MODES = ("product_detail", "scene_detail")
CONTENT_TYPES = ("all", "product", "scene", "case", "faq", "news", "location", "service", "review", "designer", "authority", "factory", "award", "report", "brand")
CONTENT_MODES = ("lexical", "hybrid", "semantic")


class PublicContentError(Exception):
    def __init__(self, message: str, *, code: str = "public_content_error", details: dict[str, t.Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class PublicArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> t.NoReturn:
        raise PublicContentError(message, code="argument_error")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--site-url", default=os.environ.get("LIANGQIN_SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--type", dest="content_type", choices=CONTENT_TYPES, help="启用统一公开内容接口。")
    parser.add_argument("--mode", choices=CONTENT_MODES, help="统一内容搜索模式。")
    parser.add_argument("--search", help="搜索公开内容。")
    parser.add_argument("--code", help="旧产品接口 SKU，或 product/scene 内容接口的 code。")
    parser.add_argument("--id", dest="record_id", help="统一内容接口记录 ID。")
    parser.add_argument("--per-page", type=int, default=24)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--all-pages", action="store_true", help="抓取所有结果页；最多按服务端 total_pages 分页。")
    parser.add_argument("--output", choices=("json",), default="json")


def _add_legacy_query_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--presentation-mode", choices=DETAIL_MODES, default="product_detail")
    parser.add_argument("--category", help="Product category slug; applies to product_detail.")
    parser.add_argument("--space", help="Scene space slug; applies to scene_detail.")


def build_parser() -> argparse.ArgumentParser:
    parser = PublicArgumentParser(description="Read Liangqin public content. Read-only; no credentials required.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("describe", "Describe client support and server capabilities."), ("schema", "Return machine-readable schemas.")):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--output", choices=("json",), default="json")
    capabilities = subparsers.add_parser("capabilities", help="Live GET server content capabilities.")
    capabilities.add_argument("--site-url", default=os.environ.get("LIANGQIN_SITE_URL", DEFAULT_SITE_URL))
    capabilities.add_argument("--timeout", type=int, default=20)
    capabilities.add_argument("--output", choices=("json",), default="json")
    for name, aliases, help_text in (("public-products", ("list",), "List public products/scenes."), ("search", (), "Search public products or typed content."), ("get", (), "Get one public record.")):
        sub = subparsers.add_parser(name, aliases=aliases, help=help_text)
        _add_common(sub)
        _add_legacy_query_arguments(sub)
    return parser


def _normalise_site_url(value: str) -> str:
    site_url = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(site_url)
    if not site_url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PublicContentError("官网地址必须是完整的 http(s) URL。", code="argument_error")
    return site_url


def _validate_page_args(args: argparse.Namespace) -> None:
    if args.per_page < 1 or args.per_page > MAX_PER_PAGE:
        raise PublicContentError(f"--per-page 必须在 1–{MAX_PER_PAGE} 之间。", code="argument_error")
    if args.page < 1:
        raise PublicContentError("--page 必须大于等于 1。", code="argument_error")


def _reject(condition: bool, message: str) -> None:
    if condition:
        raise PublicContentError(message, code="argument_error")


def _legacy_url(args: argparse.Namespace, *, page_override: int | None = None) -> tuple[str, str, dict[str, t.Any]]:
    _validate_page_args(args)
    page = args.page if page_override is None else page_override
    query: dict[str, t.Any] = {"presentation_mode": args.presentation_mode, "orderby": "catalog", "per_page": args.per_page, "page": page}
    for key in ("category", "space", "search", "code"):
        value = getattr(args, key, None)
        if value:
            query[key] = str(value).strip().upper() if key == "code" else value
    return _normalise_site_url(args.site_url) + PRODUCTS_PATH + "?" + urllib.parse.urlencode(query), PRODUCTS_PATH, query


def _typed_url(args: argparse.Namespace, *, page_override: int | None = None) -> tuple[str, str, dict[str, t.Any]]:
    _validate_page_args(args)
    content_type = args.content_type
    _reject(not content_type, "统一内容参数必须提供 --type。")
    _reject(bool(args.presentation_mode != "product_detail" or args.category or args.space), "使用 --type 时不能使用 --presentation-mode、--category 或 --space。")
    _reject(args.command != "get" and bool(args.record_id), "--id 只适用于 get。")
    if args.command == "get" and args.record_id:
        _reject(bool(args.code or args.search or args.mode or args.all_pages or args.page != 1 or args.per_page != 24), "get --type TYPE --id ID 不能同时使用 --code、--search、--mode、--all-pages 或分页参数。")
        path = f"{CONTENT_PATH}/{urllib.parse.quote(content_type, safe='')}/{urllib.parse.quote(str(args.record_id), safe='')}"
        return _normalise_site_url(args.site_url) + path, path, {}
    _reject(args.command == "get" and not args.code, "统一内容 get 必须提供 --id；product/scene 也可提供 --code。")
    _reject(args.command == "get" and args.code and content_type not in {"product", "scene"}, "统一内容 get 使用 --code 时，--type 只能是 product 或 scene；其他类型请使用 --id。")
    query: dict[str, t.Any] = {"type": content_type, "per_page": args.per_page, "page": args.page if page_override is None else page_override}
    if args.search:
        query["search"] = args.search
    if args.mode:
        query["mode"] = args.mode
    if args.code:
        query["code"] = str(args.code).strip().upper()
    return _normalise_site_url(args.site_url) + CONTENT_PATH + "?" + urllib.parse.urlencode(query), CONTENT_PATH, query


def _read_json(url: str, timeout: int) -> tuple[int, dict[str, t.Any], dict[str, str]]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"LiangqinPublicCLI/{CLI_VERSION} (+read-only)"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status = response.read(), int(response.status)
            headers = {str(key): str(value) for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        excerpt = exc.read(300).decode("utf-8", errors="replace").strip()
        raise PublicContentError(f"公开内容接口返回 HTTP {exc.code}。", code="public_endpoint_unavailable", details={"status": exc.code, "url": url, "response_excerpt": excerpt}) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PublicContentError(f"无法读取公开内容接口：{exc}", code="public_endpoint_unavailable", details={"url": url}) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicContentError("公开内容接口返回的不是合法 JSON。", code="invalid_public_response", details={"status": status, "url": url}) from exc
    if not isinstance(payload, dict):
        raise PublicContentError("公开内容接口返回格式异常：顶层必须是 JSON object。", code="invalid_public_response", details={"status": status, "url": url})
    return status, payload, headers


def _as_collection(data: dict[str, t.Any], *, requested_mode: str | None = None) -> dict[str, t.Any]:
    if isinstance(data.get("items"), list):
        return data
    item = data.get("item") if isinstance(data.get("item"), dict) else data
    return {"items": [item] if item else [], "count": 1 if item else 0, "total": 1 if item else 0, "page": 1, "per_page": 1, "total_pages": 1, "search_mode": data.get("search_mode"), "requested_mode": data.get("requested_mode", requested_mode), "degraded": bool(data.get("degraded", False)), "schema_version": data.get("schema_version")}


def _fetch_all_pages(args: argparse.Namespace, data: dict[str, t.Any], *, typed: bool, status: int, headers: dict[str, str]) -> tuple[int, dict[str, t.Any], dict[str, str]]:
    total_pages = min(int(data.get("total_pages") or 1), MAX_PER_PAGE)
    if total_pages <= 1:
        return status, data, headers
    combined = dict(data)
    items = list(data.get("items") or [])
    for page in range(2, total_pages + 1):
        url, _endpoint, _query = _typed_url(args, page_override=page) if typed else _legacy_url(args, page_override=page)
        _status, next_data, next_headers = _read_json(url, args.timeout)
        items.extend(list(next_data.get("items") or []))
        headers = next_headers or headers
    combined.update({"items": items, "count": len(items), "pages_fetched": total_pages, "all_pages": True})
    return status, combined, headers


def _success(command: str, *, site_url: str, endpoint: str, query: dict[str, t.Any], status: int, data: dict[str, t.Any], headers: dict[str, str]) -> dict[str, t.Any]:
    return {"ok": True, "command": command, "results": [{"read_only": True, "source": site_url, "endpoint": endpoint, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(), "http_status": status, "query": query, "data": data, "cache_headers": {key: headers[key] for key in ("ETag", "Last-Modified", "Cache-Control") if key in headers}}], "error": None}


def _local_success(command: str, data: dict[str, t.Any]) -> dict[str, t.Any]:
    return {"ok": True, "command": command, "results": [{"read_only": True, "source": DEFAULT_SITE_URL, "endpoint": "local", "data": data}], "error": None}


def _failure(command: str | None, exc: PublicContentError) -> dict[str, t.Any]:
    return {"ok": False, "command": command, "results": [], "error": {"code": exc.code, "message": str(exc), "details": exc.details}}


def _schema_data() -> dict[str, t.Any]:
    collection = {"required": ["items", "count", "total", "page", "per_page", "total_pages", "search_mode", "requested_mode", "degraded", "schema_version"], "properties": {"items": {"type": "array"}, "count": {"type": "integer"}, "total": {"type": "integer"}, "page": {"type": "integer"}, "per_page": {"type": "integer", "maximum": MAX_PER_PAGE}, "total_pages": {"type": "integer"}, "search_mode": {"type": ["string", "null"]}, "requested_mode": {"type": ["string", "null"], "enum": [*CONTENT_MODES, None]}, "degraded": {"type": "boolean"}, "schema_version": {"type": ["string", "integer"]}}}
    legacy_item = {"required": ["id", "code", "name", "slug", "detail_shape", "category", "space", "image", "gallery", "facts", "material_groups", "customization", "baseline_customization", "url"], "properties": {"id": {"type": "integer"}, "code": {"type": "string"}, "name": {"type": "string"}, "slug": {"type": "string"}, "detail_shape": {"type": "string", "enum": list(DETAIL_MODES)}, "category": {"type": "array"}, "space": {"type": "array"}, "image": {"type": ["string", "null"]}, "gallery": {"type": "array"}, "facts": {"type": "array"}, "material_groups": {"type": "array"}, "customization": {"type": ["array", "object"]}, "baseline_customization": {"type": ["array", "object"]}, "url": {"type": "string"}}}
    legacy_response = {"description": "Legacy products response; retained for compatibility.", "required": ["items", "count", "total", "page", "per_page", "total_pages"], "properties": {"items": {"type": "array", "items": {"$ref": "#/item"}}, "count": {"type": "integer"}, "total": {"type": "integer"}, "page": {"type": "integer"}, "per_page": {"type": "integer", "maximum": MAX_PER_PAGE}, "total_pages": {"type": "integer"}}}
    return {"schema_version": CLI_VERSION, "contract": "public-product-catalog", "public_content": {"contract": "public-content", "endpoint": CONTENT_PATH, "collection": collection, "single_record": {"description": "CLI 将单记录响应统一包装为 collection.items[0]。"}, "types": list(CONTENT_TYPES), "modes": list(CONTENT_MODES)}, "response": legacy_response, "item": legacy_item, "client_supported": {"types": list(CONTENT_TYPES), "modes": list(CONTENT_MODES), "pagination_max_per_page": MAX_PER_PAGE}, "server_availability": {"status": "runtime-dependent", "description": "是否部署、支持哪些 type/mode 以 capabilities 命令的实时 GET 结果为准；本地 schema 不作部署承诺。"}}


def _describe_data() -> dict[str, t.Any]:
    return {"cli_version": CLI_VERSION, "service": "liangqin-public-content", "website": DEFAULT_SITE_URL, "read_only": True, "credentials_required": False, "transport": "HTTPS GET", "endpoint": PRODUCTS_PATH, "client_supported": {"types": list(CONTENT_TYPES), "modes": list(CONTENT_MODES), "max_per_page": MAX_PER_PAGE}, "server_availability": {"status": "unknown_until_capabilities", "command": "capabilities", "endpoint": CAPABILITIES_PATH, "description": "客户端支持不等于生产服务已部署；请用 capabilities 做实时确认。"}, "endpoints": {"legacy_products": PRODUCTS_PATH, "typed_collection": CONTENT_PATH, "typed_record": f"{CONTENT_PATH}/TYPE/ID", "capabilities": CAPABILITIES_PATH}, "modes": {"product_detail": {"meaning": "成品产品目录", "facet": "category", "filters": ["category", "search", "code"]}, "scene_detail": {"meaning": "空间/场景方案目录", "facet": "space", "filters": ["space", "search", "code"]}}, "commands": {"describe": "读取本地客户端说明。", "schema": "读取本地兼容 schema。", "capabilities": "实时 GET 服务端内容能力。", "list": "无 --type 时读取旧 products；有 --type 时读取统一内容集合。", "get": "无 --type 时按 SKU 读取旧 products；统一内容按 --id，product/scene 也支持 --code。", "search": "按旧 products 或统一内容接口搜索。"}, "query_rules": {"search": "参数名是 search。", "code": "旧产品接口按完整 SKU 查询并转为大写。", "pagination": f"per_page 范围为 1–{MAX_PER_PAGE}。"}, "compatibility": {"no_type": "保留旧 products endpoint、presentation-mode、category、space 和 --code 行为。", "typed": "--type 显式启用统一 content endpoint。"}, "pagination": f"--per-page 范围为 1–{MAX_PER_PAGE}；--all-pages 受服务端 total_pages 且最多抓取 {MAX_PER_PAGE} 页。"}


def _fetch_command(args: argparse.Namespace) -> dict[str, t.Any]:
    typed = bool(args.content_type)
    _reject(args.command == "get" and args.all_pages, "get 不能使用 --all-pages。")
    if not typed:
        _reject(bool(args.record_id or args.mode), "未指定 --type 时不能使用 --id 或 --mode；旧行为请使用 products 参数。")
        _reject(args.command == "get" and bool(args.search), "旧 get 不能使用 --search，请使用 --code。")
        _reject(args.command == "search" and bool(args.code), "旧 search 不支持 --code；请使用 --search，或带 --type 的统一内容查询。")
        _reject(args.command != "get" and bool(args.record_id), "--id 只适用于带 --type 的 get。")
        _reject(args.command == "get" and not args.code, "旧 get 必须提供 --code。")
        url, endpoint, query = _legacy_url(args)
    else:
        url, endpoint, query = _typed_url(args)
    site_url = _normalise_site_url(args.site_url)
    status, data, headers = _read_json(url, args.timeout)
    if typed and args.command == "get":
        data = _as_collection(data, requested_mode=args.mode)
    if args.all_pages:
        status, data, headers = _fetch_all_pages(args, data, typed=typed, status=status, headers=headers)
        query = dict(query, all_pages=True)
    if args.command == "get" and not data.get("items"):
        label = args.record_id or str(args.code).strip().upper()
        raise PublicContentError(f"没有找到公开记录：{label}", code="not_found", details={"id": args.record_id, "code": args.code, "query": query})
    return _success(args.command, site_url=site_url, endpoint=endpoint, query=query, status=status, data=data, headers=headers)


def main(argv: list[str] | None = None, *, stdout: t.TextIO | None = None) -> int:
    stdout = stdout or sys.stdout
    try:
        args = build_parser().parse_args(list(argv if argv is not None else sys.argv[1:]))
        if args.command == "describe":
            payload = _local_success("describe", _describe_data())
        elif args.command == "schema":
            payload = _local_success("schema", _schema_data())
        elif args.command == "capabilities":
            site_url = _normalise_site_url(args.site_url)
            status, data, headers = _read_json(site_url + CAPABILITIES_PATH, args.timeout)
            payload = _success("capabilities", site_url=site_url, endpoint=CAPABILITIES_PATH, query={}, status=status, data=data, headers=headers)
        else:
            payload = _fetch_command(args)
        stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0
    except SystemExit:
        raise
    except PublicContentError as exc:
        stdout.write(json.dumps(_failure(getattr(locals().get("args", None), "command", None), exc), ensure_ascii=False, indent=2) + "\n")
        return 2 if exc.code == "argument_error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
