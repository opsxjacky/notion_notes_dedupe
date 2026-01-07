#!/usr/bin/env python3
"""
Notion 苹果笔记数据库去重脚本

使用方法:
1. 设置环境变量 NOTION_TOKEN (Notion Integration Token)
2. 修改 DATABASE_ID 为你的苹果笔记同步数据库 ID
3. 运行: python notion_dedupe.py

去重逻辑:
- 按「名称」字段识别重复
- 保留最新的记录（按创建时间）
- 归档/删除较旧的重复记录
"""

import os
import sys
import argparse
import requests
from collections import defaultdict
from datetime import datetime

# 配置
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
if not NOTION_TOKEN:
    print("错误: 请设置环境变量 NOTION_TOKEN")
    print("例如: export NOTION_TOKEN='your_token_here'")
    exit(1)

DATABASE_ID = "2df4538c-fc22-80a8-a9c2-e213711c1efa"  # 苹果笔记同步数据库

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def query_database(database_id, start_cursor=None):
    """查询数据库所有记录"""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload = {"page_size": 100}
    if start_cursor:
        payload["start_cursor"] = start_cursor
    
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

def get_all_pages(database_id):
    """获取数据库中的所有页面"""
    all_pages = []
    has_more = True
    start_cursor = None
    
    while has_more:
        result = query_database(database_id, start_cursor)
        all_pages.extend(result.get("results", []))
        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")
    
    return all_pages

def extract_page_info(page):
    """从页面中提取关键信息"""
    page_id = page["id"]
    
    # 获取标题
    title = ""
    title_prop = page.get("properties", {}).get("名称", {})
    if title_prop.get("title"):
        title = "".join([t.get("plain_text", "") for t in title_prop["title"]])
    
    # 获取正文
    content = ""
    content_prop = page.get("properties", {}).get("正文", {})
    if content_prop.get("rich_text"):
        content = "".join([t.get("plain_text", "") for t in content_prop["rich_text"]])
    
    # 获取创建时间
    created_time = page.get("created_time", "")
    
    return {
        "id": page_id,
        "title": title.strip(),
        "content": content.strip(),
        "created_time": created_time,
        "url": page.get("url", "")
    }

def find_duplicates(pages):
    """找出重复的页面"""
    # 按标题分组
    by_title = defaultdict(list)
    for page in pages:
        if page["title"]:  # 忽略空标题
            by_title[page["title"]].append(page)
    
    # 找出有重复的
    duplicates = {}
    for title, page_list in by_title.items():
        if len(page_list) > 1:
            # 按创建时间排序，最新的在前
            sorted_pages = sorted(
                page_list, 
                key=lambda x: x["created_time"], 
                reverse=True
            )
            duplicates[title] = {
                "keep": sorted_pages[0],      # 保留最新的
                "remove": sorted_pages[1:]     # 删除其他的
            }
    
    return duplicates

def archive_page(page_id):
    """归档（软删除）页面"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"archived": True}
    
    response = requests.patch(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

def main():
    parser = argparse.ArgumentParser(description="Notion 苹果笔记数据库去重脚本")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际执行归档")
    parser.add_argument("--auto", action="store_true", help="自动执行，无需确认（用于 CI/CD）")
    args = parser.parse_args()
    
    print("🔍 正在查询苹果笔记同步数据库...")
    
    # 获取所有页面
    all_pages = get_all_pages(DATABASE_ID)
    print(f"📝 共找到 {len(all_pages)} 条记录")
    
    # 提取页面信息
    pages_info = [extract_page_info(p) for p in all_pages]
    
    # 找出重复
    duplicates = find_duplicates(pages_info)
    
    if not duplicates:
        print("✅ 没有发现重复记录!")
        return
    
    print(f"\n⚠️  发现 {len(duplicates)} 组重复记录:\n")
    
    total_to_remove = 0
    for title, dup_info in duplicates.items():
        keep = dup_info["keep"]
        remove_list = dup_info["remove"]
        total_to_remove += len(remove_list)
        
        print(f"📋 「{title}」")
        keep_preview = keep['content'][:30] + "..." if keep['content'] else "(空)"
        print(f"   ✓ 保留: {keep['created_time'][:10]} - {keep_preview}")
        for r in remove_list:
            r_preview = r['content'][:30] + "..." if r['content'] else "(空)"
            print(f"   ✗ 删除: {r['created_time'][:10]} - {r_preview}")
        print()
    
    # dry-run 模式
    if args.dry_run:
        print(f"🔍 [DRY-RUN] 预览模式，共 {total_to_remove} 条记录将被归档，但不会实际执行")
        return
    
    # 自动模式（CI/CD）或交互确认
    if not args.auto:
        print(f"⚠️  将归档 {total_to_remove} 条重复记录")
        confirm = input("确认执行? (y/N): ").strip().lower()
        if confirm != 'y':
            print("❌ 已取消")
            return
    
    # 执行归档
    print("\n🗑️  正在归档重复记录...")
    for title, dup_info in duplicates.items():
        for page in dup_info["remove"]:
            try:
                archive_page(page["id"])
                print(f"   ✓ 已归档: {title}")
            except Exception as e:
                print(f"   ✗ 归档失败: {title} - {e}")
    
    print("\n✅ 去重完成!")

if __name__ == "__main__":
    main()
