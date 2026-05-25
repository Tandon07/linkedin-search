import json

# Check the latest fetched posts
data = json.load(open('data/fetched_posts_20260524_025526.json', 'r', encoding='utf-8'))
total = len(data)
has_url = sum(1 for p in data if p.get('post_url', '') != 'https://www.linkedin.com/feed/')
unique_urls = set(p.get('post_url', '') for p in data if p.get('post_url', '') != 'https://www.linkedin.com/feed/')

print(f"Total posts: {total}")
print(f"With URL: {has_url} ({100 * has_url // max(total, 1)}%)")
print(f"Unique URLs: {len(unique_urls)}")
print(f"Fallback (generic feed): {total - has_url}")
print()
for p in data:
    url = p.get('post_url', '')
    email = p.get('emails', [''])[0] if p.get('emails') else ''
    status = 'OK' if url != 'https://www.linkedin.com/feed/' else 'FALLBACK'
    print(f"  [{status:8s}] {email:40s} -> {url[:80]}")
