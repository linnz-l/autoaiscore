import feedparser
from datetime import datetime, timedelta, timezone
import json
import requests
import os
import openai

# ================= 核心配置区域 =================
# 1. 替换为你自己在 PubMed 生成的 RSS 订阅链接
rss_url = "https://pubmed.ncbi.nlm.nih.gov/rss/search/?term=nutrition+%5Bjournal%5D+OR+%22American+Journal+of+Clinical+Nutrition%22+%5Bjournal%5D+OR+%22Journal+of+Nutrition%22+%5Bjournal%5D&limit=20"

# 2. 定制你的 AI 评审角色（在此处修改你的学科领域，比如把环境科学改成你的专业）
SYSTEM_PROMPT = "You are a leading nutrition science expert and clinical dietitian. You are skilled at selecting robust, high-quality, and groundbreaking nutritional research, clinical trials, and dietary studies."
# ===============================================

access_token = os.getenv('GITHUB_TOKEN')
openaiapikey = os.getenv('OPENAI_API_KEY')

# 【关键改动】这里配置了 DeepSeek 的官方服务器地址
client = openai.OpenAI(
    api_key=openaiapikey,
    base_url="https://api.deepseek.com/v1"
)

def extract_scores(text):
    # 使用 DeepSeek 目前最高性价比的 V3 模型 (deepseek-chat)
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Given the text '{text}', evaluate this article with two scores:\n"
                                        "1. Research Score (0-100): Based on research innovation, methodological rigor, and data reliability.\n"
                                        "2. Social Impact Score (0-100): Based on public attention, policy relevance, and societal impact.\n"
                                        "Provide the scores in the following format:\n"
                                        "Research Score: <score>\n"
                                        "Social Impact Score: <score>"}
        ],
        max_tokens=100,
        temperature=0.5
    )

    generated_text = response.choices[0].message.content.strip()  

    # 提取评分提取
    try:
        research_score_start = generated_text.find("Research Score:")
        research_score = generated_text[research_score_start+len("Research Score:"):].split("\n")[0].strip()

        social_impact_score_start = generated_text.find("Social Impact Score:")
        social_impact_score = generated_text[social_impact_score_start+len("Social Impact Score:"):].strip()
    except Exception:
        research_score, social_impact_score = "N/A", "N/A"

    return research_score, social_impact_score

def get_pubmed_abstracts(rss_url):
    abstracts_with_urls = []
    feed = feedparser.parse(rss_url)
    one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)

    for entry in feed.entries:
        published_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z')
        if published_date >= one_week_ago:
            title = entry.title
            abstract = entry.content[0].value if 'content' in entry else entry.summary
            doi = entry.get('dc_identifier', 'No DOI available')
            abstracts_with_urls.append({"title": title, "abstract": abstract, "doi": doi})

    return abstracts_with_urls

# 获取并评分
pubmed_abstracts = get_pubmed_abstracts(rss_url)
new_articles_data = []

for abstract_data in pubmed_abstracts:
    title = abstract_data["title"]
    research_score, social_impact_score = extract_scores(abstract_data["abstract"])
    doi = abstract_data["doi"]

    new_articles_data.append({
        "title": title,
        "research_score": research_score,
        "social_impact_score": social_impact_score,
        "doi": doi
    })
    
# 生成 Issue 内容
issue_title = f"Weekly Article Matching (DeepSeek) - {datetime.now().strftime('%Y-%m-%d')}"
issue_body = "Below are the article matching results from the past week:\n\n"

for article_data in new_articles_data:
    issue_body += f"- **Title**: {article_data['title']}\n"
    issue_body += f"  **Research Score**: {article_data['research_score']}\n"
    issue_body += f"  **Social Impact Score**: {article_data['social_impact_score']}\n"
    issue_body += f"  **DOI**: {article_data['doi']}\n\n"

def create_github_issue(title, body, access_token):
    # 动态获取当前仓库路径，自动推送到你的当前仓库 issue 中
    repo = os.getenv('GITHUB_REPOSITORY')
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"title": title, "body": body}
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code == 201:
        print("Issue created successfully!")
    else:
        print("Failed to create issue:", response.text)

create_github_issue(issue_title, issue_body, access_token)
